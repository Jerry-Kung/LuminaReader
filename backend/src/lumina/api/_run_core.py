import asyncio
import base64
import binascii
import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from fastapi import Request
from fastapi.responses import JSONResponse

from ulid import ULID

from lumina.api._thumbnail import render_thumbnail
from lumina.config import Settings
from lumina.db.models import SelectionRow
from lumina.logging import get_logger, log_with_fields
from lumina.projects.manager import PdfNotFoundError, lookup_project_by_pdf_id
from lumina.request_id import generate_request_id
from lumina import settings_store
from lumina.providers.base import (
    LLMMessage,
    LLMRequest,
    LLMStreamEvent,
    LLMUsage,
    Provider,
    ProviderAuthError,
    ProviderConfigError,
    ProviderTimeout,
    ProviderUpstreamError,
    TextPart,
)
from lumina.providers.errors import StreamUnsupportedError
from lumina.plugins import PluginPipeline
from lumina.plugins.base import PluginContext, estimate_word_count
from lumina.plugins.registry import PluginRegistry
from lumina.providers.openai_compat import _is_qwen_base_url
from lumina.schemas.api import (
    TranslateData,
    TranslateMeta,
    TranslateRequest,
    TranslateUsage,
    error_response,
    ok_response,
)
from lumina.sessions import get_session_store
from lumina.tasks.base import TaskContext, TaskResult, UnsupportedTaskError
from lumina.tasks.extract import EXTRACT_TASK

MAX_BODY_BYTES = 8 * 1024 * 1024
ALLOWED_IMAGE_MIME = "image/png"
API_VERSION = "v1"

logger = get_logger("lumina.run")


class RunInvalidRequestError(Exception):
    def __init__(
        self,
        message: str,
        field_errors: list[dict[str, str]] | None = None,
    ) -> None:
        self.message = message
        self.field_errors = field_errors or []
        super().__init__(message)


STREAM_HEARTBEAT_SECONDS = 15.0
_SSE_KEEP_ALIVE = b":keep-alive\n\n"


def _encode_sse(event: str, data: dict) -> bytes:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


def _usage_to_dict(usage: LLMUsage | None) -> dict:
    if usage is None:
        return {}
    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
    }


def _thinking_enabled_for_meta(
    pipeline: PluginPipeline,
    plugin_ids: list[str],
) -> bool:
    if not pipeline.decide_thinking(plugin_ids):
        return False
    try:
        current = settings_store.get_current()
        return _is_qwen_base_url(current.base_url)
    except RuntimeError:
        return False


def _plugins_log_value(plugin_ids: list[str]) -> str:
    return ",".join(plugin_ids) if plugin_ids else "chat"


def _conversation_task_type(plugin_ids: list[str]) -> str:
    return plugin_ids[0] if plugin_ids else "chat"


def _model_override_task(plugin_ids: list[str]) -> str | None:
    if not plugin_ids:
        return None
    return plugin_ids[0]


def _make_pipeline(
    registry: PluginRegistry,
    provider: Provider,
) -> PluginPipeline:
    return PluginPipeline(
        registry=registry,
        provider=provider,
        settings_thinking_enabled=_thinking_enabled_from_settings(),
    )


def resolve_plugin_routing(
    body: TranslateRequest,
    registry: PluginRegistry,
    ctx: PluginContext,
) -> tuple[list[str], str | None]:
    if body.plugins:
        plugin_ids = list(body.plugins)
        field_errors: list[dict[str, str]] = []
        for i, pid in enumerate(plugin_ids):
            if pid not in registry.plugins:
                field_errors.append(
                    {
                        "path": f"plugins[{i}]",
                        "reason": f"unknown plugin id: {pid}",
                    }
                )
        if field_errors:
            raise RunInvalidRequestError(
                "plugins contain unknown ids",
                field_errors=field_errors,
            )
    elif body.task_type == "translate":
        plugin_ids = ["translate"]
    elif body.task_type == "explain":
        plugin_ids = ["explain"]
    elif body.task_type == "chat":
        plugin_ids = []
    else:
        raise UnsupportedTaskError(body.task_type)

    user_input = body.user_input if body.user_input else body.options.user_question

    if not plugin_ids and not user_input:
        raise RunInvalidRequestError("either plugins or user_input is required")

    field_errors = []
    for i, pid in enumerate(plugin_ids):
        plugin = registry.get(pid)
        if not plugin.is_applicable(ctx):
            field_errors.append(
                {
                    "path": f"plugins[{i}]",
                    "reason": (
                        f"plugin {pid} is not applicable to the current selection"
                    ),
                }
            )
    if field_errors:
        raise RunInvalidRequestError(
            "plugin not applicable",
            field_errors=field_errors,
        )

    return plugin_ids, user_input


