import logging
import time as _time

from ulid import ULID

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from lumina.config import get_settings
from lumina.db.engine import get_connection
from lumina.db.models import (
    BookmarkRow,
    NoteRow,
    delete_bookmark,
    delete_note,
    get_pdf_text_meta,
    insert_bookmark,
    insert_note,
    list_bookmarks,
    list_notes,
    rename_bookmark,
    update_note,
    update_pdf_reading_position,
)
from lumina.logging import get_logger, log_with_fields
from lumina.projects.catalog import find_by_pdf_id
from lumina.projects.manager import (
    ProjectNameConflictError,
    auto_create_project,
    delete_project,
    touch_last_opened_at,
)
from lumina.projects.paths import project_pdf_path
from lumina.pdftext import read_status, schedule_extraction, wait_for_pdf
from lumina.providers import get_provider
from lumina.providers.base import Provider, ProviderError
from lumina.request_id import generate_request_id
from lumina.schemas.api import (
    BookmarkCreate,
    BookmarkRename,
    NoteCreate,
    NoteUpdate,
    PdfUploadData,
    ReadingPositionUpdate,
    error_response,
    ok_response,
)
from lumina.sessions import get_session_store
from lumina.toc import (
    TocResult,
    get_or_recognize,
    llm_estimate,
    run_free_recognition,
    run_llm_recognition,
)
from lumina.toc.llm import TocLlmInvalidError

router = APIRouter(prefix="/pdfs", tags=["pdfs"])
logger = get_logger("lumina.pdfs")

PDF_MAGIC = b"%PDF-"
MULTIPART_SAFETY_BUFFER = 64 * 1024
VALID_SORTS = frozenset({"last_opened_at_desc", "created_at_desc", "name_asc"})


def _parse_force_create_new(value: str) -> bool:
    return value.strip().lower() == "true"


def _log_pdf_call(
    *,
    request_id: str,
    http_status: int,
    error_code: str | None = None,
    pdf_id: str | None = None,
    project_id: str | None = None,
    pdf_size_bytes: int | None = None,
    force_create_new: bool | None = None,
) -> None:
    log_with_fields(
        logger,
        logging.INFO if error_code is None else logging.WARNING,
        "pdf endpoint completed",
        request_id=request_id,
        api_version="v1",
        http_status=http_status,
        error_code=error_code or "",
        pdf_id=pdf_id or "",
        project_id=project_id or "",
        pdf_size_bytes=pdf_size_bytes if pdf_size_bytes is not None else "",
        force_create_new=force_create_new if force_create_new is not None else "",
    )


