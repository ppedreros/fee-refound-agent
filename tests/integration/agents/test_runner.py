"""The runner and recorder (SPEC-agent, "Runner and recording"): persistence, totals, the stream,
read-only nodes, and interrupted runs."""

import json
from decimal import Decimal
from typing import Any

import pytest
from langgraph.graph import END, START, StateGraph
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.agents.deps import AgentDeps
from backend.agents.runner import RunInProgress, RunnerDeps, reset_interrupted_runs, run_case
from backend.agents.state import GraphState
from backend.agents.steps import StepReport, as_node
from tests.integration.agents.fakes import FakeClassifier, jev_answers

SECRETS = ("Ana", "Torres", "884210", "884211")
GRAPH_ORDER_AFTER_READS = [
    "identify_fee",
    "run_checks",
    "decide",
    "find_policy",
    "draft",
    "finalize",
]


def runner_deps(
    reader: async_sessionmaker[AsyncSession],
    writer: async_sessionmaker[AsyncSession],
    events: list[dict[str, Any]] | None = None,
) -> RunnerDeps:
    async def collect(event: dict[str, Any]) -> None:
        if events is not None:
            events.append(event)

    return RunnerDeps(
        writer=writer,
        agent=AgentDeps(reader=reader, classifier=FakeClassifier(jev_answers())),
        provider_modes={"jev": "live", "openai": "replay"},
        on_event=collect,
    )


def rows(engine: Engine, query: str) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        return [dict(row._mapping) for row in connection.execute(text(query))]


async def test_a_run_writes_one_run_row_and_one_step_row_per_node(
    reader: async_sessionmaker[AsyncSession],
    writer: async_sessionmaker[AsyncSession],
    with_clauses: Engine,
) -> None:
    result = await run_case(5012, runner_deps(reader, writer))

    (run,) = rows(with_clauses, "SELECT * FROM agent_runs")
    steps = rows(with_clauses, "SELECT * FROM agent_steps ORDER BY id")
    assert result.status == "ready_to_refund"
    assert run["id"] == result.run_id
    assert (run["status"], run["outcome"]) == ("completed", "ready_to_refund")
    assert run["reason_codes"] == []
    assert run["classifier_used"] == "jev"
    assert run["would_auto_approve"] is True
    assert run["provider_mode"] == {"jev": "live", "openai": "replay"}
    assert run["prompt_versions"] == {"triage": "triage-v1"}
    assert run["policy_version"]
    assert run["result"]["recommendation"]["amount"] == "35.00"
    assert len(steps) == 11
    assert all(step["latency_ms"] >= 0 and step["status"] == "finished" for step in steps)


async def test_the_run_totals_add_up_from_its_steps(
    reader: async_sessionmaker[AsyncSession],
    writer: async_sessionmaker[AsyncSession],
    with_clauses: Engine,
) -> None:
    await run_case(5012, runner_deps(reader, writer))

    (run,) = rows(with_clauses, "SELECT * FROM agent_runs")
    steps = rows(with_clauses, "SELECT * FROM agent_steps")
    (triage,) = [s for s in steps if s["node"] == "triage"]
    assert (triage["kind"], triage["model"], triage["prompt_version"]) == (
        "jev",
        "jev-1.13.0",
        "triage-v1",
    )
    assert (triage["tokens_in"], triage["cost_usd"], triage["attempts"]) == (
        760,
        Decimal("0.000032"),
        1,
    )
    assert run["tokens_in"] == sum(s["tokens_in"] or 0 for s in steps)
    assert run["cost_usd"] == sum((s["cost_usd"] or Decimal(0) for s in steps), Decimal(0))
    assert run["total_latency_ms"] >= max(s["latency_ms"] for s in steps)


async def test_the_case_row_follows_the_run(
    reader: async_sessionmaker[AsyncSession],
    writer: async_sessionmaker[AsyncSession],
    with_clauses: Engine,
) -> None:
    result = await run_case(5012, runner_deps(reader, writer))

    (case,) = rows(with_clauses, "SELECT * FROM cases")
    assert (case["status"], case["topic"]) == ("ready_to_refund", "fee_refund_request")
    assert case["latest_run_id"] == result.run_id
    assert case["row_version"] >= 2  # checking, then the outcome


