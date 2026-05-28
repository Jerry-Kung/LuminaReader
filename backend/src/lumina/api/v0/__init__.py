from fastapi import APIRouter

from lumina.api.v0 import health, translate

router = APIRouter(prefix="/api/v0")
router.include_router(health.router)
router.include_router(translate.router)
