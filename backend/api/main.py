"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.api.middleware import RequestIdMiddleware
from backend.api.routes_health import router as health_router
from backend.core.logging import configure_logging
from backend.core.settings import Settings, load_settings
from backend.db.engine import make_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.engine = make_engine(app.state.settings.app_database_url)
    yield
    await app.state.engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    configure_logging(settings.log_level, settings.masking_salt)
    app = FastAPI(title="Fee Refund Agent", lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(RequestIdMiddleware)
    app.include_router(health_router)
    return app