async def test_no_stored_step_input_holds_a_name_or_an_account_number(
    reader: async_sessionmaker[AsyncSession],
    writer: async_sessionmaker[AsyncSession],
    with_clauses: Engine,
) -> None:
    await run_case(5012, runner_deps(reader, writer))

    for step in rows(with_clauses, "SELECT node, input_masked, output FROM agent_steps"):
        stored = json.dumps([step["input_masked"], step["output"]])
        assert not any(secret in stored for secret in SECRETS), step["node"]


async def test_the_stream_shows_each_node_starting_and_finishing_then_done(
    reader: async_sessionmaker[AsyncSession],
    writer: async_sessionmaker[AsyncSession],
) -> None:
    events: list[dict[str, Any]] = []

    await run_case(5012, runner_deps(reader, writer, events))

    assert all("record" not in event for event in events)  # never streamed to the UI
    finished = [e["node"] for e in events if e.get("state") == "finished"]
    assert finished[:2] == ["load_conversation", "triage"]
    assert finished[-len(GRAPH_ORDER_AFTER_READS) :] == GRAPH_ORDER_AFTER_READS
    assert sum(1 for e in events if e.get("state") == "started") == len(finished) == 11
    assert events[-1] == {"event": "done", "status": "ready_to_refund"}


async def test_a_second_run_while_one_is_running_is_refused(
    reader: async_sessionmaker[AsyncSession],
    writer: async_sessionmaker[AsyncSession],
    with_clauses: Engine,
) -> None:
    with with_clauses.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO cases (conversation_id, status) VALUES (5012, 'checking');"
                "INSERT INTO agent_runs (case_id, status) VALUES (5012, 'running')"
            )
        )
    (running,) = rows(with_clauses, "SELECT id FROM agent_runs")

    with pytest.raises(RunInProgress) as error:
        await run_case(5012, runner_deps(reader, writer))

    assert error.value.run_id == running["id"]


async def test_a_node_trying_to_write_is_refused_and_the_recorder_still_writes(
    reader: async_sessionmaker[AsyncSession],
    writer: async_sessionmaker[AsyncSession],
    with_clauses: Engine,
) -> None:
    async def sneaky(state: GraphState, deps: AgentDeps) -> tuple[dict[str, Any], StepReport]:
        try:
            async with deps.reader() as session:
                await session.execute(
                    text("INSERT INTO audit_events (actor, action) VALUES ('agent', 'refund')")
                )
                await session.commit()
        except DBAPIError as error:
            return {}, StepReport(kind="tool", error_code=type(error.orig).__name__)
        return {}, StepReport(kind="tool", output={"wrote": True})

    graph = StateGraph(GraphState, context_schema=AgentDeps)
    graph.add_node("sneaky", as_node("sneaky", sneaky))
    graph.add_edge(START, "sneaky")
    graph.add_edge("sneaky", END)

    await run_case(5012, runner_deps(reader, writer), graph=graph.compile())

    (step,) = rows(with_clauses, "SELECT status, error_code FROM agent_steps")
    assert step["status"] == "failed"
    assert step["error_code"] in ("InsufficientPrivilege", "ReadOnlySqlTransaction")
    assert rows(with_clauses, "SELECT * FROM audit_events") == []


async def test_runs_left_running_are_interrupted_at_startup(
    writer: async_sessionmaker[AsyncSession], with_clauses: Engine
) -> None:
    with with_clauses.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO cases (conversation_id, status) VALUES (5012, 'checking');"
                "INSERT INTO agent_runs (case_id, status) VALUES (5012, 'running')"
            )
        )

    count = await reset_interrupted_runs(writer)

    (run,) = rows(with_clauses, "SELECT status, finished_at FROM agent_runs")
    (case,) = rows(with_clauses, "SELECT status FROM cases")
    assert count == 1
    assert run["status"] == "interrupted" and run["finished_at"] is not None
    assert case["status"] == "not_checked"