@router.post("", status_code=201)
async def upload_pdf(
    request: Request,
    file: UploadFile = File(...),
    force_create_new: str = Form("false"),
):
    request_id = generate_request_id()
    settings = get_settings()
    max_bytes = settings.lumina_pdf_max_size_mb * 1024 * 1024
    forced = _parse_force_create_new(force_create_new)

    content_length = request.headers.get("content-length")
    if content_length is not None:
        if int(content_length) > max_bytes + MULTIPART_SAFETY_BUFFER:
            _log_pdf_call(
                request_id=request_id,
                http_status=413,
                error_code="PDF_TOO_LARGE",
                force_create_new=forced,
            )
            return JSONResponse(
                status_code=413,
                content=error_response(
                    code="PDF_TOO_LARGE",
                    message="PDF file exceeds the size limit.",
                    request_id=request_id,
                ),
            )

    if not file.filename:
        _log_pdf_call(
            request_id=request_id,
            http_status=400,
            error_code="INVALID_REQUEST",
            force_create_new=forced,
        )
        return JSONResponse(
            status_code=400,
            content=error_response(
                code="INVALID_REQUEST",
                message="Uploaded file must have a filename.",
                request_id=request_id,
            ),
        )

    file_bytes = await file.read()
    pdf_size = len(file_bytes)
    if pdf_size > max_bytes:
        _log_pdf_call(
            request_id=request_id,
            http_status=413,
            error_code="PDF_TOO_LARGE",
            pdf_size_bytes=pdf_size,
            force_create_new=forced,
        )
        return JSONResponse(
            status_code=413,
            content=error_response(
                code="PDF_TOO_LARGE",
                message="PDF file exceeds the size limit.",
                request_id=request_id,
            ),
        )

    if not file_bytes.startswith(PDF_MAGIC):
        _log_pdf_call(
            request_id=request_id,
            http_status=415,
            error_code="UNSUPPORTED_MEDIA_TYPE",
            pdf_size_bytes=pdf_size,
            force_create_new=forced,
        )
        return JSONResponse(
            status_code=415,
            content=error_response(
                code="UNSUPPORTED_MEDIA_TYPE",
                message="Only PDF files are supported.",
                request_id=request_id,
            ),
        )

    try:
        created = auto_create_project(
            file_bytes,
            file.filename,
            force_create_new=forced,
        )
    except ProjectNameConflictError as exc:
        existing = exc.existing
        _log_pdf_call(
            request_id=request_id,
            http_status=409,
            error_code="PROJECT_NAME_CONFLICT",
            pdf_size_bytes=pdf_size,
            force_create_new=forced,
            project_id=existing.id,
            pdf_id=existing.primary_pdf_id,
        )
        return JSONResponse(
            status_code=409,
            content=error_response(
                code="PROJECT_NAME_CONFLICT",
                message=f"已存在同名书《{existing.name}》",
                request_id=request_id,
                existing={
                    "pdf_id": existing.primary_pdf_id,
                    "name": existing.name,
                    "primary_pdf_filename": existing.primary_pdf_filename,
                    "primary_pdf_size": existing.primary_pdf_size,
                    "created_at": existing.created_at,
                    "last_opened_at": existing.last_opened_at,
                },
                force_create_new_hint=(
                    "重试时在表单中附加 force_create_new=true 可新建副本"
                ),
            ),
        )

    data = PdfUploadData(
        pdf_id=created.pdf_id,
        project_id=created.project_id,
        name=created.name,
        primary_pdf_filename=created.primary_pdf_filename,
        primary_pdf_size=created.primary_pdf_size,
        created_at=created.created_at,
    )
    # V1.2.1：导入即自动触发全书文本提取（后台异步，不阻塞上传响应）
    try:
        schedule_extraction(created.project_id, created.pdf_id)
    except Exception:
        logger.warning(
            "failed to schedule text extraction for pdf_id=%s", created.pdf_id
        )
    _log_pdf_call(
        request_id=request_id,
        http_status=201,
        pdf_id=created.pdf_id,
        project_id=created.project_id,
        pdf_size_bytes=pdf_size,
        force_create_new=forced,
    )
    return JSONResponse(status_code=201, content=ok_response(data))


