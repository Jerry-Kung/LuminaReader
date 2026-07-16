import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import lumina
from lumina.api.v0 import router as v0_router
from lumina.api.v1 import router as v1_router
from lumina.config import Settings, get_settings
from lumina.db.engine import close_all
from lumina.db.startup import apply_pending_for_all_projects
from lumina.logging import get_logger, log_with_fields, setup_logging
from lumina.pdftext import wait_for_inflight
from lumina.projects.catalog import load_catalog
from lumina.projects.paths import resolve_data_root
from lumina import settings_store
from lumina.plugins import PluginRegistry, get_plugins_root
from lumina.providers import init_provider_from_resolved, reset_provider
from lumina.sessions import cleanup_loop, init_session_store, reset_session_store
from lumina.request_id import generate_request_id
from lumina.schemas.api import error_response


def register_exception_handlers(app: FastAPI) -> None:
    logger = get_logger("lumina.errors")

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        request_id = generate_request_id()
        errors = exc.errors()
        overlong = any(
            "exceeds LUMINA_SELECTION_TEXT_MAX_CHARS" in str(err.get("msg", ""))
            for err in errors
        )
        if overlong:
            log_with_fields(
                logger,
                logging.WARNING,
                "selection text too large",
                request_id=request_id,
                path=str(request.url.path),
                error_code="PAYLOAD_TOO_LARGE",
            )
            return JSONResponse(
                status_code=413,
                content=error_response(
                    code="PAYLOAD_TOO_LARGE",
                    message="selection.text exceeds maximum size.",
                    request_id=request_id,
                ),
            )
        log_with_fields(
            logger,
            logging.WARNING,
            "request validation failed",
            request_id=request_id,
            path=str(request.url.path),
            error_code="INVALID_REQUEST",
        )
        return JSONResponse(
            status_code=400,
            content=error_response(
                code="INVALID_REQUEST",
                message="Request validation failed.",
                request_id=request_id,
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = generate_request_id()
        log_with_fields(
            logger,
            logging.ERROR,
            "unhandled exception",
            request_id=request_id,
            path=str(request.url.path),
            error_code="INTERNAL_ERROR",
            exception_type=type(exc).__name__,
        )
        return JSONResponse(
            status_code=500,
            content=error_response(
                code="INTERNAL_ERROR",
                message="An internal server error occurred.",
                request_id=request_id,
            ),
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_logging(cfg.log_level)
        data_root = resolve_data_root()
        data_root.mkdir(parents=True, exist_ok=True)
        load_catalog()
        apply_pending_for_all_projects()
        resolved = settings_store.bootstrap()
        app.state.provider = init_provider_from_resolved(
            api_key=resolved.api_key,
            base_url=resolved.base_url,
            default_model=resolved.default_model,
            timeout_seconds=resolved.timeout_seconds,
        )
        store = init_session_store(
            max_entries=cfg.session_max_entries,
            ttl_seconds=cfg.session_ttl_seconds,
        )
        cleanup_task = asyncio.create_task(cleanup_loop(store))
        plugin_registry = PluginRegistry.load_all(get_plugins_root())
        app.state.plugin_registry = plugin_registry
        logger = get_logger("lumina.startup")
        plugin_ids = ", ".join(sorted(plugin_registry.plugins.keys()))
        log_with_fields(
            logger,
            logging.INFO,
            f"loaded {len(plugin_registry.plugins)} plugins: {plugin_ids}",
            event="plugins_loaded",
            plugin_count=len(plugin_registry.plugins),
            plugin_ids=plugin_ids,
        )
        log_with_fields(
            logger,
            logging.INFO,
            "lumina-backend started",
            service="lumina-backend",
            version=lumina.__version__,
            host=cfg.host,
            port=cfg.port,
            data_root=str(data_root),
        )
        log_with_fields(
            logger,
            logging.WARNING,
            "/api/v0/* endpoints are gone; clients must migrate to /api/v1/run",
            event="v0_gone",
        )
        try:
            yield
        finally:
            cleanup_task.cancel()
            try:
                await cleanup_task
            except (asyncio.CancelledError, Exception):
                pass
            # V1.2.1：等待进行中的全书文本提取收尾，再关数据库连接
            try:
                await wait_for_inflight()
            except Exception:
                pass
            close_all()
            reset_session_store()
            reset_provider()

    app = FastAPI(
        title="lumina-backend",
        version=lumina.__version__,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(v0_router)
    app.include_router(v1_router)
    register_exception_handlers(app)
    return app


app = create_app()
