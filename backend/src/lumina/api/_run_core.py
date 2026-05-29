import base64
import binascii
import logging
import time

from fastapi import Request
from fastapi.responses import JSONResponse

from lumina.config import Settings
from lumina.logging import get_logger, log_with_fields
from lumina.request_id import generate_request_id
from lumina.providers.base import (
    Provider,
    ProviderAuthError,
    ProviderConfigError,
    ProviderTimeout,
    ProviderUpstreamError,
)
from lumina.schemas.api import (
    TranslateData,
    TranslateMeta,
    TranslateRequest,
    TranslateUsage,
    error_response,
    ok_response,
)
from lumina.tasks import get_task
from lumina.tasks.base import TaskContext, UnsupportedTaskError

MAX_BODY_BYTES = 8 * 1024 * 1024
ALLOWED_IMAGE_MIME = "image/png"

logger = get_logger("lumina.run")


def is_payload_too_large(content_length: int | None, image_data_b64: str) -> bool:
    if content_length is not None and content_length > MAX_BODY_BYTES:
        return True
    estimated_body_bytes = len(image_data_b64) + 4096
    return estimated_body_bytes > MAX_BODY_BYTES


def decode_image_data(image_data_b64: str) -> bytes:
    try:
        return base64.b64decode(image_data_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Invalid base64 image data.") from exc


def _log_run_call(
    *,
    request_id: str,
    api_version: str,
    task_type: str,
    page: int,
    image_bytes: int,
    model: str | None,
    latency_ms: int | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    http_status: int,
    error_code: str | None = None,
) -> None:
    log_with_fields(
        logger,
        logging.INFO if error_code is None else logging.WARNING,
        "run call completed",
        request_id=request_id,
        api_version=api_version,
        task_type=task_type,
        page=page,
        image_bytes=image_bytes,
        model=model or "",
        latency_ms=latency_ms if latency_ms is not None else "",
        prompt_tokens=prompt_tokens if prompt_tokens is not None else "",
        completion_tokens=completion_tokens if completion_tokens is not None else "",
        http_status=http_status,
        error_code=error_code or "",
    )


def _error_json(
    *,
    status_code: int,
    code: str,
    message: str,
    request_id: str,
    api_version: str,
    task_type: str,
    page: int,
    image_bytes: int,
    latency_ms: int | None = None,
) -> JSONResponse:
    _log_run_call(
        request_id=request_id,
        api_version=api_version,
        task_type=task_type,
        page=page,
        image_bytes=image_bytes,
        model=None,
        latency_ms=latency_ms,
        prompt_tokens=None,
        completion_tokens=None,
        http_status=status_code,
        error_code=code,
    )
    return JSONResponse(
        status_code=status_code,
        content=error_response(code=code, message=message, request_id=request_id),
    )


async def execute_run(
    *,
    request: Request,
    body: TranslateRequest,
    provider: Provider,
    settings: Settings,
    api_version: str,
    allowed_task_types: set[str] | None = None,
) -> JSONResponse | dict[str, object]:
    request_id = generate_request_id()
    task_type = body.task_type
    page = body.selection.page
    image_bytes = 0
    start = time.perf_counter()

    content_length = request.headers.get("content-length")
    parsed_length = int(content_length) if content_length is not None else None
    if is_payload_too_large(parsed_length, body.image.data):
        return _error_json(
            status_code=413,
            code="PAYLOAD_TOO_LARGE",
            message="Request body exceeds the 8MB limit.",
            request_id=request_id,
            api_version=api_version,
            task_type=task_type,
            page=page,
            image_bytes=0,
        )

    if body.image.mime != ALLOWED_IMAGE_MIME:
        return _error_json(
            status_code=400,
            code="INVALID_REQUEST",
            message="Unsupported image MIME type.",
            request_id=request_id,
            api_version=api_version,
            task_type=task_type,
            page=page,
            image_bytes=0,
        )

    try:
        decoded = decode_image_data(body.image.data)
        image_bytes = len(decoded)
    except ValueError:
        return _error_json(
            status_code=400,
            code="INVALID_REQUEST",
            message="Invalid base64 image data.",
            request_id=request_id,
            api_version=api_version,
            task_type=task_type,
            page=page,
            image_bytes=0,
        )

    if allowed_task_types is not None and task_type not in allowed_task_types:
        return _error_json(
            status_code=400,
            code="UNSUPPORTED_TASK",
            message="Unsupported task type.",
            request_id=request_id,
            api_version=api_version,
            task_type=task_type,
            page=page,
            image_bytes=image_bytes,
        )

    try:
        task = get_task(body.task_type)
    except UnsupportedTaskError:
        return _error_json(
            status_code=400,
            code="UNSUPPORTED_TASK",
            message="Unsupported task type.",
            request_id=request_id,
            api_version=api_version,
            task_type=task_type,
            page=page,
            image_bytes=image_bytes,
        )

    ctx = TaskContext(
        selection=body.selection,
        image=body.image,
        options={
            **body.options.model_dump(),
            "temperature": settings.llm_temperature,
        },
    )

    try:
        llm_req = task.build_request(ctx)
        llm_resp = await provider.invoke(llm_req)
        result = task.parse_response(llm_resp)
    except ProviderTimeout:
        latency_ms = int((time.perf_counter() - start) * 1000)
        return _error_json(
            status_code=504,
            code="PROVIDER_TIMEOUT",
            message="Upstream LLM request timed out.",
            request_id=request_id,
            api_version=api_version,
            task_type=task_type,
            page=page,
            image_bytes=image_bytes,
            latency_ms=latency_ms,
        )
    except (ProviderAuthError, ProviderUpstreamError):
        latency_ms = int((time.perf_counter() - start) * 1000)
        return _error_json(
            status_code=502,
            code="PROVIDER_ERROR",
            message="Upstream LLM request failed.",
            request_id=request_id,
            api_version=api_version,
            task_type=task_type,
            page=page,
            image_bytes=image_bytes,
            latency_ms=latency_ms,
        )
    except ProviderConfigError:
        latency_ms = int((time.perf_counter() - start) * 1000)
        return _error_json(
            status_code=500,
            code="INTERNAL_ERROR",
            message="An internal server error occurred.",
            request_id=request_id,
            api_version=api_version,
            task_type=task_type,
            page=page,
            image_bytes=image_bytes,
            latency_ms=latency_ms,
        )

    latency_ms = int((time.perf_counter() - start) * 1000)
    usage = None
    if llm_resp.usage is not None:
        usage = TranslateUsage(
            prompt_tokens=llm_resp.usage.prompt_tokens,
            completion_tokens=llm_resp.usage.completion_tokens,
            total_tokens=llm_resp.usage.total_tokens,
        )

    meta_kwargs: dict[str, object] = {
        "request_id": request_id,
        "model": llm_resp.model,
        "latency_ms": latency_ms,
        "usage": usage,
    }
    if api_version == "v1":
        meta_kwargs["task_type"] = task_type

    data = TranslateData(
        text=result.text,
        meta=TranslateMeta(**meta_kwargs),
    )

    prompt_tokens = llm_resp.usage.prompt_tokens if llm_resp.usage else None
    completion_tokens = llm_resp.usage.completion_tokens if llm_resp.usage else None
    _log_run_call(
        request_id=request_id,
        api_version=api_version,
        task_type=task_type,
        page=page,
        image_bytes=image_bytes,
        model=llm_resp.model,
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        http_status=200,
    )

    return ok_response(data)