@router.get("/{pdf_id}/raw")
async def get_pdf_raw(pdf_id: str):
    request_id = generate_request_id()
    entry = find_by_pdf_id(pdf_id)
    if entry is None:
        _log_pdf_call(
            request_id=request_id,
            http_status=404,
            error_code="PDF_NOT_FOUND",
            pdf_id=pdf_id,
        )
        return JSONResponse(
            status_code=404,
            content=error_response(
                code="PDF_NOT_FOUND",
                message="PDF not found.",
                request_id=request_id,
            ),
        )

    touch_last_opened_at(entry.id)
    path = project_pdf_path(entry.id)
    _log_pdf_call(
        request_id=request_id,
        http_status=200,
        pdf_id=pdf_id,
        project_id=entry.id,
    )
    return FileResponse(
        path=path,
        media_type="application/pdf",
        filename=entry.primary_pdf_filename,
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.delete("/{pdf_id}", status_code=204)
async def delete_pdf(pdf_id: str):
    request_id = generate_request_id()
    entry = find_by_pdf_id(pdf_id)
    if entry is None:
        _log_pdf_call(
            request_id=request_id,
            http_status=404,
            error_code="PDF_NOT_FOUND",
            pdf_id=pdf_id,
        )
        return JSONResponse(
            status_code=404,
            content=error_response(
                code="PDF_NOT_FOUND",
                message="PDF not found.",
                request_id=request_id,
            ),
        )

    try:
        store = get_session_store()
        await store.evict_by_pdf_id(entry.primary_pdf_id)
    except RuntimeError:
        pass

    # V1.2.1：等待该书进行中的文本提取收尾，避免 Windows 下句柄占用导致目录删除失败
    await wait_for_pdf(pdf_id)

    # V1.2.3：取消并等待该书进行中的记忆跑批收尾（同 Windows 句柄考量）
    from lumina.memory import wait_for_pdf as memory_wait_for_pdf

    await memory_wait_for_pdf(pdf_id)

    delete_project(entry.id)
    _log_pdf_call(
        request_id=request_id,
        http_status=204,
        pdf_id=pdf_id,
        project_id=entry.id,
    )
    return Response(status_code=204)


@router.patch("/{pdf_id}/reading-position", status_code=204)
async def patch_reading_position(pdf_id: str, payload: ReadingPositionUpdate):
    request_id = generate_request_id()
    entry = find_by_pdf_id(pdf_id)
    if entry is None:
        _log_pdf_call(
            request_id=request_id,
            http_status=404,
            error_code="PDF_NOT_FOUND",
            pdf_id=pdf_id,
        )
        return JSONResponse(
            status_code=404,
            content=error_response(
                code="PDF_NOT_FOUND",
                message="PDF not found.",
                request_id=request_id,
            ),
        )

    conn = get_connection(entry.id)
    updated = update_pdf_reading_position(
        conn, pdf_id, payload.last_read_page, payload.last_read_offset
    )
    if updated == 0:
        # catalog 与 sqlite 不一致（极端情况：手工破坏 sqlite 行），按 404 上报
        _log_pdf_call(
            request_id=request_id,
            http_status=404,
            error_code="PDF_NOT_FOUND",
            pdf_id=pdf_id,
            project_id=entry.id,
        )
        return JSONResponse(
            status_code=404,
            content=error_response(
                code="PDF_NOT_FOUND",
                message="PDF not found.",
                request_id=request_id,
            ),
        )

    _log_pdf_call(
        request_id=request_id,
        http_status=204,
        pdf_id=pdf_id,
        project_id=entry.id,
    )
    return Response(status_code=204)


def _pdf_not_found(request_id: str, pdf_id: str) -> JSONResponse:
    _log_pdf_call(
        request_id=request_id,
        http_status=404,
        error_code="PDF_NOT_FOUND",
        pdf_id=pdf_id,
    )
    return JSONResponse(
        status_code=404,
        content=error_response(
            code="PDF_NOT_FOUND",
            message="PDF not found.",
            request_id=request_id,
        ),
    )


@router.get("/{pdf_id}/text-extraction")
async def get_text_extraction(pdf_id: str):
    """V1.2.1：全书文本提取状态。status ∈ none|pending|ok|unsupported|failed。"""
    request_id = generate_request_id()
    entry = find_by_pdf_id(pdf_id)
    if entry is None:
        return _pdf_not_found(request_id, pdf_id)

    meta = read_status(entry.id, pdf_id)
    _log_pdf_call(
        request_id=request_id,
        http_status=200,
        pdf_id=pdf_id,
        project_id=entry.id,
    )
    return ok_response(
        {
            "pdf_id": pdf_id,
            "status": meta.status,
            "page_count": meta.page_count,
            "textual_page_count": meta.textual_page_count,
            "char_count": meta.char_count,
            "extracted_at": meta.extracted_at,
            "error": meta.error,
        }
    )


@router.post("/{pdf_id}/text-extraction", status_code=202)
async def trigger_text_extraction(pdf_id: str):
    """V1.2.1：手动触发（重新）提取；进行中重复触发幂等返回 202 pending。"""
    request_id = generate_request_id()
    entry = find_by_pdf_id(pdf_id)
    if entry is None:
        return _pdf_not_found(request_id, pdf_id)

    status = schedule_extraction(entry.id, pdf_id)
    _log_pdf_call(
        request_id=request_id,
        http_status=202,
        pdf_id=pdf_id,
        project_id=entry.id,
    )
    return JSONResponse(
        status_code=202,
        content=ok_response({"pdf_id": pdf_id, "status": status}),
    )


def _summarize(text: str, n: int = 200) -> str:
    if len(text) <= n:
        return text
    return text[:n] + "…"


@router.get("/{pdf_id}/conversations")
async def list_pdf_conversations(pdf_id: str, include_cleared: bool = False):
    from lumina.db.engine import get_connection
    from lumina.db.models import (
        count_messages,
        get_first_assistant_message,
        get_selection,
        list_conversations_by_pdf,
    )

    request_id = generate_request_id()
    entry = find_by_pdf_id(pdf_id)
    if entry is None:
        _log_pdf_call(
            request_id=request_id,
            http_status=404,
            error_code="PDF_NOT_FOUND",
            pdf_id=pdf_id,
        )
        return JSONResponse(
            status_code=404,
            content=error_response(
                code="PDF_NOT_FOUND",
                message="PDF not found.",
                request_id=request_id,
            ),
        )

    conn = get_connection(entry.id)
    rows = list_conversations_by_pdf(conn, pdf_id, include_cleared=include_cleared)
    items = []
    for conv in rows:
        selection = get_selection(conn, conv.selection_id)
        first_assistant = get_first_assistant_message(conn, conv.id)
        summary_text = first_assistant.content if first_assistant else ""
        items.append(
            {
                "conversation_id": conv.id,
                "task_type": conv.task_type,
                "selection": {
                    "page": selection.page if selection else 0,
                    "x": selection.x if selection else 0.0,
                    "y": selection.y if selection else 0.0,
                    "w": selection.w if selection else 0.0,
                    "h": selection.h if selection else 0.0,
                },
                "thumbnail_url": None,
                "first_assistant_summary": _summarize(summary_text),
                "status": conv.status,
                "created_at": conv.created_at,
                "last_used_at": conv.last_used_at,
                "message_count": count_messages(conn, conv.id),
            }
        )

    _log_pdf_call(
        request_id=request_id,
        http_status=200,
        pdf_id=pdf_id,
        project_id=entry.id,
    )
    return ok_response({"items": items})


# ---------------------------------------------------------------------------
# V1.2.2: 目录（TOC）端点
# ---------------------------------------------------------------------------


def _toc_payload(pdf_id: str, result: TocResult) -> dict:
    return {
        "pdf_id": pdf_id,
        "status": result.status,
        "source": result.source,
        "chapters": [
            {
                "id": c.id,
                "title": c.title,
                "page": c.start_page,
                "depth": c.depth,
                "parent_id": c.parent_id,
                "order_index": c.order_index,
            }
            for c in result.chapters
        ],
        "llm_available": result.llm_available,
        "text_status": result.text_status,
        "error": result.error,
    }


@router.get("/{pdf_id}/toc")
async def get_toc(pdf_id: str):
    """惰性识别：首次访问自动跑第 1→2 层（本地秒级），已识别直接读库。"""
    request_id = generate_request_id()
    entry = find_by_pdf_id(pdf_id)
    if entry is None:
        return _pdf_not_found(request_id, pdf_id)
    result = get_or_recognize(entry.id, pdf_id)
    _log_pdf_call(request_id=request_id, http_status=200, pdf_id=pdf_id, project_id=entry.id)
    return ok_response(_toc_payload(pdf_id, result))


@router.post("/{pdf_id}/toc/recognize")
async def recognize_toc(pdf_id: str):
    """强制按第 1→2 层重跑（"重新识别"入口）；LLM 层永远只走 recognize-llm。"""
    request_id = generate_request_id()
    entry = find_by_pdf_id(pdf_id)
    if entry is None:
        return _pdf_not_found(request_id, pdf_id)
    result = run_free_recognition(entry.id, pdf_id)
    _log_pdf_call(request_id=request_id, http_status=200, pdf_id=pdf_id, project_id=entry.id)
    return ok_response(_toc_payload(pdf_id, result))


def _toc_llm_unavailable(request_id: str, pdf_id: str, project_id: str) -> JSONResponse:
    _log_pdf_call(
        request_id=request_id,
        http_status=409,
        error_code="TOC_LLM_UNAVAILABLE",
        pdf_id=pdf_id,
        project_id=project_id,
    )
    return JSONResponse(
        status_code=409,
        content=error_response(
            code="TOC_LLM_UNAVAILABLE",
            message="全书文本不可用（扫描版或尚未提取），无法进行 AI 目录识别。",
            request_id=request_id,
        ),
    )


@router.get("/{pdf_id}/toc/llm-estimate")
async def get_toc_llm_estimate(pdf_id: str):
    """LLM 识别前的花费预估（规格 D9：token 估算 + 单价表金额，未命中 cost=null）。"""
    request_id = generate_request_id()
    entry = find_by_pdf_id(pdf_id)
    if entry is None:
        return _pdf_not_found(request_id, pdf_id)
    estimate = llm_estimate(entry.id, pdf_id)
    if estimate is None:
        return _toc_llm_unavailable(request_id, pdf_id, entry.id)
    _log_pdf_call(request_id=request_id, http_status=200, pdf_id=pdf_id, project_id=entry.id)
    return ok_response(estimate)


@router.post("/{pdf_id}/toc/recognize-llm")
async def recognize_toc_llm(pdf_id: str, provider: Provider = Depends(get_provider)):
    """用户确认花费后的一次性 LLM 识别；失败旧目录保留（规格 D10 / F1）。"""
    request_id = generate_request_id()
    entry = find_by_pdf_id(pdf_id)
    if entry is None:
        return _pdf_not_found(request_id, pdf_id)
    try:
        result = await run_llm_recognition(entry.id, pdf_id, provider)
    except LookupError:
        return _toc_llm_unavailable(request_id, pdf_id, entry.id)
    except TocLlmInvalidError as exc:
        _log_pdf_call(
            request_id=request_id,
            http_status=422,
            error_code="TOC_LLM_INVALID",
            pdf_id=pdf_id,
            project_id=entry.id,
        )
        return JSONResponse(
            status_code=422,
            content=error_response(
                code="TOC_LLM_INVALID",
                message=f"AI 返回的目录结构不合法，可重试。（{exc}）",
                request_id=request_id,
            ),
        )
    except ProviderError as exc:
        _log_pdf_call(
            request_id=request_id,
            http_status=502,
            error_code="TOC_LLM_FAILED",
            pdf_id=pdf_id,
            project_id=entry.id,
        )
        return JSONResponse(
            status_code=502,
            content=error_response(
                code="TOC_LLM_FAILED",
                message=f"AI 目录识别调用失败，可重试。（{exc.message}）",
                request_id=request_id,
            ),
        )
    _log_pdf_call(request_id=request_id, http_status=200, pdf_id=pdf_id, project_id=entry.id)
    return ok_response(_toc_payload(pdf_id, result))


# ---------------------------------------------------------------------------
# V1.2.2: 书签端点
# ---------------------------------------------------------------------------


def _bookmark_payload(row: BookmarkRow) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "page": row.page,
        "offset_ratio": row.offset_ratio,
        "created_at": row.created_at,
    }


