from fastapi import APIRouter, Depends

import lumina
from lumina.providers import get_provider
from lumina.providers.base import Provider
from lumina.schemas.api import HealthData, ok_response

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(provider: Provider = Depends(get_provider)) -> dict:
    provider_ready = await provider.health_check()
    data = HealthData(
        service="lumina-backend",
        version=lumina.__version__,
        provider_ready=provider_ready,
    )
    return ok_response(data)
