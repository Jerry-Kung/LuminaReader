from fastapi import APIRouter

from lumina.api.v1 import conversations, health, library, pdfs, projects, run, sessions

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(run.router)
router.include_router(sessions.router)
router.include_router(library.router)
router.include_router(pdfs.router)
router.include_router(conversations.router)
router.include_router(projects.router)
