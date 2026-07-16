"""V1.2.2 TOC 编排：惰性识别（GET 首访自动跑免费层）、先成功后替换、失败状态语义。

全部同步 sqlite 操作 + 秒级本地解析，不引入后台任务（规格 D6）。
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, field

from ulid import ULID

from lumina.config import get_settings
from lumina.db.engine import get_connection
from lumina.db.models import (
    ChapterRow,
    PdfTocMetaRow,
    get_pdf_text_meta,
    get_pdf_text_pages_range,
    get_pdf_toc_meta,
    list_chapters,
    replace_chapters,
    upsert_pdf_toc_meta,
)
from lumina.logging import get_logger, log_with_fields
from lumina.providers.base import Provider
from lumina.toc.heuristic import recognize_from_pages
from lumina.toc.llm import estimate_cost_usd, estimate_tokens, recognize_with_llm
from lumina.toc.outline import extract_outline
from lumina.toc.types import TocItem
from lumina.projects.paths import project_pdf_path

logger = get_logger("lumina.toc")

TOC_STATUS_NONE = "none"
TOC_STATUS_READY = "ready"
TOC_STATUS_FAILED = "failed"

SOURCE_OUTLINE = "outline"
SOURCE_HEURISTIC = "heuristic"
SOURCE_LLM = "llm"


@dataclass
class TocResult:
    status: str
    source: str | None
    chapters: list[ChapterRow] = field(default_factory=list)
    llm_available: bool = False
    text_status: str = "none"
    error: str | None = None


def _text_status(conn, pdf_id: str) -> str:
    meta = get_pdf_text_meta(conn, pdf_id)
    return meta.status if meta is not None else "none"


def _result_from_db(conn, pdf_id: str, meta: PdfTocMetaRow) -> TocResult:
    text_status = _text_status(conn, pdf_id)
    return TocResult(
        status=meta.status,
        source=meta.source,
        chapters=list_chapters(conn, pdf_id) if meta.status == TOC_STATUS_READY else [],
        # LLM 入口：目录未就绪（none / failed）且全书文本可用（规格 §5 llm_available）
        llm_available=meta.status != TOC_STATUS_READY and text_status == "ok",
        text_status=text_status,
        error=meta.error,
    )


def _rows_from_items(pdf_id: str, items: list[TocItem]) -> list[ChapterRow]:
    """preorder TocItem → ChapterRow：用深度栈推导 parent_id。"""
    rows: list[ChapterRow] = []
    stack: list[tuple[int, str]] = []  # (depth, chapter_id)
    for idx, item in enumerate(items):
        chapter_id = f"chap_{ULID()}"
        while stack and stack[-1][0] >= item.depth:
            stack.pop()
        parent_id = stack[-1][1] if stack else None
        rows.append(
            ChapterRow(
                id=chapter_id,
                pdf_id=pdf_id,
                parent_id=parent_id,
                order_index=idx,
                depth=item.depth,
                title=item.title,
                start_page=item.page,
            )
        )
        stack.append((item.depth, chapter_id))
    return rows


def _persist_ready(conn, pdf_id: str, items: list[TocItem], source: str) -> None:
    """先成功后替换：校验通过的新结果在单事务内删旧写新（规格 D10）。"""
    rows = _rows_from_items(pdf_id, items)
    try:
        conn.execute("BEGIN IMMEDIATE")
        replace_chapters(conn, pdf_id, rows)
        upsert_pdf_toc_meta(
            conn,
            PdfTocMetaRow(
                pdf_id=pdf_id,
                status=TOC_STATUS_READY,
                source=source,
                chapter_count=len(rows),
                updated_at=int(time.time()),
                error=None,
            ),
        )
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise


def _load_all_pages(conn, pdf_id: str) -> list[tuple[int, str]]:
    meta = get_pdf_text_meta(conn, pdf_id)
    if meta is None or meta.status != "ok" or not meta.page_count:
        return []
    return get_pdf_text_pages_range(conn, pdf_id, 1, meta.page_count)


def run_free_recognition(project_id: str, pdf_id: str) -> TocResult:
    """第 1→2 层：outline 优先，无果且文本 ok 再启发式；两层皆免费本地秒级。"""
    conn = get_connection(project_id)
    items = extract_outline(project_pdf_path(project_id))
    source = SOURCE_OUTLINE
    if not items:
        pages = _load_all_pages(conn, pdf_id)
        if pages:
            items = recognize_from_pages(pages)
            source = SOURCE_HEURISTIC
    if items:
        _persist_ready(conn, pdf_id, items, source)
    else:
        upsert_pdf_toc_meta(
            conn,
            PdfTocMetaRow(
                pdf_id=pdf_id,
                status=TOC_STATUS_NONE,
                updated_at=int(time.time()),
            ),
        )
    meta = get_pdf_toc_meta(conn, pdf_id)
    result = _result_from_db(conn, pdf_id, meta)
    log_with_fields(
        logger,
        logging.INFO,
        "toc free recognition completed",
        pdf_id=pdf_id,
        project_id=project_id,
        status=result.status,
        source=result.source or "",
        chapter_count=len(result.chapters),
    )
    return result


def get_or_recognize(project_id: str, pdf_id: str) -> TocResult:
    """惰性识别：从未识别过（无 meta 行）→ 同步跑免费层；否则直接读库。"""
    conn = get_connection(project_id)
    meta = get_pdf_toc_meta(conn, pdf_id)
    if meta is None:
        return run_free_recognition(project_id, pdf_id)
    return _result_from_db(conn, pdf_id, meta)


def llm_estimate(project_id: str, pdf_id: str) -> dict | None:
    """花费预估；文本不可用（扫描版 / 未提取）→ None（端点映射 409）。"""
    conn = get_connection(project_id)
    pages = _load_all_pages(conn, pdf_id)
    if not pages:
        return None
    from lumina.toc.llm import build_sample

    sample = build_sample(pages, get_settings().lumina_toc_sample_max_chars)
    tokens = estimate_tokens(len(sample))
    try:
        from lumina import settings_store

        model = settings_store.get_current().default_model
    except RuntimeError:
        # settings_store 未 bootstrap（单测直连场景）：退回 env 默认模型
        model = get_settings().openai_model
    return {
        "model": model,
        "estimated_input_tokens": tokens,
        "estimated_cost": estimate_cost_usd(model, tokens),
        "currency": "USD",
    }


async def run_llm_recognition(project_id: str, pdf_id: str, provider: Provider) -> TocResult:
    """LLM 兜底；失败状态语义（规格 F1）：有旧 ready 目录 → 保留不动仅上抛；
    无旧目录 → 置 failed 记录 error 供前端展示。"""
    conn = get_connection(project_id)
    pages = _load_all_pages(conn, pdf_id)
    if not pages:
        raise LookupError("full-book text unavailable for LLM recognition")
    try:
        items = await recognize_with_llm(
            provider, pages, len(pages), get_settings().lumina_toc_sample_max_chars
        )
    except Exception as exc:
        meta = get_pdf_toc_meta(conn, pdf_id)
        if meta is None or meta.status != TOC_STATUS_READY:
            upsert_pdf_toc_meta(
                conn,
                PdfTocMetaRow(
                    pdf_id=pdf_id,
                    status=TOC_STATUS_FAILED,
                    updated_at=int(time.time()),
                    error=f"{type(exc).__name__}: {exc}"[:500],
                ),
            )
        log_with_fields(
            logger,
            logging.WARNING,
            "toc llm recognition failed",
            pdf_id=pdf_id,
            project_id=project_id,
            error=str(exc)[:200],
        )
        raise
    _persist_ready(conn, pdf_id, items, SOURCE_LLM)
    meta = get_pdf_toc_meta(conn, pdf_id)
    return _result_from_db(conn, pdf_id, meta)
