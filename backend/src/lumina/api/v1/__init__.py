from fastapi import APIRouter

from lumina.api.v1 import health, run

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(run.router)
