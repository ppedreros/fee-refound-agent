"""`POST /cases/{id}/decision` (SPEC-api): the only route that moves money."""

from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Header, Path, Request
from sqlalchemy.exc import IntegrityError

from backend.api.decision_service import Actor, make_decision
from backend.api.errors import ApiError
from backend.api.resources import AppResources
from backend.api.schemas import DecisionRequest, DecisionResult
from backend.core.settings import Settings

router = APIRouter()


@router.post("/cases/{case_id}/decision")
async def post_decision(
    request: Request,
    case_id: Annotated[int, Path(ge=1)],
    body: DecisionRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> DecisionResult:
    key = _uuid(idempotency_key)
    if key is None:  # 1. The key.
        raise ApiError(
            422, "invalid_idempotency_key", "We couldn't send this decision. Please try again."
        )
    resources: AppResources = request.app.state.resources
    settings: Settings = request.app.state.settings
    actor = Actor(
        staff_id=settings.staff_id,
        now=resources.clock.now(),
        request_id=_uuid(structlog.contextvars.get_contextvars().get("request_id")),
    )

    async def decide() -> DecisionResult:
        async with resources.writer() as session, session.begin():
            return await make_decision(
                session, case_id, key, body, actor=actor, params=resources.policy_params
            )

    try:
        return await decide()
    except IntegrityError:
        # The same key was used at the same moment on another case. Deciding again finds that
        # decision and answers like any repeated key.
        return await decide()


def _uuid(value: str | None) -> UUID | None:
    try:
        return UUID(value) if value else None
    except ValueError:
        return None
