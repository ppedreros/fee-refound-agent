"""`GET /health`: the API is up, it can reach the database as `app_writer`, and in which mode
each model provider runs (D10), with the app version."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel

from backend.core.settings import ProviderModes, Settings
from backend.db.engine import ping

DATABASE_TIMEOUT_S = 2.0

router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    database: Literal["ok", "unavailable"]
    provider_mode: ProviderModes  # the UI shows "Replay mode" when a model answers from recordings
    version: str


async def database_is_up(request: Request) -> bool:
    return await ping(request.app.state.engine, timeout_s=DATABASE_TIMEOUT_S)


@router.get("/health", responses={503: {"model": HealthResponse}})
async def health(
    request: Request, response: Response, database_up: Annotated[bool, Depends(database_is_up)]
) -> HealthResponse:
    settings: Settings = request.app.state.settings
    about = {"provider_mode": settings.provider_modes, "version": request.app.state.version}
    if database_up:
        return HealthResponse(status="ok", database="ok", **about)
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="unavailable", database="unavailable", **about)