@dataclass
class PreparedStreamRun:
    request_id: str
    start: float
    task_type: str
    page: int
    image_bytes: int
    project_id: str | None
    pdf_id: str | None
    conversation_id: str
    turn_index: int
    is_first_turn: bool
    extract_latency_ms: int | None
    extracted_text_chars: int | None
    plugin_ids: list[str]
    plugin_ctx: PluginContext
    pipeline: PluginPipeline
    follow_up_user_input: str | None
    meta_payload: dict
    meta_ready: asyncio.Event = field(default_factory=asyncio.Event)


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
    thinking_enabled: bool | None = None,
    plugins: str | None = None,
) -> None:
    log_with_fields(
        logger,
        logging.INFO if error_code is None else logging.WARNING,
        "run call completed",
        request_id=request_id,
        api_version=api_version,
        task_type=task_type,
        plugins=plugins if plugins is not None else "",
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
        thinking_enabled=(
            thinking_enabled if thinking_enabled is not None else False
        ),
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
    field_errors: list[dict[str, str]] | None = None,
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
    error_kwargs: dict[str, object] = {}
    if field_errors:
        error_kwargs["field_errors"] = field_errors
    return JSONResponse(
        status_code=status_code,
        content=error_response(
            code=code,
            message=message,
            request_id=request_id,
            **error_kwargs,
        ),
    )


def _routing_error_response(
    *,
    exc: Exception,
    request_id: str,
    api_version: str,
    task_type: str,
    page: int,
    image_bytes: int,
    **log_kwargs: object,
) -> JSONResponse:
    if isinstance(exc, UnsupportedTaskError):
        return _error_json(
            status_code=400,
            code="UNSUPPORTED_TASK",
            message="Unsupported task type.",
            request_id=request_id,
            api_version=api_version,
            task_type=task_type,
            page=page,
            image_bytes=image_bytes,
            **log_kwargs,
        )
    if isinstance(exc, RunInvalidRequestError):
        return _error_json(
            status_code=400,
            code="INVALID_REQUEST",
            message=exc.message,
            request_id=request_id,
            api_version=api_version,
            task_type=task_type,
            page=page,
            image_bytes=image_bytes,
            field_errors=exc.field_errors,
            **log_kwargs,
        )
    raise exc


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


def _inject_thinking(req: LLMRequest, *, enabled: bool) -> LLMRequest:
    return req.model_copy(update={"thinking": enabled})


def _thinking_enabled_from_settings() -> bool:
    try:
        return settings_store.get_current().thinking.enabled
    except RuntimeError:
        return False


def _inject_model_override(req: LLMRequest, override_task_type: str) -> LLMRequest:
    try:
        override = settings_store.get_current().task_models.get(override_task_type)  # type: ignore[arg-type]
    except RuntimeError:
        return req
    if override:
        new_extras = {**(req.extras or {}), "model_override": override}
        return req.model_copy(update={"extras": new_extras})
    return req


async def _invoke_extract_task(
    *,
    ctx: TaskContext,
    provider: Provider,
    request_id: str,
    api_version: str,
    task_type: str,
    page: int,
    image_bytes: int,
    start: float,
    project_id: str | None = None,
    pdf_id: str | None = None,
):
    return await _invoke_task_legacy(
        task=EXTRACT_TASK,
        ctx=ctx,
        provider=provider,
        request_id=request_id,
        api_version=api_version,
        task_type=task_type,
        page=page,
        image_bytes=image_bytes,
        start=start,
        model_override_task="extract",
        apply_thinking=False,
        project_id=project_id,
        pdf_id=pdf_id,
    )


async def _invoke_task_legacy(
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
    model_override_task: str | None = None,
    session_id: str | None = None,
    turn_index: int | None = None,
    extract_latency_ms: int | None = None,
    extracted_text_chars: int | None = None,
    project_id: str | None = None,
    pdf_id: str | None = None,
    conversation_id: str | None = None,
    apply_thinking: bool = True,
):
    try:
        llm_req = task.build_request(ctx)
        if model_override_task is not None:
            llm_req = _inject_model_override(llm_req, model_override_task)
        if apply_thinking:
            llm_req = _inject_thinking(llm_req, enabled=_thinking_enabled_from_settings())
        else:
            llm_req = _inject_thinking(llm_req, enabled=False)
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


async def _invoke_pipeline(
    *,
    pipeline: PluginPipeline,
    plugin_ids: list[str],
    plugin_ctx: PluginContext,
    provider: Provider,
    request_id: str,
    api_version: str,
    task_type: str,
    page: int,
    image_bytes: int,
    start: float,
    model_override_task: str | None = None,
    session_id: str | None = None,
    turn_index: int | None = None,
    extract_latency_ms: int | None = None,
    extracted_text_chars: int | None = None,
    project_id: str | None = None,
    pdf_id: str | None = None,
    conversation_id: str | None = None,
):
    try:
        llm_req = pipeline.build_request(plugin_ids, plugin_ctx)
        if model_override_task is not None:
            llm_req = _inject_model_override(llm_req, model_override_task)
        llm_resp = await provider.invoke(llm_req)
        return TaskResult(text=llm_resp.text), llm_resp, None
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
    plugins: list[str] | None = None,
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
        "plugins": plugins or [],
    }
    if turn_index is not None:
        meta_kwargs["turn_index"] = turn_index
    meta_kwargs["thinking_enabled"] = llm_resp.thinking_enabled

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
        thinking_enabled=llm_resp.thinking_enabled,
        plugins=_plugins_log_value(plugins or []),
    )
    return ok_response(data)


