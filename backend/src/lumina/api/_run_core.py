import base64
import binascii
import logging
import time

from fastapi import Request
from fastapi.responses import JSONResponse

from ulid import ULID

from lumina.api._thumbnail import render_thumbnail
from lumina.config import Settings
from lumina.db.models import SelectionRow
from lumina.logging import get_logger, log_with_fields
from lumina.projects.manager import PdfNotFoundError, lookup_project_by_pdf_id
from lumina.request_id import generate_request_id
from lumina.providers.base import (
    Provider,
    ProviderAuthError,
    ProviderConfigError,
    ProviderTimeout,
    ProviderUpstreamError,
    LLMMessage,
    TextPart,
)
from lumina.schemas.api import (
    TranslateData,
    TranslateMeta,
    TranslateRequest,
    TranslateUsage,
    error_response,
    ok_response,
)
from lumina.sessions import get_session_store
from lumina.tasks import get_task
from lumina.tasks.base import TaskContext, UnsupportedTaskError
from lumina.tasks.extract import EXTRACT_TASK

MAX_BODY_BYTES = 8 * 1024 * 1024
ALLOWED_IMAGE_MIME = "image/png"
API_VERSION = "v1"

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


def _compose_user_history_text(extracted_text: str, user_question: str | None) -> str:
    parts = [
        "Source content (extracted from the user's screenshot):\n\n",
        extracted_text,
    ]
    if user_question:
        parts.append(f"\n\nAdditional question from the user: {user_question}")
    return "".join(parts)


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
    session_id: str | None = None,
    turn_index: int | None = None,
    extract_latency_ms: int | None = None,
    extracted_text_chars: int | None = None,
    project_id: str | None = None,
    pdf_id: str | None = None,
    conversation_id: str | None = None,
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
        session_id=session_id or "",
        turn_index=turn_index if turn_index is not None else "",
        extract_latency_ms=extract_latency_ms if extract_latency_ms is not None else "",
        extracted_text_chars=extracted_text_chars if extracted_text_chars is not None else "",
        project_id=project_id or "",
        pdf_id=pdf_id or "",
        conversation_id=conversation_id or "",
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
    session_id: str | None = None,
    turn_index: int | None = None,
    extract_latency_ms: int | None = None,
    extracted_text_chars: int | None = None,
    project_id: str | None = None,
    pdf_id: str | None = None,
    conversation_id: str | None = None,
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
        session_id=session_id,
        turn_index=turn_index,
        extract_latency_ms=extract_latency_ms,
        extracted_text_chars=extracted_text_chars,
        project_id=project_id,
        pdf_id=pdf_id,
        conversation_id=conversation_id,
    )
    return JSONResponse(
        status_code=status_code,
        content=error_response(code=code, message=message, request_id=request_id),
    )


