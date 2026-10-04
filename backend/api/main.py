"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.api.routes_health import router as health_router
from backend.core.settings import Settings, load_settings
from backend.db.engine import make_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.engine = make_engine(app.state.settings.app_database_url)
    yield
    await app.state.engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="Fee Refund Agent", lifespan=lifespan)
    app.state.settings = settings or load_settings()
    app.include_router(health_router)
    return app
