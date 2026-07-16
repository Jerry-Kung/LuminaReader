from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from lumina import settings_store
from lumina.request_id import generate_request_id
from lumina.schemas.api import (
    ContextExpansionSettingsOut,
    SettingsProviderOut,
    SettingsResponse,
    ThinkingSettingsOut,
)

router = APIRouter(tags=["settings"])


def _build_settings_response(current: settings_store.ResolvedSettings) -> SettingsResponse:
    return SettingsResponse(
        provider=SettingsProviderOut(
            kind=current.provider_kind,
            base_url=current.base_url,
            api_key_masked=settings_store.mask_api_key(current.api_key),
            default_model=current.default_model,
            timeout_seconds=current.timeout_seconds,
        ),
        task_models=dict(current.task_models),
        thinking=ThinkingSettingsOut(enabled=current.thinking.enabled),
        context_expansion=ContextExpansionSettingsOut(
            enabled=current.context_expansion.enabled
        ),
        source=current.source,
        writable=settings_store.is_writable(),
        provider_ready=current.api_key is not None and bool(current.base_url),
    )


def _settings_ok(current: settings_store.ResolvedSettings) -> dict[str, Any]:
    return {
        "ok": True,
        "data": _build_settings_response(current).model_dump(),
    }


@router.get("/settings")
async def get_settings_endpoint() -> dict[str, Any]:
    return _settings_ok(settings_store.get_current())


@router.put("/settings", response_model=None)
async def put_settings_endpoint(payload: dict[str, Any]) -> JSONResponse | dict[str, Any]:
    request_id = generate_request_id()
    try:
        new_state = settings_store.apply_update(payload)
    except settings_store.InvalidSettingsError as exc:
        first_reason = (
            exc.field_errors[0]["reason"] if exc.field_errors else "invalid settings"
        )
        return JSONResponse(
            status_code=422,
            content={
                "ok": False,
                "error": {
                    "code": "INVALID_SETTINGS",
                    "message": first_reason,
                    "request_id": request_id,
                    "field_errors": [
                        {"path": fe["path"], "reason": fe["reason"]}
                        for fe in exc.field_errors
                    ],
                },
            },
        )
    except settings_store.SettingsPersistError as exc:
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": {
                    "code": "SETTINGS_PERSIST_FAILED",
                    "message": str(exc),
                    "request_id": request_id,
                },
            },
        )
    return _settings_ok(new_state)
