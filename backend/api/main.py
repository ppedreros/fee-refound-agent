"""FastAPI application factory."""

from fastapi import FastAPI

from backend.core.settings import Settings, load_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="Fee Refund Agent")
    app.state.settings = settings or load_settings()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
