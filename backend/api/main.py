"""FastAPI application factory."""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from sqlalchemy.exc import SQLAlchemyError

from backend.agents.runner import reset_interrupted_runs
from backend.api.errors import install_error_handlers
from backend.api.middleware import RequestIdMiddleware
from backend.api.resources import AppResources, default_resources
from backend.api.routes_cases import router as cases_router
from backend.api.routes_decision import router as decision_router
from backend.api.routes_health import router as health_router
from backend.core.logging import configure_logging
from backend.core.settings import Settings, load_settings
from backend.core.version import app_version

STARTUP_DB_TIMEOUT_S = 5.0

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    resources: AppResources = app.state.resources_factory(app.state.settings)
    app.state.resources = resources
    app.state.engine = resources.writer_engine  # /health checks the database as app_writer
    app.state.run_tasks = set()
    await _reset_interrupted_runs(resources)
    yield
    tasks = list(app.state.run_tasks)
    for task in tasks:  # a cut-off run is marked interrupted at the next startup
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await resources.close()


def create_app(
    settings: Settings | None = None,
    *,
    resources: Callable[[Settings], AppResources] = default_resources,
) -> FastAPI:
    settings = settings or load_settings()
    configure_logging(settings.log_level, settings.masking_salt)
    app = FastAPI(title="Fee Refund Agent", lifespan=lifespan)
    app.state.settings = settings
    app.state.version = app_version(settings)
    app.state.resources_factory = resources
    app.add_middleware(RequestIdMiddleware)
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(cases_router)
    app.include_router(decision_router)
    return app


async def _reset_interrupted_runs(resources: AppResources) -> None:
    """Runs left `running` by a restart become `interrupted`. If the database isn't reachable
    yet, the API still starts and /health reports it."""
    try:
        async with asyncio.timeout(STARTUP_DB_TIMEOUT_S):
            count = await reset_interrupted_runs(resources.writer)
    except TimeoutError, OSError, SQLAlchemyError:
        log.warning("interrupted_runs_not_reset")
        return
    if count:
        log.info("interrupted_runs_reset", count=count)
