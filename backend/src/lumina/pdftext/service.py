"""V1.2.1 提取服务层：pending 落行、后台任务调度（幂等）、状态读取。"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time

from lumina.config import get_settings
from lumina.db.engine import get_connection
from lumina.db.models import (
    PdfTextMetaRow,
    get_pdf_text_meta,
    replace_pdf_text_pages,
    upsert_pdf_text_meta,
)
from lumina.logging import get_logger, log_with_fields
from lumina.pdftext.extractor import extract_pdf_text
from lumina.projects.paths import project_pdf_path, project_sqlite_path

logger = get_logger("lumina.pdftext")

STATUS_NONE = "none"
STATUS_PENDING = "pending"
STATUS_OK = "ok"
STATUS_UNSUPPORTED = "unsupported"
STATUS_FAILED = "failed"

# 进行中的提取任务（pdf_id → Task）；单进程后端，无需跨进程协调
_INFLIGHT: dict[str, asyncio.Task] = {}


def read_status(project_id: str, pdf_id: str) -> PdfTextMetaRow:
    """读取提取状态；无行 / 表缺失呈现为 status='none'（存量书籍初始态）。"""
    conn = get_connection(project_id)
    row = get_pdf_text_meta(conn, pdf_id)
    if row is None:
        return PdfTextMetaRow(pdf_id=pdf_id, status=STATUS_NONE)
    return row


def _open_worker_connection(project_id: str) -> sqlite3.Connection:
    """提取线程专用连接：不与 engine 连接缓存共享，避免应用关闭 close_all()
    时连接被从线程脚下关闭（跨线程共享 sqlite 连接会触发原生崩溃）。"""
    conn = sqlite3.connect(project_sqlite_path(project_id), isolation_level=None)
    conn.execute(
        f"PRAGMA busy_timeout = {get_settings().lumina_sqlite_busy_timeout_ms}"
    )
    return conn


def run_extraction_sync(project_id: str, pdf_id: str) -> PdfTextMetaRow:
    """同步执行一次全量提取并落库（设计为在线程池中运行）。

    重跑幂等：单事务内先删旧行再全量插入；失败落 status='failed' 可重试。
    """
    conn = _open_worker_connection(project_id)
    started = time.perf_counter()
    try:
        result = extract_pdf_text(project_pdf_path(project_id))
        status = STATUS_OK if result.is_textual_book else STATUS_UNSUPPORTED
        meta = PdfTextMetaRow(
            pdf_id=pdf_id,
            status=status,
            page_count=result.page_count,
            textual_page_count=result.textual_page_count,
            char_count=result.char_count,
            extractor=result.extractor,
            extracted_at=int(time.time()),
            error=None,
        )
        try:
            conn.execute("BEGIN IMMEDIATE")
            replace_pdf_text_pages(conn, pdf_id, result.page_texts)
            upsert_pdf_text_meta(conn, meta)
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        log_with_fields(
            logger,
            logging.INFO,
            "pdf text extraction completed",
            pdf_id=pdf_id,
            project_id=project_id,
            status=status,
            page_count=result.page_count,
            textual_page_count=result.textual_page_count,
            char_count=result.char_count,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return meta
    except Exception as exc:
        meta = PdfTextMetaRow(
            pdf_id=pdf_id,
            status=STATUS_FAILED,
            extracted_at=int(time.time()),
            error=f"{type(exc).__name__}: {exc}"[:500],
        )
        try:
            upsert_pdf_text_meta(conn, meta)
        except sqlite3.Error:
            pass
        log_with_fields(
            logger,
            logging.WARNING,
            "pdf text extraction failed",
            pdf_id=pdf_id,
            project_id=project_id,
            error=meta.error or "",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return meta
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass


def schedule_extraction(project_id: str, pdf_id: str) -> str:
    """落 pending 行并调度后台提取；进行中重复触发幂等返回 pending。

    须在事件循环内调用（导入端点 / 补提取端点）。
    """
    existing = _INFLIGHT.get(pdf_id)
    if existing is not None and not existing.done():
        return STATUS_PENDING

    conn = get_connection(project_id)
    upsert_pdf_text_meta(
        conn,
        PdfTextMetaRow(pdf_id=pdf_id, status=STATUS_PENDING),
    )

    async def _runner() -> None:
        try:
            await asyncio.to_thread(run_extraction_sync, project_id, pdf_id)
        finally:
            _INFLIGHT.pop(pdf_id, None)

    _INFLIGHT[pdf_id] = asyncio.get_running_loop().create_task(_runner())
    return STATUS_PENDING


async def wait_for_inflight(timeout: float = 30.0) -> None:
    """应用关闭前等待进行中的提取任务收尾（lifespan 调用）。"""
    tasks = [t for t in _INFLIGHT.values() if not t.done()]
    if tasks:
        await asyncio.wait(tasks, timeout=timeout)


async def wait_for_pdf(pdf_id: str, timeout: float = 30.0) -> None:
    """删除书籍前等待该 PDF 的进行中提取收尾（工作线程持有 sqlite / PDF 文件句柄，
    Windows 下与目录删除冲突）。"""
    task = _INFLIGHT.get(pdf_id)
    if task is not None and not task.done():
        await asyncio.wait({task}, timeout=timeout)
