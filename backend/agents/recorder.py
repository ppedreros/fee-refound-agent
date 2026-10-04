"""Writes the run trace (D8): `agent_runs`, `agent_steps` and the case row, as `app_writer`.

Only the runner calls this. The graph's nodes never hold a writer session.
"""

from typing import Any
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.agents.steps import StepRecord
from backend.db.models import AgentRun, AgentStep, Case

_JSON: TypeAdapter[dict[str, Any] | None] = TypeAdapter(dict[str, Any] | None)

type Writer = async_sessionmaker[AsyncSession]


class RunInProgress(Exception):
    """The case already has a running run (one active run per case, D-api-2)."""

    def __init__(self, run_id: UUID | None) -> None:
        super().__init__("run_in_progress")
        self.run_id = run_id


async def start_run(writer: Writer, case_id: int) -> UUID:
    """Create the run and set the case to `checking`, in one transaction."""
    try:
        async with writer() as session, session.begin():
            await session.execute(
                insert(Case)
                .values(conversation_id=case_id, status="checking")
                .on_conflict_do_update(
                    index_elements=[Case.conversation_id],
                    set_={
                        "status": "checking",
                        "updated_at": func.now(),
                        "row_version": Case.row_version + 1,
                    },
                )
            )
            run_id: UUID | None = await session.scalar(
                insert(AgentRun).values(case_id=case_id, status="running").returning(AgentRun.id)
            )
    except IntegrityError:
        raise RunInProgress(await _running_run(writer, case_id)) from None
    if run_id is None:
        raise RuntimeError("the run row was not created")
    return run_id


async def record_step(writer: Writer, run_id: UUID, record: StepRecord) -> None:
    meta = record.meta
    async with writer() as session, session.begin():
        session.add(
            AgentStep(
                run_id=run_id,
                node=record.node,
                kind=record.kind,
                status=record.status,
                started_at=record.started_at,
                latency_ms=record.latency_ms,
                model=meta.model if meta else None,
                prompt_version=record.prompt_version,
                tokens_in=meta.tokens_in if meta else None,
                tokens_out=meta.tokens_out if meta else None,
                tokens_cached=meta.tokens_cached if meta else None,
                cost_usd=meta.cost_usd if meta else None,
                attempts=meta.attempts if meta else None,
                error_code=record.error_code,
                input_masked=_JSON.dump_python(record.input_masked, mode="json"),
                output=_JSON.dump_python(record.output, mode="json"),
            )
        )


async def finish_run(
    writer: Writer,
    *,
    run_id: UUID,
    case_id: int,
    result: dict[str, Any],
    totals: dict[str, Any],
) -> None:
    async with writer() as session, session.begin():
        await session.execute(
            update(AgentRun)
            .where(AgentRun.id == run_id)
            .values(
                status="completed",
                finished_at=func.now(),
                outcome=result["status"],
                reason_codes=[*result.get("reasons", []), *result.get("notes", [])],
                would_auto_approve=bool(result.get("would_auto_approve", False)),
                classifier_used=result.get("classifier_used"),
                result=_JSON.dump_python(result, mode="json"),
                **totals,
            )
        )
        await session.execute(
            update(Case)
            .where(Case.conversation_id == case_id)
            .values(
                status=result["status"],
                topic=result.get("topic"),
                latest_run_id=run_id,
                updated_at=func.now(),
                row_version=Case.row_version + 1,
            )
        )


async def fail_run(writer: Writer, *, run_id: UUID, case_id: int) -> None:
    """An unexpected error: the run fails and the case can be checked again."""
    async with writer() as session, session.begin():
        await session.execute(
            update(AgentRun)
            .where(AgentRun.id == run_id)
            .values(status="failed", finished_at=func.now())
        )
        await _back_to_not_checked(session, [case_id])


async def reset_interrupted_runs(writer: Writer) -> int:
    """At startup: runs still `running` were cut off by a restart. They become `interrupted`, and
    their cases go back to `not_checked`, so "Check again" is offered. Runs only read, so running
    again is safe."""
    async with writer() as session, session.begin():
        cases = (
            await session.scalars(
                update(AgentRun)
                .where(AgentRun.status == "running")
                .values(status="interrupted", finished_at=func.now())
                .returning(AgentRun.case_id)
            )
        ).all()
        await _back_to_not_checked(session, list(cases))
    return len(cases)


async def _back_to_not_checked(session: AsyncSession, case_ids: list[int]) -> None:
    if case_ids:
        await session.execute(
            update(Case)
            .where(Case.conversation_id.in_(case_ids))
            .values(status="not_checked", updated_at=func.now(), row_version=Case.row_version + 1)
        )


async def _running_run(writer: Writer, case_id: int) -> UUID | None:
    async with writer() as session:
        return await session.scalar(
            select(AgentRun.id).where(AgentRun.case_id == case_id, AgentRun.status == "running")
        )
