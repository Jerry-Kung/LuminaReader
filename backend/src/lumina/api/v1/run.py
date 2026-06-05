from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from lumina.api._run_core import execute_run, iter_run_sse_bytes, prepare_stream_run
from lumina.config import Settings, get_settings
from lumina.plugins import PluginRegistry, get_plugin_registry
from lumina.providers import get_provider
from lumina.providers.base import Provider
from lumina.request_id import generate_request_id
from lumina.schemas.api import TranslateRequest

router = APIRouter(tags=["run"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@router.post("/run", response_model=None)
async def run(
    request: Request,
    body: TranslateRequest,
    provider: Provider = Depends(get_provider),
    settings: Settings = Depends(get_settings),
    registry: PluginRegistry = Depends(get_plugin_registry),
):
    if body.options.stream:
        request_id = generate_request_id()
        prepared = await prepare_stream_run(
            request=request,
            body=body,
            provider=provider,
            settings=settings,
            registry=registry,
            request_id=request_id,
            allowed_task_types=None,
        )
        if isinstance(prepared, JSONResponse):
            return prepared
        return StreamingResponse(
            iter_run_sse_bytes(prepared=prepared, provider=provider),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    return await execute_run(
        request=request,
        body=body,
        provider=provider,
        settings=settings,
        registry=registry,
        allowed_task_types=None,
    )