@router.get("/{pdf_id}/bookmarks")
async def get_bookmarks(pdf_id: str):
    request_id = generate_request_id()
    entry = find_by_pdf_id(pdf_id)
    if entry is None:
        return _pdf_not_found(request_id, pdf_id)
    conn = get_connection(entry.id)
    rows = list_bookmarks(conn, pdf_id)
    _log_pdf_call(request_id=request_id, http_status=200, pdf_id=pdf_id, project_id=entry.id)
    return ok_response({"bookmarks": [_bookmark_payload(r) for r in rows]})


@router.post("/{pdf_id}/bookmarks", status_code=201)
async def create_bookmark(pdf_id: str, payload: BookmarkCreate):
    request_id = generate_request_id()
    entry = find_by_pdf_id(pdf_id)
    if entry is None:
        return _pdf_not_found(request_id, pdf_id)
    conn = get_connection(entry.id)
    # 页码上界仅在全书文本已提取（page_count 可知）时校验；下界由 pydantic ge=1 保证
    text_meta = get_pdf_text_meta(conn, pdf_id)
    if text_meta is not None and text_meta.page_count and payload.page > text_meta.page_count:
        _log_pdf_call(
            request_id=request_id,
            http_status=422,
            error_code="BOOKMARK_PAGE_OUT_OF_RANGE",
            pdf_id=pdf_id,
            project_id=entry.id,
        )
        return JSONResponse(
            status_code=422,
            content=error_response(
                code="BOOKMARK_PAGE_OUT_OF_RANGE",
                message=f"页码超出范围（全书共 {text_meta.page_count} 页）。",
                request_id=request_id,
            ),
        )
    row = BookmarkRow(
        id=f"bm_{ULID()}",
        pdf_id=pdf_id,
        name=(payload.name or "").strip() or f"第 {payload.page} 页",
        page=payload.page,
        offset_ratio=payload.offset_ratio,
        created_at=int(_time.time()),
    )
    insert_bookmark(conn, row)
    _log_pdf_call(request_id=request_id, http_status=201, pdf_id=pdf_id, project_id=entry.id)
    return JSONResponse(status_code=201, content=ok_response(_bookmark_payload(row)))


