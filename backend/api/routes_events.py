"""`GET /cases/{id}/runs/{run_id}/events` (SPEC-api): a check's steps as server-sent events.

Each event is `{"event": "step", "node", "state"}`, and the last is `{"event": "done", "status"}`.
A run that is active in this process is followed live, history first; a run that ended is read
back from its trace (`agent_steps`). A keep-alive comment goes out every 15 seconds.
"""

import json
from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Path, Request
from sqlalchemy import select
from sse_starlette import EventSourceResponse, ServerSentEvent

from backend.api.errors import ApiError
from backend.api.events import Event, RunEvents
from backend.api.resources import AppResources
from backend.db.models import AgentRun, AgentStep

KEEP_ALIVE_S = 15
NOT_FOUND = ("not_found", "We couldn't find that check.")
DONE_STATUS = {"failed": "failed", "interrupted": "interrupted"}  # a completed run: its outcome

router = APIRouter()


@router.get("/cases/{case_id}/runs/{run_id}/events")
async def run_events(
    request: Request, case_id: Annotated[int, Path(ge=1)], run_id: UUID
) -> EventSourceResponse:
    resources: AppResources = request.app.state.resources
    hub: RunEvents = request.app.state.run_events
    async with resources.writer() as session:
        run = (
            await session.execute(select(AgentRun.case_id).where(AgentRun.id == run_id))
        ).one_or_none()
    if run is None or run.case_id != case_id:
        raise ApiError(404, *NOT_FOUND)

    events = hub.follow(run_id) or _recorded(resources, run_id)
    return EventSourceResponse(_sse(events), ping=KEEP_ALIVE_S)


async def _recorded(resources: AppResources, run_id: UUID) -> AsyncIterator[Event]:
    """A run that isn't active here: its recorded steps, then `done` once it has ended. If it is
    still running elsewhere, the stream just ends, and the browser's EventSource reconnects."""
    async with resources.writer() as session:
        steps = (
            await session.execute(
                select(AgentStep.node, AgentStep.status)
                .where(AgentStep.run_id == run_id)
                .order_by(AgentStep.id)
            )
        ).all()
        run = (
            await session.execute(
                select(AgentRun.status, AgentRun.outcome).where(AgentRun.id == run_id)
            )
        ).one()
    for step in steps:
        yield {"event": "step", "node": step.node, "state": "started"}
        yield {"event": "step", "node": step.node, "state": step.status}
    if run.status != "running":
        yield {"event": "done", "status": run.outcome or DONE_STATUS.get(run.status, run.status)}


async def _sse(events: AsyncIterator[Event]) -> AsyncIterator[ServerSentEvent]:
    async for event in events:
        yield ServerSentEvent(data=json.dumps(_public(event)))


def _public(event: dict[str, Any]) -> Event:
    """Only what the page uses: never a step record (it holds masked inputs)."""
    keys = ("event", "node", "state") if event.get("event") == "step" else ("event", "status")
    return {key: event[key] for key in keys if key in event}
