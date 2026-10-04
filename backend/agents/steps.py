"""How nodes are run and recorded, from outside the node code (SPEC-agent, "Runner").

Each node returns its state update plus a `StepReport`. The wrapper times it and emits two
custom stream events, `started` and then `finished` or `failed`; the second carries a
`StepRecord`, which the runner stores as an `agent_steps` row and strips before streaming to the
UI. The wrapper also gives read tools their one retry (core/config/tools.yaml).
"""

import asyncio
import datetime as dt
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from langgraph.runtime import Runtime
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.deps import AgentDeps
from backend.agents.state import GraphState
from backend.providers.types import CallMeta, ProviderUnavailable
from backend.tools.errors import ToolError, ToolTimeout
from backend.tools.queries import TOOL_RETRIES

type StepKind = Literal["rule", "jev", "llm", "tool"]


@dataclass(frozen=True)
class StepReport:
    kind: StepKind
    input_masked: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    meta: CallMeta | None = None
    prompt_version: str | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class StepRecord:
    node: str
    kind: StepKind
    status: Literal["finished", "failed"]
    started_at: dt.datetime
    latency_ms: int
    input_masked: dict[str, Any] | None
    output: dict[str, Any] | None
    meta: CallMeta | None
    prompt_version: str | None
    error_code: str | None


type NodeFn = Callable[[GraphState, AgentDeps], Awaitable[tuple[dict[str, Any], StepReport]]]


class GraphNode(Protocol):
    """What LangGraph calls: the run context arrives as the keyword argument `runtime`."""

    def __call__(
        self, state: GraphState, *, runtime: Runtime[AgentDeps]
    ) -> Awaitable[dict[str, Any]]: ...


def as_node(name: str, node: NodeFn) -> GraphNode:
    async def run(state: GraphState, *, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
        write = runtime.stream_writer
        started_at = dt.datetime.now(dt.UTC)  # for the record only; nothing decides on it
        started = time.perf_counter()
        write({"event": "step", "node": name, "state": "started"})
        update, report = await node(state, runtime.context)
        status: Literal["finished", "failed"] = "failed" if report.error_code else "finished"
        record = StepRecord(
            node=name,
            kind=report.kind,
            status=status,
            started_at=started_at,
            latency_ms=round((time.perf_counter() - started) * 1000),
            input_masked=report.input_masked,
            output=report.output,
            meta=report.meta,
            prompt_version=report.prompt_version,
            error_code=report.error_code,
        )
        write({"event": "step", "node": name, "state": status, "record": record})
        return update

    return run


async def bounded[T](deps: AgentDeps, call: Awaitable[T]) -> T:
    """A model call cut at the run's deadline, even when the provider doesn't watch it, so the
    node's fallback still runs inside the run (D-agent-6). The real adapters stop retrying at the
    deadline on their own; this also covers one that hangs."""
    if deps.model_deadline is None:
        return await call
    try:
        async with asyncio.timeout_at(deps.model_deadline):  # the loop's clock is monotonic
            return await call
    except TimeoutError:
        raise ProviderUnavailable("timeout") from None


async def run_tool[T](deps: AgentDeps, call: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """Run a read tool on a fresh agent_reader session, with one retry after a timeout or a
    database error, never starting an attempt after the run deadline."""
    attempt = 0
    while True:
        attempt += 1
        if deps.deadline is not None and deps.clock() >= deps.deadline:
            raise ToolTimeout
        try:
            async with deps.reader() as session:
                return await call(session)
        except ToolError as error:
            if error.reason == "not_found" or attempt > TOOL_RETRIES:
                raise
