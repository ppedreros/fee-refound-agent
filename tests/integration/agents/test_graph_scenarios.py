"""The agent graph end to end on the seed, with in-process fake providers (D10: tests never use
replay files or live models). Each scenario asserts the status and what Luis would see."""

import json
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.agents.deps import AgentDeps
from backend.agents.graph import build_graph
from backend.agents.state import GraphState
from backend.agents.steps import StepRecord
from tests.integration.agents.fakes import FakeClassifier, FakeDrafter, jev_answers

SEEDED_SECRETS = ("Ana", "Torres", "884210", "884211")


async def run(
    case_id: int, classifier: FakeClassifier, reader: async_sessionmaker[AsyncSession]
) -> tuple[dict[str, Any], list[StepRecord]]:
    graph = build_graph()
    final: dict[str, Any] = {}
    records: list[StepRecord] = []
    async for mode, chunk in graph.astream(
        GraphState(case_id=case_id, run_id=uuid4()),
        context=AgentDeps(reader=reader, classifier=classifier, drafter=FakeDrafter()),
        stream_mode=["values", "custom"],
    ):
        if mode == "values":
            final = chunk
        elif chunk.get("state") in ("finished", "failed"):
            records.append(chunk["record"])
    return final, records


async def test_ana_is_ready_to_refund_with_a_drafted_reply(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    final, _ = await run(5012, FakeClassifier(jev_answers()), reader)
    result = final["result"]

    assert result["status"] == "ready_to_refund"
    assert result["recommendation"] == {"action": "refund", "amount": "35.00", "fee_txn_id": 88002}
    assert result["clear"] is True
    assert result["would_auto_approve"] is True
    assert result["clause"]["id"] == "fee-refund-policy#4"
    assert result["clause"]["found_by"] == "rule_fallback"
    assert "{{first_name}}" in result["draft"]["text"]
    assert "$35" in result["draft"]["text"]
    assert result["draft"]["source"] == "model"


async def test_ana_runs_every_node_once_and_the_reads_in_parallel(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    _, records = await run(5012, FakeClassifier(jev_answers()), reader)

    nodes = [record.node for record in records]
    assert nodes[:2] == ["load_conversation", "triage"]
    assert set(nodes[2:5]) == {"load_accounts", "load_transactions", "load_refund_history"}
    assert nodes[5:] == [
        "identify_fee",
        "run_checks",
        "decide",
        "find_policy",
        "draft",
        "finalize",
    ]
    assert all(record.status == "finished" for record in records)


async def test_no_step_input_holds_a_name_or_an_account_number(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    classifier = FakeClassifier(jev_answers())

    _, records = await run(5012, classifier, reader)

    for record in records:
        text = json.dumps(record.input_masked, default=str)
        assert not any(secret in text for secret in SEEDED_SECRETS), record.node
    assert classifier.states == [
        {
            "subject": "Overdraft fee",
            "message": "My paycheck came the same day. Can you refund this?",
        }
    ]


async def test_a_message_that_is_not_about_a_fee_loads_no_balances(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    final, records = await run(5011, FakeClassifier(jev_answers("card_issue")), reader)

    assert final["result"]["status"] == "not_about_fee"
    assert final["result"]["topic"] == "card_issue"
    assert [r.node for r in records] == ["load_conversation", "triage", "finalize"]


async def test_with_every_classifier_down_the_case_is_still_prepared(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    final, records = await run(5012, FakeClassifier(None), reader)
    result = final["result"]

    assert result["status"] == "needs_your_call"
    assert result["reasons"] == ["classifier_down"]
    assert result["recommendation"]["action"] == "refund"
    assert next(r for r in records if r.node == "triage").status == "failed"
