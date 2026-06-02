import logging

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from lumina.config import get_settings
from lumina.db.engine import get_connection
from lumina.db.models import update_pdf_last_read_page
from lumina.logging import get_logger, log_with_fields
from lumina.projects.catalog import find_by_pdf_id
from lumina.projects.manager import (
    ProjectNameConflictError,
    auto_create_project,
    delete_project,
    touch_last_opened_at,
)
from lumina.projects.paths import project_pdf_path
from lumina.request_id import generate_request_id
from lumina.schemas.api import PdfUploadData, ReadingPositionUpdate, error_response, ok_response
from lumina.sessions import get_session_store

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
    if payload.last_read_page < 1:
        _log_pdf_call(
            request_id=request_id,
            http_status=400,
            error_code="INVALID_REQUEST",
            pdf_id=pdf_id,
        )
        return JSONResponse(
            status_code=400,
            content=error_response(
                code="INVALID_REQUEST",
                message="last_read_page must be >= 1",
                request_id=request_id,
            ),
        )

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
    updated = update_pdf_last_read_page(conn, pdf_id, payload.last_read_page)
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
