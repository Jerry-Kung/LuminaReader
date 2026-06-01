import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from lumina.logging import get_logger, log_with_fields
from lumina.request_id import generate_request_id

router = APIRouter(prefix="/translate", tags=["v0-gone"])
logger = get_logger("lumina.v0")


@router.post("")
async def v0_translate_gone(request: Request) -> JSONResponse:
    request_id = generate_request_id()
    log_with_fields(
        logger,
        logging.WARNING,
        "v0 endpoint gone",
        request_id=request_id,
        api_version="gone",
        http_status=410,
        error_code="GONE",
        path=str(request.url.path),
    )
    return JSONResponse(
        status_code=410,
        content={
            "ok": False,
            "error": {
                "code": "GONE",
                "message": "Endpoint removed in V1.0.3. Use POST /api/v1/run instead.",
                "request_id": request_id,
            },
        },
    )