@router.patch("/{pdf_id}/bookmarks/{bookmark_id}")
async def patch_bookmark(pdf_id: str, bookmark_id: str, payload: BookmarkRename):
    request_id = generate_request_id()
    entry = find_by_pdf_id(pdf_id)
    if entry is None:
        return _pdf_not_found(request_id, pdf_id)
    conn = get_connection(entry.id)
    updated = rename_bookmark(conn, pdf_id, bookmark_id, payload.name.strip())
    if updated == 0:
        _log_pdf_call(
            request_id=request_id,
            http_status=404,
            error_code="BOOKMARK_NOT_FOUND",
            pdf_id=pdf_id,
            project_id=entry.id,
        )
        return JSONResponse(
            status_code=404,
            content=error_response(
                code="BOOKMARK_NOT_FOUND",
                message="Bookmark not found.",
                request_id=request_id,
            ),
        )
    _log_pdf_call(request_id=request_id, http_status=200, pdf_id=pdf_id, project_id=entry.id)
    return ok_response({"id": bookmark_id, "name": payload.name.strip()})


@router.delete("/{pdf_id}/bookmarks/{bookmark_id}", status_code=204)
async def remove_bookmark(pdf_id: str, bookmark_id: str):
    request_id = generate_request_id()
    entry = find_by_pdf_id(pdf_id)
    if entry is None:
        return _pdf_not_found(request_id, pdf_id)
    conn = get_connection(entry.id)
    delete_bookmark(conn, pdf_id, bookmark_id)  # 重复删除幂等：rowcount=0 也返回 204
    _log_pdf_call(request_id=request_id, http_status=204, pdf_id=pdf_id, project_id=entry.id)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# V1.2.5: 笔记端点
