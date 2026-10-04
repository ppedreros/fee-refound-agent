"""Every fallback in SPEC-agent AC4, on the seed, with in-process fakes (D10: tests never use
replay files or live models). Falling back is never a guess: the case says what happened."""

import asyncio
import datetime as dt
import time
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.agents.deps import AgentDeps
from backend.agents.draft_postcheck import check_draft
from backend.agents.graph import build_graph
from backend.agents.runner import RunnerDeps, run_case, timeout_reason
from backend.agents.state import GraphState
from backend.agents.steps import StepRecord
from backend.providers.chain import ClassifierChain
from backend.providers.replay import ReplayClassifier, ReplayDrafter, ReplayStore
from backend.providers.types import (
    CallMeta,
    ChoiceAnswer,
    Classification,
    Classifier,
    NoulAnswer,
    Question,
)
from backend.tools import queries
from backend.tools.models import Transaction
from tests.integration.agents.fakes import FakeClassifier, FakeDrafter, jev_answers

MEMBER_TEXT = ("paycheck came the same day", "Can you refund this", "Overdraft fee")


class FakeLuna:
    """Answers like the backup would: labels only, no calibrated numbers."""

    async def classify(
        self,
        state: Any,
        questions: Any,
        *,
        prompt_version: str | None = None,
        deadline: float | None = None,
    ) -> Any:
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
    case_id: int,
    classifier: Classifier,
    reader: async_sessionmaker[AsyncSession],
    drafter: FakeDrafter | None = None,
) -> tuple[dict[str, Any], list[StepRecord]]:
    graph = build_graph()
    final: dict[str, Any] = {}
    records: list[StepRecord] = []
    async for mode, chunk in graph.astream(
        GraphState(case_id=case_id, run_id=uuid4()),
        context=AgentDeps(reader=reader, classifier=classifier, drafter=drafter or FakeDrafter()),
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


# --- Sol (D-agent-7: a drafter failure is a reason, and Luis can still approve in one click) ---


async def test_sol_down_gives_the_template_and_needs_your_call_keeping_the_recommendation(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    classifier = FakeClassifier(jev_answers())

    final, records = await run(5012, classifier, reader, FakeDrafter([None]))
    result = final["result"]

    assert result["status"] == "needs_your_call"
    assert result["reasons"] == ["drafter_down"]
    assert result["recommendation"] == {"action": "refund", "amount": "35.00", "fee_txn_id": 88002}
    assert result["draft"]["source"] == "template"
    assert "{{first_name}}" in result["draft"]["text"]
    draft = next(record for record in records if record.node == "draft")
    assert (draft.status, draft.error_code) == ("failed", "timeout")


async def test_a_reply_that_fails_the_post_check_twice_falls_back_to_the_template(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    bad = "Hi {{first_name}}, we refunded $500 to you."
    drafter = FakeDrafter([bad, bad])

    final, records = await run(5012, FakeClassifier(jev_answers()), reader, drafter)

    assert final["result"]["reasons"] == ["drafter_down"]
    assert final["result"]["draft"]["source"] == "template"
    assert "$500" not in str(final["result"])
    draft = next(record for record in records if record.node == "draft")
    assert draft.error_code == "postcheck_failed"
    assert draft.output is not None and draft.output["postcheck"] == ["amount"]
    assert draft.meta is not None and draft.meta.attempts == 2  # both calls are in the trace


async def test_one_failed_post_check_is_retried_once(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    drafter = FakeDrafter(["Hi Ana, we refunded the fee."])  # no placeholder, then a good one

    final, _ = await run(5012, FakeClassifier(jev_answers()), reader, drafter)

    assert final["result"]["status"] == "ready_to_refund"
    assert final["result"]["draft"]["source"] == "model"
    assert len(drafter.payloads) == 2


async def test_sol_sees_facts_only_never_the_members_message(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    drafter = FakeDrafter()

    final, records = await run(5012, FakeClassifier(jev_answers()), reader, drafter)

    (payload,) = drafter.payloads
    assert payload.model_dump(mode="json") == {
        "language": "en",
        "tone": "casual",
        "outcome": "refund",
        "amount": "35.00",
        "fee_date": "2026-09-14",
        "fee_type": "Courtesy Pay",
        "sub_account_name": "Everyday Checking",
        "facts": ["The paycheck arrived the same day and the bill posted before it."],
        "policy_clause": None,
        "first_name": "{{first_name}}",
    }
    llm_steps = [record for record in records if record.kind == "llm"]
    assert [record.node for record in llm_steps] == ["draft"]
    for record in llm_steps:
        assert not any(text in str(record.input_masked) for text in MEMBER_TEXT)
    assert final["result"]["draft"]["source"] == "model"


# --- Data and the run itself ---


async def test_a_tool_timeout_is_data_timeout_and_luis_decides(
    reader: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    @queries.read_tool  # the real timeout path...
    async def slow(
        session: AsyncSession, member_id: int, start: dt.date, end: dt.date
    ) -> list[Transaction]:
        await asyncio.sleep(1)
        return []

    async def stuck(
        session: AsyncSession, member_id: int, start: dt.date, end: dt.date
    ) -> list[Transaction]:
        # ...made shorter for this one read only, so the other reads keep their own timeout
        normal = queries.TOOL_TIMEOUT_S
        monkeypatch.setattr(queries, "TOOL_TIMEOUT_S", 0.05)
        try:
            return await slow(session, member_id, start, end)
        finally:
            monkeypatch.setattr(queries, "TOOL_TIMEOUT_S", normal)

    monkeypatch.setattr(queries, "list_transactions", stuck)

    final, records = await run(5012, FakeClassifier(jev_answers()), reader)
    result = final["result"]

    assert result["status"] == "needs_your_call"
    assert result["reasons"] == ["data_timeout"]
    assert result["recommendation"]["action"] == "none"  # no usable data, no guess
    load = next(record for record in records if record.node == "load_transactions")
    assert (load.status, load.error_code) == ("failed", "timeout")


class HangingClassifier:
    """A classifier that never answers, so only the run timeout can end the wait."""

    async def classify(
        self,
        state: Mapping[str, str],
        questions: Sequence[Question],
        *,
        prompt_version: str | None = None,
        deadline: float | None = None,
    ) -> Classification:
        await asyncio.sleep(60)
        raise AssertionError("the run timeout should have fired")


class HangingDrafter:
    """A Sol that never answers and ignores the deadline it is given."""

    async def draft(
        self,
        payload: Any,
        *,
        instructions: str,
        prompt_version: str | None = None,
        deadline: float | None = None,
    ) -> Any:
        await asyncio.sleep(60)
        raise AssertionError("the deadline should have cut this call")


def runner_deps(
    reader: async_sessionmaker[AsyncSession],
    writer: async_sessionmaker[AsyncSession],
    *,
    classifier: Classifier | None = None,
    drafter: Any = None,
    timeout_s: float = 3.0,
    reserve_s: float = 2.0,
) -> RunnerDeps:
    return RunnerDeps(
        writer=writer,
        agent=AgentDeps(
            reader=reader,
            classifier=classifier or FakeClassifier(jev_answers()),
            drafter=drafter or FakeDrafter(),
        ),
        provider_modes={"jev": "live", "openai": "live"},
        timeout_s=timeout_s,  # 45 s in the shipped config
        reserve_s=reserve_s,  # 3 s in the shipped config
    )


async def test_a_hanging_classifier_is_cut_at_the_deadline_and_the_case_is_still_prepared(
    reader: async_sessionmaker[AsyncSession], writer: async_sessionmaker[AsyncSession]
) -> None:
    started = time.monotonic()

    result = await run_case(5012, runner_deps(reader, writer, classifier=HangingClassifier()))

    assert time.monotonic() - started < 3.0  # inside the run timeout, not at it
    assert result.status == "needs_your_call"
    assert result.result["reasons"] == ["classifier_down"]
    assert result.result["recommendation"]["action"] == "refund"
    assert result.result["evidence"]["fee_day"]  # the evidence is still there


async def test_a_hanging_sol_falls_back_to_the_template_inside_the_run(
    reader: async_sessionmaker[AsyncSession], writer: async_sessionmaker[AsyncSession]
) -> None:
    started = time.monotonic()

    result = await run_case(5012, runner_deps(reader, writer, drafter=HangingDrafter()))

    assert time.monotonic() - started < 3.0
    assert result.result["reasons"] == ["drafter_down"]
    assert result.result["draft"]["source"] == "template"
    assert result.result["recommendation"]["action"] == "refund"  # Luis can still approve


async def test_the_run_timeout_is_the_backstop_with_the_stalled_steps_reason(
    reader: async_sessionmaker[AsyncSession],
    writer: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def stuck(session: AsyncSession, conversation_id: int) -> Any:
        await asyncio.sleep(60)  # a read that ignores every timeout

    monkeypatch.setattr(queries, "get_conversation", stuck)

    result = await run_case(5012, runner_deps(reader, writer, timeout_s=0.5, reserve_s=0.1))

    assert result.status == "needs_your_call"
    assert result.result["reasons"] == ["data_timeout"]  # it stalled in a read


@pytest.mark.parametrize(
    ("node", "reason"),
    [("triage", "classifier_down"), ("draft", "drafter_down"), ("load_accounts", "data_timeout")],
)
def test_each_stalled_step_has_its_own_reason(node: str, reason: str) -> None:
    assert timeout_reason(node) == reason


@pytest.mark.parametrize(
    ("language", "opening", "reason_words"),
    [
        ("en", "Hi {{first_name}},", "up to 3 fee refunds in any 12-month period"),
        (
            "es",
            "Hola {{first_name}},",
            "hasta 3 reembolsos de cargos en cualquier periodo de 12 meses",
        ),
    ],
)
async def test_sol_down_on_a_decline_gives_the_decline_template_in_the_members_language(
    reader: async_sessionmaker[AsyncSession], language: str, opening: str, reason_words: str
) -> None:
    classifier = FakeClassifier(jev_answers(language=language))

    final, _ = await run(5106, classifier, reader, FakeDrafter([None]))
    result = final["result"]

    assert result["status"] == "needs_your_call"
    assert result["reasons"] == ["yearly_limit", "drafter_down"]
    assert result["recommendation"]["action"] == "no_refund"
    draft = result["draft"]
    assert draft["source"] == "template"
    assert draft["text"].startswith(opening)
    assert reason_words in draft["text"]
    assert check_draft(draft["text"], amount=Decimal("35.00")) == []


# --- Data that doesn't add up, and a replay with nothing recorded (scenarios 16 and 18) ---


async def test_balances_that_dont_add_up_are_data_mismatch_and_no_recommendation(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    final, _ = await run(5116, FakeClassifier(jev_answers()), reader)
    result = final["result"]

    assert result["status"] == "needs_your_call"
    assert result["reasons"] == ["data_mismatch"]
    assert result["recommendation"]["action"] == "none"


async def test_in_replay_with_nothing_recorded_the_case_falls_back_with_its_evidence(
    reader: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    store = ReplayStore(tmp_path)  # scenario 18 is never recorded
    chain = ClassifierChain(
        ReplayClassifier(store, provider="jev", model="jev-1.13.0"),
        ReplayClassifier(store, provider="openai", model="gpt-6-luna"),
    )
    deps = AgentDeps(
        reader=reader,
        classifier=chain,
        drafter=ReplayDrafter(store, model="gpt-6.1-sol"),
        chooser=chain.primary,
    )

    final = await build_graph().ainvoke(GraphState(case_id=5118, run_id=uuid4()), context=deps)
    result = final["result"]

    assert result["status"] == "needs_your_call"
    assert result["reasons"] == ["classifier_down", "drafter_down"]
    assert result["evidence"]["fee_day"]
    assert result["recommendation"]["action"] == "refund"
    assert result["draft"]["source"] == "template"
