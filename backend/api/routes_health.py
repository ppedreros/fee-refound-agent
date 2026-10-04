"""`GET /health`: the API is up, and it can reach the database as `app_writer`."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel

from backend.db.engine import ping

DATABASE_TIMEOUT_S = 2.0

router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    database: Literal["ok", "unavailable"]


async def database_is_up(request: Request) -> bool:
    return await ping(request.app.state.engine, timeout_s=DATABASE_TIMEOUT_S)


@router.get("/health", responses={503: {"model": HealthResponse}})
async def health(
    response: Response, database_up: Annotated[bool, Depends(database_is_up)]
) -> HealthResponse:
    if database_up:
        return HealthResponse(status="ok", database="ok")
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="unavailable", database="unavailable")