# ---------------------------------------------------------------------------


def _note_payload(row: NoteRow) -> dict:
    return {
        "id": row.id,
        "content": row.content,
        "page": row.page,
        "offset_ratio": row.offset_ratio,
        "anchor_text": row.anchor_text,
        "anchor_rects_json": row.anchor_rects_json,
        "source": row.source,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "title": row.title,
    }


@router.get("/{pdf_id}/notes")
async def get_notes(pdf_id: str):
    request_id = generate_request_id()
    entry = find_by_pdf_id(pdf_id)
    if entry is None:
        return _pdf_not_found(request_id, pdf_id)
    conn = get_connection(entry.id)
    rows = list_notes(conn, pdf_id)
    _log_pdf_call(request_id=request_id, http_status=200, pdf_id=pdf_id, project_id=entry.id)
    return ok_response({"notes": [_note_payload(r) for r in rows]})


@router.post("/{pdf_id}/notes", status_code=201)
async def create_note(pdf_id: str, payload: NoteCreate):
    request_id = generate_request_id()
    entry = find_by_pdf_id(pdf_id)
    if entry is None:
        return _pdf_not_found(request_id, pdf_id)
    conn = get_connection(entry.id)
    # 页码上界仅在全书文本已提取（page_count 可知）时校验；下界由 pydantic ge=1 保证（同书签先例）
    text_meta = get_pdf_text_meta(conn, pdf_id)
    if text_meta is not None and text_meta.page_count and payload.page > text_meta.page_count:
        _log_pdf_call(
            request_id=request_id,
            http_status=422,
            error_code="NOTE_PAGE_OUT_OF_RANGE",
            pdf_id=pdf_id,
            project_id=entry.id,
        )
        return JSONResponse(
            status_code=422,
            content=error_response(
                code="NOTE_PAGE_OUT_OF_RANGE",
                message=f"页码超出范围（全书共 {text_meta.page_count} 页）。",
                request_id=request_id,
            ),
        )
    now = int(_time.time())
    row = NoteRow(
        id=f"nt_{ULID()}",
        pdf_id=pdf_id,
        content=payload.content,
        page=payload.page,
        offset_ratio=payload.offset_ratio,
        anchor_text=payload.anchor_text,
        anchor_rects_json=payload.anchor_rects_json,
        source=payload.source,
        created_at=now,
        updated_at=now,
        title=payload.title,
    )
    insert_note(conn, row)
    _log_pdf_call(request_id=request_id, http_status=201, pdf_id=pdf_id, project_id=entry.id)
    return JSONResponse(status_code=201, content=ok_response(_note_payload(row)))


