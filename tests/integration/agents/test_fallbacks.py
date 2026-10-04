"""Every fallback in SPEC-agent AC4, on the seed, with in-process fakes (D10: tests never use
replay files or live models). Falling back is never a guess: the case says what happened."""

from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.agents.deps import AgentDeps
from backend.agents.graph import build_graph
from backend.agents.state import GraphState
from backend.agents.steps import StepRecord
from backend.providers.chain import ClassifierChain
from backend.providers.types import (
    CallMeta,
    ChoiceAnswer,
    Classification,
    Classifier,
    NoulAnswer,
)
from tests.integration.agents.fakes import FakeClassifier, jev_answers


class FakeLuna:
    """Answers like the backup would: labels only, no calibrated numbers."""

    async def classify(self, state: Any, questions: Any, *, deadline: float | None = None) -> Any:
        return Classification(
            answers={
                "intent": ChoiceAnswer(choice="fee_refund_request"),
                "language": ChoiceAnswer(choice="en"),
                "tone": ChoiceAnswer(choice="casual"),
                "manipulation": NoulAnswer(p_yes=None, label=False),
                "multiple_requests": NoulAnswer(p_yes=None, label=False),
            },
            meta=CallMeta(
                provider="openai",
                model="gpt-6-luna",
                mode="live",
                latency_ms=600,
                tokens_in=420,
                tokens_out=30,
                cost_usd=Decimal("0.000057"),
                attempts=1,
            ),
        )


async def run(
    case_id: int, classifier: Classifier, reader: async_sessionmaker[AsyncSession]
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


async def test_jev_down_luna_answers_and_the_note_changes_nothing_but_clear(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    chain = ClassifierChain(FakeClassifier(None), FakeLuna())

    final, records = await run(5012, chain, reader)
    result = final["result"]

    assert result["status"] == "ready_to_refund"  # the note never changes the status
    assert result["notes"] == ["classified_with_backup"]
    assert result["classifier_used"] == "backup"
    assert (result["clear"], result["would_auto_approve"]) == (False, False)
    triage = next(record for record in records if record.node == "triage")
    assert triage.status == "finished"
    assert triage.kind == "llm"
    assert triage.meta is not None
    assert (triage.meta.provider, triage.meta.model, triage.meta.attempts) == (
        "openai",
        "gpt-6-luna",
        2,
    )
    assert triage.output is not None
    assert triage.output["fallback"] == {"from": "jev", "reason": "timeout"}


async def test_both_classifiers_down_still_prepares_the_evidence_and_the_recommendation(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    chain = ClassifierChain(FakeClassifier(None), FakeClassifier(None))

    final, records = await run(5012, chain, reader)
    result = final["result"]

    assert result["status"] == "needs_your_call"
    assert result["reasons"] == ["classifier_down"]
    assert result["recommendation"] == {"action": "refund", "amount": "35.00", "fee_txn_id": 88002}
    assert [row["id"] for row in result["evidence"]["fee_day"]] == [88001, 88002, 88003]
    triage = next(record for record in records if record.node == "triage")
    assert triage.status == "failed"
    assert triage.output is not None
    assert triage.output["fallback"] == {"from": "jev", "reason": "timeout"}


async def test_jev_answering_needs_no_backup(reader: async_sessionmaker[AsyncSession]) -> None:
    final, records = await run(
        5012, ClassifierChain(FakeClassifier(jev_answers()), FakeLuna()), reader
    )

    assert final["result"]["notes"] == []
    triage = next(record for record in records if record.node == "triage")
    assert triage.output is not None
    assert "fallback" not in triage.output
