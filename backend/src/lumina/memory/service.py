"""V1.2.3 记忆跑批编排：分段快照 → 串行 LLM → 每单元落库断点 → 总结收口。

复用 V1.2.1 提取服务的进程内后台任务模式（规格 D4 方案 A）：
- 单章失败不中断整体（continue），跑完置 partial 可续跑；
- 取消协作式（单元间检查标志）；进程重启孤儿 running 由启动期降 partial；
- 跑批任务运行在事件循环上（LLM 调用为 async，DB 写为小事务），
  与请求处理共用 engine 连接，无跨线程 sqlite 问题。
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from dataclasses import dataclass

from ulid import ULID

from lumina import settings_store
from lumina.config import get_settings
from lumina.db.engine import get_connection
from lumina.db.models import (
    MemoryConceptRow,
    MemoryMetaRow,
    MemoryUnitRow,
    count_ok_memory_units,
    delete_memory_all,
    get_memory_meta,
    get_pdf_text_char_counts,
    get_pdf_text_meta,
    get_pdf_text_pages_range,
    get_pdf_toc_meta,
    list_chapters,
    list_memory_units,
    list_running_memory_pdf_ids,
    replace_memory_units,
    replace_unit_concepts,
    set_memory_unit_result,
    upsert_memory_meta,
)
from lumina.logging import get_logger, log_with_fields
from lumina.memory.llm import (
    ConceptDraft,
    MemoryLlmInvalidError,
    summarize_book,
    summarize_unit,
)
from lumina.memory.segmenter import build_units
from lumina.pricing import estimate_cost_usd, estimate_tokens
from lumina.projects.catalog import list_entries
from lumina.providers.base import Provider, ProviderError

logger = get_logger("lumina.memory")

STATUS_NONE = "none"
STATUS_RUNNING = "running"
STATUS_PARTIAL = "partial"
STATUS_READY = "ready"
STATUS_FAILED = "failed"

# 花费预估常量：每单元 prompt 框架开销 / 每单元输出粗估 / 全书总结输出粗估（token）
_PROMPT_OVERHEAD_TOKENS = 300
_EST_OUTPUT_TOKENS_PER_UNIT = 800
_EST_BOOK_SUMMARY_OUTPUT_TOKENS = 600

# 进行中的跑批任务（pdf_id → Task）与协作式取消标志；单进程后端
_INFLIGHT: dict[str, asyncio.Task] = {}
_CANCEL: set[str] = set()


class MemoryUnavailableError(Exception):
    """全书文本未就绪 / 扫描版：记忆功能不可用（端点映射 409）。"""


class MemoryAlreadyReadyError(Exception):
    """记忆已完整（ready）：build 无事可做，应走 rebuild（端点映射 409）。"""


@dataclass
class MemoryState:
    meta: MemoryMetaRow | None
    units: list[MemoryUnitRow]
    toc_changed: bool


def _unit_max_chars() -> int:
    return get_settings().lumina_memory_unit_max_chars


def _resolve_model() -> str:
    try:
        cur = settings_store.get_current()
        return cur.task_models.get("memory") or cur.default_model
    except RuntimeError:
        # settings_store 未 bootstrap（单测直连场景）：退回 env 默认模型
        return get_settings().openai_model


def _model_override() -> str | None:
    try:
        return settings_store.get_current().task_models.get("memory")
    except RuntimeError:
        return None


def _toc_changed(conn, pdf_id: str, meta: MemoryMetaRow | None) -> bool:
    """快照绑定检测（规格 D3）：当前目录 updated_at 与建立记忆时不一致即视为变更。

    无目录快照（toc_source='pages'）的 toc_updated_at 为 None；此后目录出现
    （current 非 None）同样判为变更 → 提示可重建以获得按章记忆。
    """
    if meta is None:
        return False
    toc = get_pdf_toc_meta(conn, pdf_id)
    current = toc.updated_at if toc is not None and toc.status == "ready" else None
    return current != meta.toc_updated_at


def read_state(project_id: str, pdf_id: str) -> MemoryState:
    conn = get_connection(project_id)
    meta = get_memory_meta(conn, pdf_id)
    units = list_memory_units(conn, pdf_id) if meta is not None else []
    return MemoryState(meta=meta, units=units, toc_changed=_toc_changed(conn, pdf_id, meta))


def _require_text_ok(conn, pdf_id: str):
    text_meta = get_pdf_text_meta(conn, pdf_id)
    if text_meta is None or text_meta.status != "ok" or not text_meta.page_count:
        raise MemoryUnavailableError("full-book text unavailable")
    return text_meta


def _fresh_specs(conn, pdf_id: str, page_count: int):
    chapters = list_chapters(conn, pdf_id)
    char_counts = get_pdf_text_char_counts(conn, pdf_id)
    specs = build_units(chapters, page_count, char_counts, _unit_max_chars())
    if not specs:
        raise MemoryUnavailableError("no processable pages")
    return specs, char_counts


def estimate(project_id: str, pdf_id: str) -> dict:
    """花费预估（规格 F4）：首建/重建按全书，partial 续跑按剩余单元。"""
    conn = get_connection(project_id)
    text_meta = _require_text_ok(conn, pdf_id)
    meta = get_memory_meta(conn, pdf_id)
    units = list_memory_units(conn, pdf_id)
    char_counts = get_pdf_text_char_counts(conn, pdf_id)

    if meta is not None and meta.status in (STATUS_PARTIAL, STATUS_RUNNING) and units:
        remaining = [u for u in units if u.status != "ok"]
        scope = "remaining"
        unit_count = len(remaining)
        chars = sum(
            char_counts.get(p, 0)
            for u in remaining
            for p in range(u.start_page, u.end_page + 1)
        )
    else:
        specs, char_counts = _fresh_specs(conn, pdf_id, text_meta.page_count)
        scope = "full"
        unit_count = len(specs)
        chars = text_meta.char_count or sum(char_counts.values())

    # 输入 = 正文 + 每单元 prompt 开销 + 全书总结调用吃各章摘要
    input_tokens = (
        estimate_tokens(chars)
        + unit_count * _PROMPT_OVERHEAD_TOKENS
        + unit_count * _EST_OUTPUT_TOKENS_PER_UNIT
    )
    output_tokens = unit_count * _EST_OUTPUT_TOKENS_PER_UNIT + _EST_BOOK_SUMMARY_OUTPUT_TOKENS
    model = _resolve_model()
    return {
        "model": model,
        "scope": scope,
        "unit_count": unit_count,
        "estimated_input_tokens": input_tokens,
        "estimated_output_tokens": output_tokens,
        "estimated_cost": estimate_cost_usd(model, input_tokens, output_tokens),
        "currency": "USD",
    }


def _snapshot_fresh(conn, pdf_id: str, page_count: int, now: int) -> None:
    """分段快照 + meta 置 running（单事务；rebuild 与首建共用）。"""
    specs, _ = _fresh_specs(conn, pdf_id, page_count)
    toc = get_pdf_toc_meta(conn, pdf_id)
    if toc is not None and toc.status == "ready":
        toc_source, toc_updated = toc.source, toc.updated_at
    else:
        toc_source, toc_updated = "pages", None
    rows = [
        MemoryUnitRow(
            id=f"mu_{ULID()}", pdf_id=pdf_id, seq=i, title=s.title,
            start_page=s.start_page, end_page=s.end_page, status="pending",
        )
        for i, s in enumerate(specs)
    ]
    try:
        conn.execute("BEGIN IMMEDIATE")
        delete_memory_all(conn, pdf_id)
        replace_memory_units(conn, pdf_id, rows)
        upsert_memory_meta(
            conn,
            MemoryMetaRow(
                pdf_id=pdf_id, status=STATUS_RUNNING,
                toc_source=toc_source, toc_updated_at=toc_updated,
                unit_total=len(rows), unit_done=0, model=_resolve_model(),
                book_summary=None, created_at=now, updated_at=now, error=None,
            ),
        )
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise


def _schedule(project_id: str, pdf_id: str, provider: Provider) -> None:
    async def _runner() -> None:
        try:
            await _run_batch(project_id, pdf_id, provider)
        finally:
            _CANCEL.discard(pdf_id)
            _INFLIGHT.pop(pdf_id, None)

    _INFLIGHT[pdf_id] = asyncio.get_running_loop().create_task(_runner())


def start_build(project_id: str, pdf_id: str, provider: Provider) -> tuple[MemoryState, bool]:
    """启动/续跑记忆构建。必须在事件循环内调用（内部 `_schedule` 用 `get_running_loop()` 建任务）。"""
    existing = _INFLIGHT.get(pdf_id)
    if existing is not None and not existing.done():
        return read_state(project_id, pdf_id), False

    conn = get_connection(project_id)
    text_meta = _require_text_ok(conn, pdf_id)
    meta = get_memory_meta(conn, pdf_id)
    units = list_memory_units(conn, pdf_id)
    now = int(time.time())

    if meta is not None and meta.status == STATUS_READY:
        raise MemoryAlreadyReadyError
    if meta is None or meta.status == STATUS_FAILED or not units:
        _snapshot_fresh(conn, pdf_id, text_meta.page_count, now)
    else:
        # partial 续跑：保留单元快照，仅置回 running（模型按当前配置刷新）
        meta.status = STATUS_RUNNING
        meta.model = _resolve_model()
        meta.updated_at = now
        meta.error = None
        upsert_memory_meta(conn, meta)
    _schedule(project_id, pdf_id, provider)
    return read_state(project_id, pdf_id), True


def start_rebuild(project_id: str, pdf_id: str, provider: Provider) -> tuple[MemoryState, bool]:
    """重建记忆（清空快照重来）。必须在事件循环内调用（内部 `_schedule` 用 `get_running_loop()` 建任务）。"""
    existing = _INFLIGHT.get(pdf_id)
    if existing is not None and not existing.done():
        return read_state(project_id, pdf_id), False
    conn = get_connection(project_id)
    text_meta = _require_text_ok(conn, pdf_id)
    _snapshot_fresh(conn, pdf_id, text_meta.page_count, int(time.time()))
    _schedule(project_id, pdf_id, provider)
    return read_state(project_id, pdf_id), True


def request_cancel(project_id: str, pdf_id: str) -> MemoryState:
    task = _INFLIGHT.get(pdf_id)
    if task is not None and not task.done():
        _CANCEL.add(pdf_id)
    return read_state(project_id, pdf_id)


def _persist_unit_ok(
    conn, pdf_id: str, unit: MemoryUnitRow, summary: str, concepts: list[ConceptDraft]
) -> None:
    now = int(time.time())
    rows = [
        MemoryConceptRow(
            id=f"mc_{ULID()}", pdf_id=pdf_id, unit_id=unit.id,
            term=c.term, definition=c.definition, page=c.page, created_at=now,
        )
        for c in concepts
    ]
    try:
        conn.execute("BEGIN IMMEDIATE")
        set_memory_unit_result(conn, unit.id, status="ok", summary=summary, error=None, updated_at=now)
        replace_unit_concepts(conn, unit.id, rows)
        done = count_ok_memory_units(conn, pdf_id)
        conn.execute(
            "UPDATE memory_meta SET unit_done = ?, updated_at = ? WHERE pdf_id = ?",
            (done, now, pdf_id),
        )
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise


def _finish(conn, pdf_id: str, *, status: str, error: str | None, book_summary: str | None = None) -> None:
    meta = get_memory_meta(conn, pdf_id)
    if meta is None:
        return
    meta.status = status
    meta.error = error
    meta.updated_at = int(time.time())
    if book_summary is not None:
        meta.book_summary = book_summary
    upsert_memory_meta(conn, meta)


async def _run_batch(project_id: str, pdf_id: str, provider: Provider) -> None:
    conn = get_connection(project_id)
    override = _model_override()
    started = time.perf_counter()
    cancelled = False
    try:
        pending = [u for u in list_memory_units(conn, pdf_id) if u.status != "ok"]
        for unit in pending:
            if pdf_id in _CANCEL:
                cancelled = True
                break
            pages = get_pdf_text_pages_range(conn, pdf_id, unit.start_page, unit.end_page)
            try:
                summary, concepts = await summarize_unit(
                    provider, model_override=override, title=unit.title,
                    pages=pages, start_page=unit.start_page, end_page=unit.end_page,
                )
            except (MemoryLlmInvalidError, ProviderError) as exc:
                set_memory_unit_result(
                    conn, unit.id, status="failed", summary=None,
                    error=f"{type(exc).__name__}: {exc}"[:500], updated_at=int(time.time()),
                )
                continue
            _persist_unit_ok(conn, pdf_id, unit, summary, concepts)

        remaining = [u for u in list_memory_units(conn, pdf_id) if u.status != "ok"]
        if cancelled or pdf_id in _CANCEL:
            # 末尾复查：全部单元跑完后、进入总结分支前，若取消已到达也不再花钱调用
            # summarize_book（并避免删除书籍时 wait_for_pdf(timeout=30) 卡等总结调用）。
            _finish(conn, pdf_id, status=STATUS_PARTIAL, error="用户取消")
        elif remaining:
            _finish(conn, pdf_id, status=STATUS_PARTIAL, error=f"{len(remaining)} 个章节加工失败")
        else:
            ok_units = list_memory_units(conn, pdf_id)
            try:
                book = await summarize_book(
                    provider, model_override=override,
                    items=[(u.title, u.summary or "") for u in ok_units],
                )
                _finish(conn, pdf_id, status=STATUS_READY, error=None, book_summary=book)
            except (MemoryLlmInvalidError, ProviderError) as exc:
                _finish(
                    conn, pdf_id, status=STATUS_PARTIAL,
                    error=f"全书总结失败：{exc}"[:500],
                )
    except Exception as exc:
        # 兜底：意外异常不留孤儿 running；有产物 partial、零产物 failed
        done = count_ok_memory_units(conn, pdf_id)
        _finish(
            conn, pdf_id,
            status=STATUS_PARTIAL if done > 0 else STATUS_FAILED,
            error=f"{type(exc).__name__}: {exc}"[:500],
        )
        log_with_fields(
            logger, logging.WARNING, "memory batch crashed",
            pdf_id=pdf_id, project_id=project_id, error=str(exc)[:200],
        )
    finally:
        meta = get_memory_meta(conn, pdf_id)
        log_with_fields(
            logger, logging.INFO, "memory batch finished",
            pdf_id=pdf_id, project_id=project_id,
            status=meta.status if meta else "?",
            unit_done=meta.unit_done if meta else 0,
            unit_total=meta.unit_total if meta else 0,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


def recover_orphan_running() -> None:
    """启动期：进程崩溃 / 强杀留下的 running 一律降 partial（规格 F2.6）。"""
    for entry in list_entries():
        try:
            conn = get_connection(entry.id)
        except Exception:
            continue
        for pdf_id in list_running_memory_pdf_ids(conn):
            _finish(conn, pdf_id, status=STATUS_PARTIAL, error="进程重启中断，可继续")
            log_with_fields(
                logger, logging.INFO, "orphan running memory recovered",
                pdf_id=pdf_id, project_id=entry.id,
            )


async def shutdown_inflight(timeout: float = 10.0) -> None:
    """应用关闭前：置取消标志并等待；超时未收尾的由下次启动孤儿恢复兜底。"""
    tasks = [t for t in _INFLIGHT.values() if not t.done()]
    _CANCEL.update(_INFLIGHT.keys())
    if tasks:
        await asyncio.wait(tasks, timeout=timeout)


async def wait_for_pdf(pdf_id: str, timeout: float = 30.0) -> None:
    """删除书籍前：取消并等待该 PDF 的跑批收尾（Windows 下句柄占用与目录删除冲突）。"""
    task = _INFLIGHT.get(pdf_id)
    if task is not None and not task.done():
        _CANCEL.add(pdf_id)
        await asyncio.wait({task}, timeout=timeout)
