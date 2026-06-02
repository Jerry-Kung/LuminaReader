import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from lumina.db.engine import get_connection
from lumina.db.models import get_pdf_last_read_page
from lumina.logging import get_logger, log_with_fields
from lumina.projects.catalog import list_entries
from lumina.request_id import generate_request_id
from lumina.schemas.api import LibraryItem, LibraryListData, error_response, ok_response

router = APIRouter(prefix="/library", tags=["library"])
logger = get_logger("lumina.library")

VALID_SORTS = frozenset({"last_opened_at_desc", "created_at_desc", "name_asc"})


@router.get("")
async def get_library(sort: str = "last_opened_at_desc"):
    request_id = generate_request_id()
    if sort not in VALID_SORTS:
        log_with_fields(
            logger,
            logging.WARNING,
            "library request invalid sort",
            request_id=request_id,
            api_version="v1",
            http_status=400,
            error_code="INVALID_REQUEST",
        )
        return JSONResponse(
            status_code=400,
            content=error_response(
                code="INVALID_REQUEST",
                message="Invalid sort parameter.",
                request_id=request_id,
            ),
        )

    entries = list_entries(sort=sort)
    items = []
    for e in entries:
        try:
            conn = get_connection(e.id)
            stored = get_pdf_last_read_page(conn, e.primary_pdf_id)
        except Exception:
            stored = None
        last_read_page = stored if isinstance(stored, int) and stored >= 1 else 1
        items.append(
            LibraryItem(
                pdf_id=e.primary_pdf_id,
                name=e.name,
                primary_pdf_filename=e.primary_pdf_filename,
                primary_pdf_size=e.primary_pdf_size,
                created_at=e.created_at,
                last_opened_at=e.last_opened_at,
                last_read_page=last_read_page,
                thumbnail_url=None,
            )
        )
    log_with_fields(
        logger,
        logging.INFO,
        "library request completed",
        request_id=request_id,
        api_version="v1",
        http_status=200,
    )
    return ok_response(LibraryListData(items=items))
