"""Runs the agent graph for one case and records it (SPEC-agent, "Runner and recording").

The run has a 45-second budget; its deadline reaches every model and tool call. Steps are recorded
from the stream, outside node code, with the writer session; the graph only ever gets the reader.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any
from uuid import UUID

import structlog
import yaml

from backend.agents.deps import AgentDeps
from backend.agents.graph import build_graph
from backend.agents.recorder import (
    RunInProgress,
    Writer,
    fail_run,
    finish_run,
    record_step,
    reset_interrupted_runs,
    start_run,
)
from backend.agents.state import GraphState
from backend.agents.steps import StepRecord
from backend.policy.reasons import ReasonCode

__all__ = [
    "RunInProgress",
    "RunResult",
    "RunnerDeps",
    "reset_interrupted_runs",
    "run_case",
    "start_run",
]

CONFIG_FILE = Path(__file__).resolve().parents[1] / "core" / "config" / "runs.yaml"
RUN_TIMEOUT_S = float(yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))["timeout_s"])

# When the run timeout fires, the reason belongs to the node that was running.
TIMEOUT_REASON = {"triage": ReasonCode.CLASSIFIER_DOWN, "draft": ReasonCode.DRAFTER_DOWN}

log = structlog.get_logger()

type EventSink = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class RunnerDeps:
    writer: Writer  # app_writer: records the run; never passed to the graph
    agent: AgentDeps  # what the graph gets: the reader session and the providers
    provider_modes: dict[str, str]
    on_event: EventSink | None = None  # live steps for the UI (SSE, T36)
    timeout_s: float = RUN_TIMEOUT_S


@dataclass(frozen=True)
class RunResult:
    run_id: UUID
    status: str
    result: dict[str, Any]


@cache
def _graph() -> Any:
    return build_graph()


async def run_case(
    case_id: int,
    deps: RunnerDeps,
    *,
    pinned_fee_txn_id: int | None = None,
    run_id: UUID | None = None,
    graph: Any = None,
) -> RunResult:
    """Run the graph for a case. The API passes a `run_id` it already created with
    `start_run`, so it can answer 202 with it before the run ends."""
    if run_id is None:
        run_id = await start_run(deps.writer, case_id)
    log.info("run_started", run_id=str(run_id), case_id=case_id)
    started = deps.agent.clock()
    agent = replace(deps.agent, deadline=started + deps.timeout_s)
    records: list[StepRecord] = []
    result: dict[str, Any] | None = None
    running_node: str | None = None

    try:
        async with asyncio.timeout(deps.timeout_s):
            async for mode, chunk in (graph or _graph()).astream(
                GraphState(case_id=case_id, run_id=run_id, pinned_fee_txn_id=pinned_fee_txn_id),
                context=agent,
                stream_mode=["updates", "custom"],
            ):
                if mode == "custom":
                    if chunk.get("state") == "started":
                        running_node = chunk["node"]
                    record = chunk.get("record")
                    if isinstance(record, StepRecord):
                        records.append(record)
                        await record_step(deps.writer, run_id, record)
                    await _emit(deps, {k: v for k, v in chunk.items() if k != "record"})
                elif mode == "updates" and "finalize" in chunk:
                    result = (chunk["finalize"] or {}).get("result")
    except TimeoutError:
        reason = TIMEOUT_REASON.get(running_node or "", ReasonCode.DATA_TIMEOUT)
        log.warning("run_timed_out", run_id=str(run_id), node=running_node)
        result = _incomplete(reason)
    except Exception:
        log.exception("run_failed", run_id=str(run_id), case_id=case_id)
        await fail_run(deps.writer, run_id=run_id, case_id=case_id)
        await _emit(deps, {"event": "done", "status": "failed"})
        raise

    result = result or _incomplete(None)
    totals = _totals(records, deps, round((deps.agent.clock() - started) * 1000))
    await finish_run(deps.writer, run_id=run_id, case_id=case_id, result=result, totals=totals)
    log.info("run_finished", run_id=str(run_id), status=result["status"])
    await _emit(deps, {"event": "done", "status": result["status"]})
    return RunResult(run_id=run_id, status=result["status"], result=result)


def _totals(records: list[StepRecord], deps: RunnerDeps, latency_ms: int) -> dict[str, Any]:
    metas = [r.meta for r in records if r.meta is not None]
    return {
        "total_latency_ms": latency_ms,
        "tokens_in": sum(m.tokens_in for m in metas),
        "tokens_out": sum(m.tokens_out for m in metas),
        "tokens_cached": sum(m.tokens_cached for m in metas),
        "cost_usd": sum((m.cost_usd for m in metas if m.cost_usd is not None), Decimal("0")),
        "prompt_versions": {r.node: r.prompt_version for r in records if r.prompt_version},
        "policy_version": deps.agent.policy.version,
        "provider_mode": dict(deps.provider_modes),
    }


def _incomplete(reason: ReasonCode | None) -> dict[str, Any]:
    """A result for a run that did not reach finalize: Luis decides."""
    return {
        "status": "needs_your_call",
        "reasons": [reason.value] if reason else [],
        "notes": [],
        "topic": None,
        "recommendation": {"action": "none", "amount": None, "fee_txn_id": None},
        "clear": False,
        "would_auto_approve": False,
    }


async def _emit(deps: RunnerDeps, event: dict[str, Any]) -> None:
    if deps.on_event is not None:
        await deps.on_event(event)
