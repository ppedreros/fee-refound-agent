"""The queue, one case and checking a case (SPEC-api: `GET /cases`, `GET /cases/{id}` and
`POST /cases/{id}/run`)."""

import asyncio
from typing import Annotated, Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Body, FastAPI, Path, Query, Request, status
from sqlalchemy import select

from backend.agents.deps import AgentDeps
from backend.agents.runner import RunInProgress, RunnerDeps, run_case, start_run
from backend.api.auto_approve import auto_approve
from backend.api.errors import NOT_FOUND, ApiError
from backend.api.events import RunEvents
from backend.api.middleware import current_request_id
from backend.api.queue import View, list_queue
from backend.api.resources import AppResources
from backend.api.schemas import AccountNumber, CaseView, QueuePage, RunRequest, RunStarted
from backend.api.view_model import load_case_view
from backend.core.settings import Settings
from backend.db.models import Account, AgentRun, AuditEvent, Case, Conversation

router = APIRouter()
log = structlog.get_logger()

NOT_RUNNING = {
    "closed": "This conversation is closed.",
    "waiting_for_member": "This conversation is waiting for the member.",
}


@router.get("/cases")
async def list_cases(
    request: Request,
    view: View = "open",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> QueuePage:
    async with _resources(request).writer() as session:
        return await list_queue(session, view, limit, cursor)


@router.get("/cases/{case_id}")
async def get_case(request: Request, case_id: Annotated[int, Path(ge=1)]) -> CaseView:
    resources = _resources(request)
    async with resources.writer() as session:
        return await load_case_view(session, case_id, resources.policy_params)


@router.get("/cases/{case_id}/accounts/{account_id}/number")
async def reveal_account_number(
    request: Request,
    case_id: Annotated[int, Path(ge=1)],
    account_id: Annotated[int, Path(ge=1)],
) -> AccountNumber:
    """The full number, for this one request, and audited (SPEC-api; D9)."""
    settings: Settings = request.app.state.settings
    async with _resources(request).writer() as session, session.begin():
        number = await session.scalar(
            select(Account.account_number)
            .join(Conversation, Conversation.member_id == Account.member_id)
            .where(Conversation.id == case_id, Account.id == account_id)
        )
        if number is None:  # no such account, or not this member's
            raise ApiError(404, "not_found", "We couldn't find that account.")
        session.add(
            AuditEvent(
                actor=settings.staff_id,
                action="account_number_revealed",
                case_id=case_id,
                request_id=current_request_id(),
                details={"account_id": account_id},
            )
        )
    return AccountNumber(account_number=number)


@router.post("/cases/{case_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def check_case(
    request: Request,
    case_id: Annotated[int, Path(ge=1)],
    body: Annotated[RunRequest | None, Body()] = None,
) -> RunStarted:
    resources = _resources(request)
    fee_txn_id = body.fee_txn_id if body else None
    async with resources.writer() as session:
        row = (
            await session.execute(
                select(Conversation.status, Case.status, AgentRun.result)
                .select_from(Conversation)
                .outerjoin(Case, Case.conversation_id == Conversation.id)
                .outerjoin(AgentRun, AgentRun.id == Case.latest_run_id)
                .where(Conversation.id == case_id)
            )
        ).one_or_none()
    if row is None:
        raise ApiError(404, *NOT_FOUND)
    conversation_status, case_status, latest_result = row
    if conversation_status in NOT_RUNNING:
        raise ApiError(409, "case_not_running", NOT_RUNNING[conversation_status])
    if case_status == "done":
        raise ApiError(409, "case_not_running", "This case is already done.")
    if fee_txn_id is not None and fee_txn_id not in _candidate_ids(latest_result):
        raise ApiError(422, "invalid_fee", "That fee isn't one of the options for this case.")

    try:
        run_id = await start_run(resources.writer, case_id)
    except RunInProgress as error:
        raise ApiError(
            409,
            "run_in_progress",
            "This case is being checked right now.",
            extra={"run_id": str(error.run_id) if error.run_id else None},
        ) from None
    _start_in_background(request.app, case_id, run_id, fee_txn_id)
    return RunStarted(run_id=run_id)


def _start_in_background(app: FastAPI, case_id: int, run_id: UUID, fee_txn_id: int | None) -> None:
    resources: AppResources = app.state.resources
    hub: RunEvents = app.state.run_events
    hub.open(run_id)  # before the run starts, so a follower misses nothing

    async def publish(event: dict[str, Any]) -> None:
        await hub.publish(run_id, event)

    deps = RunnerDeps(
        writer=resources.writer,
        agent=AgentDeps(
            reader=resources.reader,
            classifier=resources.classifier,
            drafter=resources.drafter,
            chooser=resources.chooser,
        ),
        provider_modes=resources.provider_modes,
        on_event=publish,
    )

    settings: Settings = app.state.settings

    async def run() -> None:
        try:
            result = await run_case(case_id, deps, run_id=run_id, pinned_fee_txn_id=fee_txn_id)
        except Exception:  # run_case logged it and marked the run failed
            log.warning("background_run_failed", run_id=str(run_id))
            return
        if settings.auto_approve_enabled and result.result.get("would_auto_approve"):
            await auto_approve(resources, case_id, run_id)  # tests only (D5)

    task = asyncio.create_task(run())
    tasks: set[asyncio.Task[None]] = app.state.run_tasks
    tasks.add(task)
    task.add_done_callback(tasks.discard)


def _candidate_ids(result: dict[str, Any] | None) -> set[int]:
    return {c["id"] for c in (result or {}).get("candidates", []) if "id" in c}


def _resources(request: Request) -> AppResources:
    resources: AppResources = request.app.state.resources
    return resources