def _resolve_task(
    *,
    body: TranslateRequest,
    allowed_task_types: set[str] | None,
    request_id: str,
    api_version: str,
    page: int,
    image_bytes: int,
):
    task_type = body.task_type
    if allowed_task_types is not None and task_type not in allowed_task_types:
        return None, _error_json(
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
        return get_task(body.task_type), None
    except UnsupportedTaskError:
        return None, _error_json(
            status_code=400,
            code="UNSUPPORTED_TASK",
            message="Unsupported task type.",
            request_id=request_id,
            api_version=api_version,
            task_type=task_type,
            page=page,
            image_bytes=image_bytes,
        )


def _validate_image_payload(
    *,
    request: Request,
    body: TranslateRequest,
    request_id: str,
    api_version: str,
    task_type: str,
    page: int,
) -> tuple[int, JSONResponse | None]:
    if body.image is None:
        return 0, _error_json(
            status_code=400,
            code="INVALID_REQUEST",
            message="Request requires a valid image.",
            request_id=request_id,
            api_version=api_version,
            task_type=task_type,
            page=page,
            image_bytes=0,
        )

    content_length = request.headers.get("content-length")
    parsed_length = int(content_length) if content_length is not None else None
    if is_payload_too_large(parsed_length, body.image.data):
        return 0, _error_json(
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
        return 0, _error_json(
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
    except ValueError:
        return 0, _error_json(
            status_code=400,
            code="INVALID_REQUEST",
            message="Invalid base64 image data.",
            request_id=request_id,
            api_version=api_version,
            task_type=task_type,
            page=page,
            image_bytes=0,
        )

    return len(decoded), None


async def _invoke_task(
    *,
    task,
    ctx: TaskContext,
    provider: Provider,
    request_id: str,
    api_version: str,
    task_type: str,
    page: int,
    image_bytes: int,
    start: float,
    session_id: str | None = None,
    turn_index: int | None = None,
    extract_latency_ms: int | None = None,
    extracted_text_chars: int | None = None,
    project_id: str | None = None,
    pdf_id: str | None = None,
    conversation_id: str | None = None,
):
    try:
        llm_req = task.build_request(ctx)
        llm_resp = await provider.invoke(llm_req)
        return task.parse_response(llm_resp), llm_resp, None
    except ProviderTimeout:
        latency_ms = int((time.perf_counter() - start) * 1000)
        return None, None, _error_json(
            status_code=504,
            code="PROVIDER_TIMEOUT",
            message="Upstream LLM request timed out.",
            request_id=request_id,
            api_version=api_version,
            task_type=task_type,
            page=page,
            image_bytes=image_bytes,
            latency_ms=latency_ms,
            session_id=session_id,
            turn_index=turn_index,
            extract_latency_ms=extract_latency_ms,
            extracted_text_chars=extracted_text_chars,
        )
    except (ProviderAuthError, ProviderUpstreamError):
        latency_ms = int((time.perf_counter() - start) * 1000)
        return None, None, _error_json(
            status_code=502,
            code="PROVIDER_ERROR",
            message="Upstream LLM request failed.",
            request_id=request_id,
            api_version=api_version,
            task_type=task_type,
            page=page,
            image_bytes=image_bytes,
            latency_ms=latency_ms,
            session_id=session_id,
            turn_index=turn_index,
            extract_latency_ms=extract_latency_ms,
            extracted_text_chars=extracted_text_chars,
        )
    except ProviderConfigError:
        latency_ms = int((time.perf_counter() - start) * 1000)
        return None, None, _error_json(
            status_code=500,
            code="INTERNAL_ERROR",
            message="An internal server error occurred.",
            request_id=request_id,
            api_version=api_version,
            task_type=task_type,
            page=page,
            image_bytes=image_bytes,
            latency_ms=latency_ms,
            session_id=session_id,
            turn_index=turn_index,
            extract_latency_ms=extract_latency_ms,
            extracted_text_chars=extracted_text_chars,
        )


def _build_success_response(
    *,
    request_id: str,
    api_version: str,
    task_type: str,
    page: int,
    image_bytes: int,
    start: float,
    llm_resp,
    result,
    session_id: str | None = None,
    turn_index: int | None = None,
    extract_latency_ms: int | None = None,
    extracted_text_chars: int | None = None,
    project_id: str | None = None,
    pdf_id: str | None = None,
    conversation_id: str | None = None,
):
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
        "task_type": task_type,
    }
    if turn_index is not None:
        meta_kwargs["turn_index"] = turn_index

    data = TranslateData(
        text=result.text,
        session_id=session_id,
        conversation_id=session_id if session_id is not None else None,
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
        session_id=session_id,
        turn_index=turn_index,
        extract_latency_ms=extract_latency_ms,
        extracted_text_chars=extracted_text_chars,
        project_id=project_id,
        pdf_id=pdf_id,
        conversation_id=conversation_id,
    )
    return ok_response(data)


async def _execute_first_turn_v1(
    *,
    request: Request,
    body: TranslateRequest,
    provider: Provider,
    settings: Settings,
    request_id: str,
    start: float,
    allowed_task_types: set[str] | None,
) -> JSONResponse | dict[str, object]:
    task_type = body.task_type
    page = body.selection.page if body.selection is not None else 0

    if not body.pdf_id:
        return _error_json(
            status_code=400,
            code="INVALID_REQUEST",
            message="First turn requires pdf_id.",
            request_id=request_id,
            api_version="v1",
            task_type=task_type,
            page=page,
            image_bytes=0,
        )

    if body.selection is None or body.image is None:
        return _error_json(
            status_code=400,
            code="INVALID_REQUEST",
            message="First turn requires selection and image.",
            request_id=request_id,
            api_version="v1",
            task_type=task_type,
            page=page,
            image_bytes=0,
            pdf_id=body.pdf_id,
        )

    try:
        catalog_entry = lookup_project_by_pdf_id(body.pdf_id)
    except PdfNotFoundError:
        return _error_json(
            status_code=404,
            code="PDF_NOT_FOUND",
            message="PDF not found.",
            request_id=request_id,
            api_version="v1",
            task_type=task_type,
            page=page,
            image_bytes=0,
            pdf_id=body.pdf_id,
        )

    project_id = catalog_entry.id
    pdf_id = body.pdf_id

    image_bytes, image_error = _validate_image_payload(
        request=request,
        body=body,
        request_id=request_id,
        api_version="v1",
        task_type=task_type,
        page=page,
    )
    if image_error is not None:
        return image_error

    task, task_error = _resolve_task(
        body=body,
        allowed_task_types=allowed_task_types,
        request_id=request_id,
        api_version="v1",
        page=page,
        image_bytes=image_bytes,
    )
    if task_error is not None:
        return task_error

    extract_ctx = TaskContext(
        selection=body.selection,
        image=body.image,
        options={"temperature": settings.llm_temperature},
        project_id=project_id,
        pdf_id=pdf_id,
    )
    extract_start = time.perf_counter()
    extract_result, extract_resp, extract_error = await _invoke_task(
        task=EXTRACT_TASK,
        ctx=extract_ctx,
        provider=provider,
        request_id=request_id,
        api_version="v1",
        task_type=task_type,
        page=page,
        image_bytes=image_bytes,
        start=start,
        project_id=project_id,
        pdf_id=pdf_id,
    )
    extract_latency_ms = int((time.perf_counter() - extract_start) * 1000)
    if extract_error is not None:
        return extract_error

    extracted_text = extract_result.text
    extracted_text_chars = len(extracted_text)

    drive_ctx = TaskContext(
        selection=None,
        image=None,
        extracted_text=extracted_text,
        user_question=body.options.user_question,
        history=[],
        options={
            "target_lang": body.options.target_lang,
            "temperature": settings.llm_temperature,
        },
        project_id=project_id,
        pdf_id=pdf_id,
    )

    result, llm_resp, invoke_error = await _invoke_task(
        task=task,
        ctx=drive_ctx,
        provider=provider,
        request_id=request_id,
        api_version="v1",
        task_type=task_type,
        page=page,
        image_bytes=image_bytes,
        start=start,
        turn_index=0,
        extract_latency_ms=extract_latency_ms,
        extracted_text_chars=extracted_text_chars,
        project_id=project_id,
        pdf_id=pdf_id,
    )
    if invoke_error is not None:
        return invoke_error

    conversation_id = f"conv_{ULID()}"
    selection_id = f"sel_{ULID()}"
    user_history_text = _compose_user_history_text(
        extracted_text, body.options.user_question
    )

    store = get_session_store()
    meta = {
        "page": body.selection.page,
        "x": body.selection.x,
        "y": body.selection.y,
        "w": body.selection.w,
        "h": body.selection.h,
        "dpi": body.selection.dpi,
        "image_bytes": image_bytes,
    }
    thumbnail_png = None
    try:
        thumbnail_png = render_thumbnail(body.image.data)
    except Exception:
        thumbnail_png = None
    selection_row = SelectionRow(
        id=selection_id,
        pdf_id=pdf_id,
        page=body.selection.page,
        x=body.selection.x,
        y=body.selection.y,
        w=body.selection.w,
        h=body.selection.h,
        dpi=body.selection.dpi,
        thumbnail_png=thumbnail_png,
        created_at=int(time.time()),
    )
    assistant_meta = {
        "model": llm_resp.model,
        "prompt_tokens": llm_resp.usage.prompt_tokens if llm_resp.usage else None,
        "completion_tokens": llm_resp.usage.completion_tokens if llm_resp.usage else None,
        "latency_ms": int((time.perf_counter() - start) * 1000),
    }

    try:
        session = await store.create(
            conversation_id=conversation_id,
            project_id=project_id,
            pdf_id=pdf_id,
            selection_id=selection_id,
            task_type=task_type,
            extracted_text=extracted_text,
            selection_row=selection_row,
            first_user_question=body.options.user_question,
            first_user_content=user_history_text,
            first_assistant_text=result.text,
            first_assistant_meta=assistant_meta,
            meta=meta,
        )
    except Exception:
        return _error_json(
            status_code=500,
            code="INTERNAL_ERROR",
            message="An internal server error occurred.",
            request_id=request_id,
            api_version="v1",
            task_type=task_type,
            page=page,
            image_bytes=image_bytes,
            project_id=project_id,
            pdf_id=pdf_id,
        )

    if settings.session_log_extracted_text:
        log_with_fields(
            logger,
            logging.DEBUG,
            "extracted text captured",
            request_id=request_id,
            session_id=session.session_id,
            extracted_text=extracted_text,
        )

    return _build_success_response(
        request_id=request_id,
        api_version="v1",
        task_type=task_type,
        page=page,
        image_bytes=image_bytes,
        start=start,
        llm_resp=llm_resp,
        result=result,
        session_id=session.session_id,
        turn_index=0,
        extract_latency_ms=extract_latency_ms,
        extracted_text_chars=extracted_text_chars,
        project_id=project_id,
        pdf_id=pdf_id,
        conversation_id=conversation_id,
    )


async def _execute_follow_up_v1(
    *,
    body: TranslateRequest,
    provider: Provider,
    settings: Settings,
    request_id: str,
    start: float,
    allowed_task_types: set[str] | None,
) -> JSONResponse | dict[str, object]:
    task_type = body.task_type
    page = body.selection.page if body.selection is not None else 0

    if body.image is not None:
        return _error_json(
            status_code=400,
            code="INVALID_REQUEST",
            message="Follow-up turn must not include image.",
            request_id=request_id,
            api_version="v1",
            task_type=task_type,
            page=page,
            image_bytes=0,
            session_id=body.session_id,
        )

    user_question = body.options.user_question
    if not user_question:
        return _error_json(
            status_code=400,
            code="INVALID_REQUEST",
            message="Follow-up turn requires options.user_question.",
            request_id=request_id,
            api_version="v1",
            task_type=task_type,
            page=page,
            image_bytes=0,
            session_id=body.session_id,
        )

    task, task_error = _resolve_task(
        body=body,
        allowed_task_types=allowed_task_types,
        request_id=request_id,
        api_version="v1",
        page=page,
        image_bytes=0,
    )
    if task_error is not None:
        return task_error

    store = get_session_store()
    session = await store.get(body.session_id)
    if session is None:
        return _error_json(
            status_code=400,
            code="SESSION_NOT_FOUND",
            message="Session not found.",
            request_id=request_id,
            api_version="v1",
            task_type=task_type,
            page=page,
            image_bytes=0,
            session_id=body.session_id,
        )

    if session.task_type != body.task_type:
        return _error_json(
            status_code=400,
            code="SESSION_TASK_MISMATCH",
            message="Task type does not match session.",
            request_id=request_id,
            api_version="v1",
            task_type=task_type,
            page=page,
            image_bytes=0,
            session_id=body.session_id,
        )

    turn_index = len(session.messages) // 2

    drive_ctx = TaskContext(
        selection=None,
        image=None,
        extracted_text=session.extracted_text,
        user_question=user_question,
        history=list(session.messages),
        options={
            "target_lang": body.options.target_lang,
            "temperature": settings.llm_temperature,
        },
        project_id=session.project_id,
        pdf_id=session.pdf_id,
    )

    result, llm_resp, invoke_error = await _invoke_task(
        task=task,
        ctx=drive_ctx,
        provider=provider,
        request_id=request_id,
        api_version="v1",
        task_type=task_type,
        page=page,
        image_bytes=0,
        start=start,
        session_id=body.session_id,
        turn_index=turn_index,
        project_id=session.project_id,
        pdf_id=session.pdf_id,
        conversation_id=body.session_id,
    )
    if invoke_error is not None:
        return invoke_error

    user_msg_for_history = LLMMessage(
        role="user",
        content=[TextPart(text=user_question)],
    )
    assistant_msg_for_history = LLMMessage(
        role="assistant",
        content=[TextPart(text=result.text)],
    )
    await store.append_turn(
        body.session_id,
        user_message=user_msg_for_history,
        assistant_message=assistant_msg_for_history,
        turn_index=turn_index,
        assistant_meta={
            "model": llm_resp.model,
            "prompt_tokens": llm_resp.usage.prompt_tokens if llm_resp.usage else None,
            "completion_tokens": llm_resp.usage.completion_tokens if llm_resp.usage else None,
            "latency_ms": int((time.perf_counter() - start) * 1000),
        },
    )

    return _build_success_response(
        request_id=request_id,
        api_version="v1",
        task_type=task_type,
        page=page,
        image_bytes=0,
        start=start,
        llm_resp=llm_resp,
        result=result,
        session_id=body.session_id,
        turn_index=turn_index,
        project_id=session.project_id,
        pdf_id=session.pdf_id,
        conversation_id=body.session_id,
    )


async def execute_run(
    *,
    request: Request,
    body: TranslateRequest,
    provider: Provider,
    settings: Settings,
    allowed_task_types: set[str] | None = None,
) -> JSONResponse | dict[str, object]:
    request_id = generate_request_id()
    start = time.perf_counter()

    if body.session_id is None:
        return await _execute_first_turn_v1(
            request=request,
            body=body,
            provider=provider,
            settings=settings,
            request_id=request_id,
            start=start,
            allowed_task_types=allowed_task_types,
        )

    return await _execute_follow_up_v1(
        body=body,
        provider=provider,
        settings=settings,
        request_id=request_id,
        start=start,
        allowed_task_types=allowed_task_types,
    )