@router.patch("/{pdf_id}/notes/{note_id}")
async def patch_note(pdf_id: str, note_id: str, payload: NoteUpdate):
    request_id = generate_request_id()
    entry = find_by_pdf_id(pdf_id)
    if entry is None:
        return _pdf_not_found(request_id, pdf_id)
    conn = get_connection(entry.id)
    now = int(_time.time())
    updated = update_note(
        conn, pdf_id, note_id, content=payload.content, title=payload.title, updated_at=now
    )
    if updated == 0:
        _log_pdf_call(
            request_id=request_id,
            http_status=404,
            error_code="NOTE_NOT_FOUND",
            pdf_id=pdf_id,
            project_id=entry.id,
        )
        return JSONResponse(
            status_code=404,
            content=error_response(
                code="NOTE_NOT_FOUND",
                message="Note not found.",
                request_id=request_id,
            ),
        )
    # 部分更新下回显请求值会失真，改为回读整行返回完整 payload
    row = next((r for r in list_notes(conn, pdf_id) if r.id == note_id), None)
    _log_pdf_call(request_id=request_id, http_status=200, pdf_id=pdf_id, project_id=entry.id)
    return ok_response(_note_payload(row))


@router.delete("/{pdf_id}/notes/{note_id}", status_code=204)
async def remove_note(pdf_id: str, note_id: str):
    request_id = generate_request_id()
    entry = find_by_pdf_id(pdf_id)
    if entry is None:
        return _pdf_not_found(request_id, pdf_id)
    conn = get_connection(entry.id)
    delete_note(conn, pdf_id, note_id)  # 重复删除幂等：rowcount=0 也返回 204
    _log_pdf_call(request_id=request_id, http_status=204, pdf_id=pdf_id, project_id=entry.id)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# V1.2.3: 记忆加工（memory）端点
# ---------------------------------------------------------------------------

from lumina.memory import (  # noqa: E402
    MemoryAlreadyReadyError,
    MemoryState,
    MemoryUnavailableError,
)
from lumina.memory import (  # noqa: E402
    estimate as memory_estimate,
)
from lumina.memory import (  # noqa: E402
    read_state as memory_read_state,
)
from lumina.memory import (  # noqa: E402
    request_cancel as memory_request_cancel,
)
from lumina.memory import (  # noqa: E402
    start_build as memory_start_build,
)
from lumina.memory import (  # noqa: E402
    start_rebuild as memory_start_rebuild,
)


def _memory_payload(pdf_id: str, state: MemoryState) -> dict:
    meta = state.meta
    return {
        "pdf_id": pdf_id,
        "status": meta.status if meta else "none",
        "unit_total": meta.unit_total if meta else 0,
        "unit_done": meta.unit_done if meta else 0,
        "model": meta.model if meta else None,
        "toc_changed": state.toc_changed,
        "book_summary": meta.book_summary if meta else None,
        "error": meta.error if meta else None,
        "units": [
            {
                "id": u.id,
                "seq": u.seq,
                "title": u.title,
                "start_page": u.start_page,
                "end_page": u.end_page,
                "status": u.status,
                "summary": u.summary,
                "error": u.error,
            }
            for u in state.units
        ],
    }


def _memory_unavailable(request_id: str, pdf_id: str, project_id: str) -> JSONResponse:
    _log_pdf_call(
        request_id=request_id, http_status=409, error_code="MEMORY_UNAVAILABLE",
        pdf_id=pdf_id, project_id=project_id,
    )
    return JSONResponse(
        status_code=409,
        content=error_response(
            code="MEMORY_UNAVAILABLE",
            message="全书文本不可用（扫描版或尚未提取），无法建立记忆。",
            request_id=request_id,
        ),
    )