async def _execute_first_turn_v1(
    *,
    request: Request,
    body: TranslateRequest,
    provider: Provider,
    settings: Settings,
    registry: PluginRegistry,
    request_id: str,
    start: float,
    allowed_task_types: set[str] | None,
) -> JSONResponse | dict[str, object]:
    task_type = body.task_type
    page = body.selection.page if body.selection is not None else 0
    pipeline = _make_pipeline(registry, provider)

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

    extract_ctx = TaskContext(
        selection=body.selection,
        image=body.image,
        options={"temperature": settings.llm_temperature},
        project_id=project_id,
        pdf_id=pdf_id,
    )
    extract_start = time.perf_counter()
    extract_result, extract_resp, extract_error = await _invoke_extract_task(
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

    plugin_ctx = PluginContext(
        selection_text=extracted_text,
        selection_type="image",
        selection_word_count=estimate_word_count(extracted_text),
        target_lang=body.options.target_lang,
        history=[],
    )
    try:
        plugin_ids, user_input = resolve_plugin_routing(body, registry, plugin_ctx)
    except (UnsupportedTaskError, RunInvalidRequestError) as exc:
        return _routing_error_response(
            exc=exc,
            request_id=request_id,
            api_version="v1",
            task_type=task_type,
            page=page,
            image_bytes=image_bytes,
            project_id=project_id,
            pdf_id=pdf_id,
        )

    plugin_ctx = plugin_ctx.model_copy(update={"user_input": user_input})
    conversation_task_type = _conversation_task_type(plugin_ids)

    result, llm_resp, invoke_error = await _invoke_pipeline(
        pipeline=pipeline,
        plugin_ids=plugin_ids,
        plugin_ctx=plugin_ctx,
        provider=provider,
        request_id=request_id,
        api_version="v1",
        task_type=conversation_task_type,
        page=page,
        image_bytes=image_bytes,
        start=start,
        model_override_task=_model_override_task(plugin_ids),
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
    user_history_text = _compose_user_history_text(extracted_text, user_input)

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
            task_type=conversation_task_type,
            extracted_text=extracted_text,
            selection_row=selection_row,
            first_user_question=user_input,
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
            task_type=conversation_task_type,
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
        task_type=conversation_task_type,
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
        plugins=plugin_ids,
    )


async def _execute_follow_up_v1(
    *,
    body: TranslateRequest,
    provider: Provider,
    settings: Settings,
    registry: PluginRegistry,
    request_id: str,
    start: float,
    allowed_task_types: set[str] | None,
) -> JSONResponse | dict[str, object]:
    task_type = body.task_type
    page = body.selection.page if body.selection is not None else 0
    pipeline = _make_pipeline(registry, provider)

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

    # V1.1.1: cross-plugin follow-up allowed; SESSION_TASK_MISMATCH check removed.

    turn_index = len(session.messages) // 2

    plugin_ctx = PluginContext(
        selection_text=session.extracted_text,
        selection_type="image",
        selection_word_count=estimate_word_count(session.extracted_text),
        target_lang=body.options.target_lang,
        history=list(session.messages),
    )
    try:
        plugin_ids, user_input = resolve_plugin_routing(body, registry, plugin_ctx)
    except (UnsupportedTaskError, RunInvalidRequestError) as exc:
        return _routing_error_response(
            exc=exc,
            request_id=request_id,
            api_version="v1",
            task_type=task_type,
            page=page,
            image_bytes=0,
            session_id=body.session_id,
        )

    plugin_ctx = plugin_ctx.model_copy(update={"user_input": user_input})
    conversation_task_type = _conversation_task_type(plugin_ids)

    result, llm_resp, invoke_error = await _invoke_pipeline(
        pipeline=pipeline,
        plugin_ids=plugin_ids,
        plugin_ctx=plugin_ctx,
        provider=provider,
        request_id=request_id,
        api_version="v1",
        task_type=conversation_task_type,
        page=page,
        image_bytes=0,
        start=start,
        model_override_task=_model_override_task(plugin_ids),
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
        content=[TextPart(text=user_input or "")],
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
        task_type=conversation_task_type,
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
        plugins=plugin_ids,
    )


async def execute_run(
    *,
    request: Request,
    body: TranslateRequest,
    provider: Provider,
    settings: Settings,
    registry: PluginRegistry,
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
            registry=registry,
            request_id=request_id,
            start=start,
            allowed_task_types=allowed_task_types,
        )

    return await _execute_follow_up_v1(
        body=body,
        provider=provider,
        settings=settings,
        registry=registry,
        request_id=request_id,
        start=start,
        allowed_task_types=allowed_task_types,
    )


async def _stream_driver_events(
    *,
    prepared: PreparedStreamRun,
    provider: Provider,
) -> AsyncIterator[LLMStreamEvent]:
    accumulated_text = ""
    interrupted = False
    usage: LLMUsage | None = None
    model: str | None = None
    thinking_enabled = False
    stream_error: LLMStreamEvent | None = None

    try:
        llm_req = prepared.pipeline.build_request(
            prepared.plugin_ids,
            prepared.plugin_ctx,
        )
        llm_req = llm_req.model_copy(update={"stream": True})
        override_task = _model_override_task(prepared.plugin_ids)
        if override_task is not None:
            llm_req = _inject_model_override(llm_req, override_task)
        async for event in provider.invoke_stream(llm_req):
            if event.type == "text_delta" and event.delta:
                accumulated_text += event.delta
                yield event
            elif event.type == "usage":
                usage = event.usage
                yield event
            elif event.type == "done":
                model = event.model
                thinking_enabled = bool(event.thinking_enabled)
                yield event
                break
            elif event.type == "error":
                interrupted = True
                stream_error = event
                yield event
                break
    except asyncio.CancelledError:
        interrupted = True
        raise
    finally:
        latency_ms = int((time.perf_counter() - prepared.start) * 1000)
        assistant_meta = {
            "model": model,
            "prompt_tokens": usage.prompt_tokens if usage else None,
            "completion_tokens": usage.completion_tokens if usage and not interrupted else None,
            "latency_ms": latency_ms,
        }
        store = get_session_store()
        if prepared.is_first_turn:
            await store.finalize_streaming_assistant(
                prepared.conversation_id,
                turn_index=prepared.turn_index,
                assistant_text=accumulated_text,
                interrupted=interrupted,
                assistant_meta=assistant_meta,
            )
        elif accumulated_text or interrupted:
            user_msg = LLMMessage(
                role="user",
                content=[TextPart(text=prepared.follow_up_user_input or "")],
            )
            assistant_msg = LLMMessage(
                role="assistant",
                content=[TextPart(text=accumulated_text)],
            )
            await store.append_turn(
                prepared.conversation_id,
                user_message=user_msg,
                assistant_message=assistant_msg,
                turn_index=prepared.turn_index,
                assistant_meta=assistant_meta,
                interrupted=interrupted,
            )
        _ = stream_error


async def prepare_stream_run(
    *,
    request: Request,
    body: TranslateRequest,
    provider: Provider,
    settings: Settings,
    registry: PluginRegistry,
    request_id: str,
    allowed_task_types: set[str] | None = None,
) -> JSONResponse | PreparedStreamRun:
    start = time.perf_counter()
    task_type = body.task_type
    page = body.selection.page if body.selection is not None else 0
    pipeline = _make_pipeline(registry, provider)

    if body.session_id is None:
        if not body.pdf_id:
            return _error_json(
                status_code=400,
                code="INVALID_REQUEST",
                message="First turn requires pdf_id.",
                request_id=request_id,
                api_version=API_VERSION,
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
                api_version=API_VERSION,
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
                api_version=API_VERSION,
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
            api_version=API_VERSION,
            task_type=task_type,
            page=page,
        )
        if image_error is not None:
            return image_error

        extract_ctx = TaskContext(
            selection=body.selection,
            image=body.image,
            options={"temperature": settings.llm_temperature},
            project_id=project_id,
            pdf_id=pdf_id,
        )
        extract_start = time.perf_counter()
        extract_result, extract_resp, extract_error = await _invoke_extract_task(
            ctx=extract_ctx,
            provider=provider,
            request_id=request_id,
            api_version=API_VERSION,
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

        plugin_ctx = PluginContext(
            selection_text=extracted_text,
            selection_type="image",
            selection_word_count=estimate_word_count(extracted_text),
            target_lang=body.options.target_lang,
            history=[],
        )
        try:
            plugin_ids, user_input = resolve_plugin_routing(body, registry, plugin_ctx)
        except (UnsupportedTaskError, RunInvalidRequestError) as exc:
            return _routing_error_response(
                exc=exc,
                request_id=request_id,
                api_version=API_VERSION,
                task_type=task_type,
                page=page,
                image_bytes=image_bytes,
                project_id=project_id,
                pdf_id=pdf_id,
            )

        plugin_ctx = plugin_ctx.model_copy(update={"user_input": user_input})
        conversation_task_type = _conversation_task_type(plugin_ids)

        conversation_id = f"conv_{ULID()}"
        selection_id = f"sel_{ULID()}"
        user_history_text = _compose_user_history_text(extracted_text, user_input)
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
        try:
            await store.create(
                conversation_id=conversation_id,
                project_id=project_id,
                pdf_id=pdf_id,
                selection_id=selection_id,
                task_type=conversation_task_type,
                extracted_text=extracted_text,
                selection_row=selection_row,
                first_user_question=user_input,
                first_user_content=user_history_text,
                first_assistant_text="",
                first_assistant_meta={"model": None},
                meta=meta,
            )
        except Exception:
            return _error_json(
                status_code=500,
                code="INTERNAL_ERROR",
                message="An internal server error occurred.",
                request_id=request_id,
                api_version=API_VERSION,
                task_type=conversation_task_type,
                page=page,
                image_bytes=image_bytes,
                project_id=project_id,
                pdf_id=pdf_id,
            )

        try:
            default_model = settings_store.get_current().default_model
        except RuntimeError:
            default_model = settings.openai_model

        meta_payload = {
            "request_id": request_id,
            "session_id": conversation_id,
            "conversation_id": conversation_id,
            "task_type": conversation_task_type,
            "turn_index": 0,
            "model": default_model,
            "thinking_enabled": _thinking_enabled_for_meta(pipeline, plugin_ids),
            "plugins": plugin_ids,
            "extract_latency_ms": extract_latency_ms,
        }
        prepared = PreparedStreamRun(
            request_id=request_id,
            start=start,
            task_type=conversation_task_type,
            page=page,
            image_bytes=image_bytes,
            project_id=project_id,
            pdf_id=pdf_id,
            conversation_id=conversation_id,
            turn_index=0,
            is_first_turn=True,
            extract_latency_ms=extract_latency_ms,
            extracted_text_chars=extracted_text_chars,
            plugin_ids=plugin_ids,
            plugin_ctx=plugin_ctx,
            pipeline=pipeline,
            follow_up_user_input=None,
            meta_payload=meta_payload,
        )
        prepared.meta_ready.set()
        return prepared

    if body.image is not None:
        return _error_json(
            status_code=400,
            code="INVALID_REQUEST",
            message="Follow-up turn must not include image.",
            request_id=request_id,
            api_version=API_VERSION,
            task_type=task_type,
            page=page,
            image_bytes=0,
            session_id=body.session_id,
        )

    store = get_session_store()
    session = await store.get(body.session_id)
    if session is None:
        return _error_json(
            status_code=400,
            code="SESSION_NOT_FOUND",
            message="Session not found.",
            request_id=request_id,
            api_version=API_VERSION,
            task_type=task_type,
            page=page,
            image_bytes=0,
            session_id=body.session_id,
        )

    # V1.1.1: cross-plugin follow-up allowed; SESSION_TASK_MISMATCH check removed.

    turn_index = len(session.messages) // 2
    plugin_ctx = PluginContext(
        selection_text=session.extracted_text,
        selection_type="image",
        selection_word_count=estimate_word_count(session.extracted_text),
        target_lang=body.options.target_lang,
        history=list(session.messages),
    )
    try:
        plugin_ids, user_input = resolve_plugin_routing(body, registry, plugin_ctx)
    except (UnsupportedTaskError, RunInvalidRequestError) as exc:
        return _routing_error_response(
            exc=exc,
            request_id=request_id,
            api_version=API_VERSION,
            task_type=task_type,
            page=page,
            image_bytes=0,
            session_id=body.session_id,
        )

    plugin_ctx = plugin_ctx.model_copy(update={"user_input": user_input})
    conversation_task_type = _conversation_task_type(plugin_ids)

    try:
        default_model = settings_store.get_current().default_model
    except RuntimeError:
        default_model = settings.openai_model

    meta_payload = {
        "request_id": request_id,
        "session_id": body.session_id,
        "conversation_id": body.session_id,
        "task_type": conversation_task_type,
        "turn_index": turn_index,
        "model": default_model,
        "thinking_enabled": _thinking_enabled_for_meta(pipeline, plugin_ids),
        "plugins": plugin_ids,
    }
    prepared = PreparedStreamRun(
        request_id=request_id,
        start=start,
        task_type=conversation_task_type,
        page=page,
        image_bytes=0,
        project_id=session.project_id,
        pdf_id=session.pdf_id,
        conversation_id=body.session_id,
        turn_index=turn_index,
        is_first_turn=False,
        extract_latency_ms=None,
        extracted_text_chars=None,
        plugin_ids=plugin_ids,
        plugin_ctx=plugin_ctx,
        pipeline=pipeline,
        follow_up_user_input=user_input,
        meta_payload=meta_payload,
    )
    prepared.meta_ready.set()
    return prepared


def _log_run_stream_completed(
    *,
    prepared: PreparedStreamRun,
    stream_chunks: int,
    first_chunk_latency_ms: int | None,
    stream_aborted: bool,
    error_code: str | None,
    latency_ms: int,
    thinking_enabled: bool,
) -> None:
    log_with_fields(
        logger,
        logging.INFO if error_code is None and not stream_aborted else logging.WARNING,
        "run stream completed",
        request_id=prepared.request_id,
        api_version=API_VERSION,
        task_type=prepared.task_type,
        page=prepared.page,
        image_bytes=prepared.image_bytes,
        model=prepared.meta_payload.get("model", ""),
        latency_ms=latency_ms,
        prompt_tokens="",
        completion_tokens="",
        http_status=200,
        error_code=error_code or "",
        session_id=prepared.conversation_id,
        turn_index=prepared.turn_index,
        extract_latency_ms=prepared.extract_latency_ms if prepared.extract_latency_ms is not None else "",
        extracted_text_chars=prepared.extracted_text_chars if prepared.extracted_text_chars is not None else "",
        project_id=prepared.project_id or "",
        pdf_id=prepared.pdf_id or "",
        conversation_id=prepared.conversation_id,
        thinking_enabled=thinking_enabled,
        plugins=_plugins_log_value(prepared.plugin_ids),
        stream=True,
        stream_chunks=stream_chunks,
        first_chunk_latency_ms=first_chunk_latency_ms if first_chunk_latency_ms is not None else "",
        stream_aborted=stream_aborted,
    )


async def iter_run_sse_bytes(
    *,
    prepared: PreparedStreamRun,
    provider: Provider,
    heartbeat_seconds: float = STREAM_HEARTBEAT_SECONDS,
) -> AsyncIterator[bytes]:
    stream_start = time.perf_counter()
    stream_chunks = 0
    first_chunk_latency_ms: int | None = None
    stream_aborted = False
    error_code: str | None = None
    thinking_enabled = bool(prepared.meta_payload.get("thinking_enabled", False))

    pending: asyncio.Task | None = None
    try:
        await prepared.meta_ready.wait()
        yield _encode_sse("meta", prepared.meta_payload)

        events_iter = _stream_driver_events(
            prepared=prepared, provider=provider
        ).__aiter__()
        pending = asyncio.create_task(events_iter.__anext__())
        while pending is not None:
            done_set, _ = await asyncio.wait({pending}, timeout=heartbeat_seconds)
            if pending not in done_set:
                yield _SSE_KEEP_ALIVE
                continue

            try:
                event = pending.result()
            except StopAsyncIteration:
                break
            pending = asyncio.create_task(events_iter.__anext__())

            if event.type == "text_delta":
                stream_chunks += 1
                if first_chunk_latency_ms is None:
                    first_chunk_latency_ms = int((time.perf_counter() - stream_start) * 1000)
                yield _encode_sse("text_delta", {"delta": event.delta})
            elif event.type == "usage":
                yield _encode_sse("usage", _usage_to_dict(event.usage))
            elif event.type == "done":
                if event.thinking_enabled is not None:
                    thinking_enabled = bool(event.thinking_enabled)
                yield _encode_sse(
                    "done",
                    {"latency_ms": int((time.perf_counter() - prepared.start) * 1000)},
                )
            elif event.type == "error":
                error_code = event.code
                yield _encode_sse(
                    "error",
                    {
                        "code": event.code,
                        "message": event.message,
                        "retriable": event.retriable,
                        "partial_text_kept": stream_chunks > 0,
                    },
                )
    except (asyncio.CancelledError, GeneratorExit):
        stream_aborted = True
        raise
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
        _log_run_stream_completed(
            prepared=prepared,
            stream_chunks=stream_chunks,
            first_chunk_latency_ms=first_chunk_latency_ms,
            stream_aborted=stream_aborted,
            error_code=error_code,
            latency_ms=int((time.perf_counter() - prepared.start) * 1000),
            thinking_enabled=thinking_enabled,
        )
