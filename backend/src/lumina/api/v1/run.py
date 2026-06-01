from fastapi import APIRouter, Depends, Request

from lumina.api._run_core import execute_run
from lumina.config import Settings, get_settings
from lumina.providers import get_provider
from lumina.providers.base import Provider
from lumina.schemas.api import TranslateRequest

router = APIRouter(tags=["run"])


@router.post("/run", response_model=None)
async def run(
    request: Request,
    body: TranslateRequest,
    provider: Provider = Depends(get_provider),
    settings: Settings = Depends(get_settings),
):
    return await execute_run(
        request=request,
        body=body,
        provider=provider,
        settings=settings,
        allowed_task_types=None,
    )
