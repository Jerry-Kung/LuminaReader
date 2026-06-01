import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from lumina.db.engine import get_connection
from lumina.db.models import list_conversations_brief, list_pdfs
from lumina.logging import get_logger, log_with_fields
from lumina.projects.catalog import find_by_project_id, list_entries
from lumina.projects.paths import project_dir
from lumina.request_id import generate_request_id
from lumina.schemas.api import error_response, ok_response

router = APIRouter(prefix="/projects", tags=["projects-debug"])
logger = get_logger("lumina.projects_debug")


@router.get("")
async def list_projects_debug():
    request_id = generate_request_id()
    entries = list_entries(sort="created_at_desc")
    items = [
        {
            "project_id": e.id,
            "name": e.name,
            "pdf_id": e.primary_pdf_id,
            "created_at": e.created_at,
            "last_opened_at": e.last_opened_at,
        }
        for e in entries
    ]
    log_with_fields(
        logger,
        logging.INFO,
        "projects debug list",
        request_id=request_id,
        api_version="v1",
        http_status=200,
    )
    return ok_response({"items": items})


@router.get("/{project_id}")
async def get_project_debug(project_id: str):
    request_id = generate_request_id()
    entry = find_by_project_id(project_id)
    if entry is None:
        log_with_fields(
            logger,
            logging.WARNING,
            "project debug not found",
            request_id=request_id,
            api_version="v1",
            http_status=404,
            error_code="PROJECT_NOT_FOUND",
            project_id=project_id,
        )
        return JSONResponse(
            status_code=404,
            content=error_response(
                code="PROJECT_NOT_FOUND",
                message="Project not found.",
                request_id=request_id,
            ),
        )

    conn = get_connection(project_id)
    pdfs = list_pdfs(conn, project_id)
    convs = list_conversations_brief(conn)
    data = {
        "project_id": entry.id,
        "name": entry.name,
        "path": str(project_dir(entry.id)),
        "created_at": entry.created_at,
        "last_opened_at": entry.last_opened_at,
        "pdfs": [
            {
                "pdf_id": p.id,
                "filename": p.filename,
                "file_size": p.file_size,
                "added_at": p.added_at,
            }
            for p in pdfs
        ],
        "conversations": [
            {
                "conversation_id": c.id,
                "pdf_id": c.pdf_id,
                "task_type": c.task_type,
                "status": c.status,
                "created_at": c.created_at,
                "last_used_at": c.last_used_at,
            }
            for c in convs
        ],
    }
    log_with_fields(
        logger,
        logging.INFO,
        "project debug detail",
        request_id=request_id,
        api_version="v1",
        http_status=200,
        project_id=project_id,
    )
    return ok_response(data)