@router.get("/{pdf_id}/memory")
async def get_memory(pdf_id: str):
    request_id = generate_request_id()
    entry = find_by_pdf_id(pdf_id)
    if entry is None:
        return _pdf_not_found(request_id, pdf_id)
    state = memory_read_state(entry.id, pdf_id)
    _log_pdf_call(request_id=request_id, http_status=200, pdf_id=pdf_id, project_id=entry.id)
    return ok_response(_memory_payload(pdf_id, state))


@router.get("/{pdf_id}/memory/estimate")
async def get_memory_estimate(pdf_id: str, scope: str | None = None):
    """scope=full：强制按全书估算（重建入口用；与 rebuild 的实际行为对齐）。"""
    request_id = generate_request_id()
    entry = find_by_pdf_id(pdf_id)
    if entry is None:
        return _pdf_not_found(request_id, pdf_id)
    if scope is not None and scope != "full":
        _log_pdf_call(
            request_id=request_id,
            http_status=400,
            error_code="INVALID_REQUEST",
            pdf_id=pdf_id,
            project_id=entry.id,
        )
        return JSONResponse(
            status_code=400,
            content=error_response(
                code="INVALID_REQUEST",
                message="Invalid scope parameter.",
                request_id=request_id,
            ),
        )
    try:
        data = memory_estimate(entry.id, pdf_id, scope=scope)
    except MemoryUnavailableError:
        return _memory_unavailable(request_id, pdf_id, entry.id)
    _log_pdf_call(request_id=request_id, http_status=200, pdf_id=pdf_id, project_id=entry.id)
    return ok_response(data)


@router.post("/{pdf_id}/memory/build")
async def build_memory(pdf_id: str, provider: Provider = Depends(get_provider)):
    """首建或续跑（partial 只补缺失单元）；running 中幂等返回进度（规格 F2）。"""
    request_id = generate_request_id()
    entry = find_by_pdf_id(pdf_id)
    if entry is None:
        return _pdf_not_found(request_id, pdf_id)
    try:
        state, started = memory_start_build(entry.id, pdf_id, provider)
    except MemoryUnavailableError:
        return _memory_unavailable(request_id, pdf_id, entry.id)
    except MemoryAlreadyReadyError:
        _log_pdf_call(
            request_id=request_id, http_status=409, error_code="MEMORY_ALREADY_READY",
            pdf_id=pdf_id, project_id=entry.id,
        )
        return JSONResponse(
            status_code=409,
            content=error_response(
                code="MEMORY_ALREADY_READY",
                message="记忆已完整，如需重跑请使用重建。",
                request_id=request_id,
            ),
        )
    status_code = 202 if started else 200
    _log_pdf_call(request_id=request_id, http_status=status_code, pdf_id=pdf_id, project_id=entry.id)
    return JSONResponse(status_code=status_code, content=ok_response(_memory_payload(pdf_id, state)))


@router.post("/{pdf_id}/memory/rebuild")
async def rebuild_memory(pdf_id: str, provider: Provider = Depends(get_provider)):
    """整体重建：清旧产物重新分段跑批；running 中幂等返回进度（规格 F2.8）。"""
    request_id = generate_request_id()
    entry = find_by_pdf_id(pdf_id)
    if entry is None:
        return _pdf_not_found(request_id, pdf_id)
    try:
        state, started = memory_start_rebuild(entry.id, pdf_id, provider)
    except MemoryUnavailableError:
        return _memory_unavailable(request_id, pdf_id, entry.id)
    status_code = 202 if started else 200
    _log_pdf_call(request_id=request_id, http_status=status_code, pdf_id=pdf_id, project_id=entry.id)
    return JSONResponse(status_code=status_code, content=ok_response(_memory_payload(pdf_id, state)))


@router.post("/{pdf_id}/memory/cancel")
async def cancel_memory(pdf_id: str):
    """协作式取消：当前单元调用完成后停止；非 running 幂等（规格 F2.5）。"""
    request_id = generate_request_id()
    entry = find_by_pdf_id(pdf_id)
    if entry is None:
        return _pdf_not_found(request_id, pdf_id)
    state = memory_request_cancel(entry.id, pdf_id)
    _log_pdf_call(request_id=request_id, http_status=200, pdf_id=pdf_id, project_id=entry.id)
    return ok_response(_memory_payload(pdf_id, state))

