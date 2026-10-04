"""The agent graph end to end on the seed, with in-process fake providers (D10: tests never use
replay files or live models). Each scenario asserts the status and what Luis would see."""

import json
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.agents.deps import AgentDeps
from backend.agents.graph import build_graph
from backend.agents.state import GraphState
from backend.agents.steps import StepRecord
from backend.policy.loader import load_clauses
from backend.providers.types import (
    CallMeta,
    ChoiceAnswer,
    Classification,
    NoulAnswer,
    ProviderUnavailable,
    Question,
)
from tests.integration.roles import TEST_AGENT_ROLE, role_url

SEEDED_SECRETS = ("Ana", "Torres", "884210", "884211")


class FakeClassifier:
    """Answers like Jev would, or fails like a provider that is down."""

    def __init__(self, answers: Mapping[str, ChoiceAnswer | NoulAnswer] | None) -> None:
        self.answers = answers
        self.states: list[Mapping[str, str]] = []

    async def classify(
        self,
        state: Mapping[str, str],
        questions: Sequence[Question],
        *,
        deadline: float | None = None,
    ) -> Classification:
        self.states.append(state)
        if self.answers is None:
            raise ProviderUnavailable("timeout")
        return Classification(
            answers=dict(self.answers),
            meta=CallMeta(
                provider="jev",
                model="jev-1.13.0",
                mode="live",
                latency_ms=200,
                tokens_in=760,
                tokens_out=0,
                cost_usd=Decimal("0.000032"),
                attempts=1,
            ),
        )


def jev_answers(intent: str = "fee_refund_request") -> dict[str, ChoiceAnswer | NoulAnswer]:
    return {
        "intent": ChoiceAnswer(choice=intent, probabilities={intent: 1.0}, confidence=1.0),
        "language": ChoiceAnswer(choice="en", probabilities={"en": 1.0}, confidence=1.0),
        "tone": ChoiceAnswer(choice="casual", probabilities={"casual": 0.9}, confidence=0.85),
        "manipulation": NoulAnswer(p_yes=0.04, label=False),
        "multiple_requests": NoulAnswer(p_yes=0.05, label=False),
    }


@pytest.fixture
def with_clauses(seeded: Engine, granted_roles: None) -> Iterator[Engine]:
    with seeded.begin() as connection:
        load_clauses(connection)
    yield seeded


@pytest.fixture
async def reader(
    with_clauses: Engine, test_database_url: URL
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(role_url(test_database_url, TEST_AGENT_ROLE))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def run(
    case_id: int, classifier: FakeClassifier, reader: async_sessionmaker[AsyncSession]
) -> tuple[dict[str, Any], list[StepRecord]]:
    graph = build_graph()
    final: dict[str, Any] = {}
    records: list[StepRecord] = []
    async for mode, chunk in graph.astream(
        GraphState(case_id=case_id, run_id=uuid4()),
        context=AgentDeps(reader=reader, classifier=classifier),
        stream_mode=["values", "custom"],
    ):
        if mode == "values":
            final = chunk
        elif chunk.get("state") in ("finished", "failed"):
            records.append(chunk["record"])
    return final, records


async def test_ana_is_ready_to_refund_with_a_template_reply(
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
    assert result["draft"]["source"] == "template"


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
