"""The classifier comparison (SPEC-evals, "Classifier comparison"): a triage verdict is right
when it would route the case as the case expects."""

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from backend.agents.triage_rules import THRESHOLDS, Triage
from backend.policy.reasons import ReasonCode
from backend.providers.types import (
    CallMeta,
    Classification,
    Classifier,
    Question,
)
from evals.case import EvalCase, Expected
from evals.compare import compare, triage_is_right
from evals.meter import Asked, Call
from tests.integration.agents.fakes import FakeClassifier, jev_answers


def triage(*reasons: ReasonCode, topic: str = "fee_refund_request", language: str = "en") -> Triage:
    return Triage(
        about_fee=topic in ("fee_refund_request", "fee_question"),
        topic=topic,
        classifier_used="jev",
        intent_confidence=1.0,
        language=language,
        tone="casual",
        manipulation_p_yes=0.04,
        reasons=reasons,
    )


READY = Expected(status="ready_to_refund")
ATTACK = Expected(status="needs_your_call", reasons_include=(ReasonCode.MANIPULATION,))


def test_a_case_that_needs_no_one_is_right_only_without_triage_codes() -> None:
    assert triage_is_right(READY, triage())
    assert not triage_is_right(READY, triage(ReasonCode.MANIPULATION))


def test_a_note_is_not_a_routing_code() -> None:
    assert triage_is_right(READY, triage(ReasonCode.CLASSIFIED_WITH_BACKUP))


def test_a_case_for_luis_needs_its_codes_and_may_get_more() -> None:
    assert triage_is_right(ATTACK, triage(ReasonCode.MANIPULATION, ReasonCode.MULTIPLE_REQUESTS))
    assert not triage_is_right(ATTACK, triage())


def test_topic_and_language_count_when_the_case_states_them() -> None:
    card = Expected(
        status="not_about_fee", topic="card_issue", reasons_include=(ReasonCode.NOT_FEE_REQUEST,)
    )
    spanish = Expected(status="ready_to_refund", language="es")

    assert triage_is_right(card, triage(ReasonCode.NOT_FEE_REQUEST, topic="card_issue"))
    assert not triage_is_right(card, triage(ReasonCode.NOT_FEE_REQUEST, topic="other"))
    assert not triage_is_right(spanish, triage(language="en"))


# --- compare() ---

STATE = {"subject": "Overdraft fee", "message": "My paycheck came the same day."}
CASE = EvalCase.model_validate(
    {"id": "a", "kind": "refund", "source": "seed", "conversation_id": 5012, "expected": {}}
)


def triage_call(case_id: str, provider: str = "jev") -> Call:
    meta = CallMeta(
        provider=provider,
        model="jev-1.13.0",
        mode="replay",
        latency_ms=300,
        tokens_in=760,
        tokens_out=0,
        cost_usd=Decimal("0.000032"),
        attempts=1,
    )
    answer = Classification(answers=jev_answers(), meta=meta)
    return Call(case_id, "triage", meta, Asked(STATE, [], "triage-v2"), answer)


class FakeLuna:
    """Answers with labels only, like the backup."""

    def __init__(self) -> None:
        self.asked: list[tuple[Mapping[str, str], str | None]] = []

    async def classify(
        self,
        state: Mapping[str, str],
        questions: Sequence[Question],
        *,
        prompt_version: str | None = None,
        deadline: float | None = None,
    ) -> Classification:
        self.asked.append((state, prompt_version))
        answers: dict[str, Any] = jev_answers()
        return Classification(
            answers=answers,
            meta=CallMeta(
                provider="openai",
                model="gpt-6-luna",
                mode="replay",
                latency_ms=900,
                tokens_in=1000,
                tokens_out=40,
                cost_usd=Decimal("0.00012"),
                attempts=1,
            ),
        )


async def test_the_backup_is_asked_exactly_what_jev_was_asked() -> None:
    luna = FakeLuna()

    comparison = await compare([CASE], [triage_call("a")], lambda case: luna, THRESHOLDS)

    assert luna.asked == [(STATE, "triage-v2")]
    jev, backup, sol = comparison.lines
    assert (jev.name, jev.cases, jev.right, list(jev.latencies_ms)) == ("jev", 1, 1, [300])
    assert (backup.name, backup.cases, backup.right, list(backup.latencies_ms)) == (
        "luna",
        1,
        1,
        [900],
    )
    # Sol: Luna's 1,000 tokens in and 40 out at $2.00 and $10.00 per million.
    assert (sol.estimate, sol.right, list(sol.costs)) == (True, None, [Decimal("0.0024")])


async def test_a_backup_that_cannot_answer_counts_as_wrong() -> None:
    down: Classifier = FakeClassifier(None)

    comparison = await compare([CASE], [triage_call("a")], lambda case: down, THRESHOLDS)

    backup = comparison.lines[1]
    assert (backup.cases, backup.right, list(backup.latencies_ms)) == (1, 0, [])


async def test_only_triage_jev_answered_in_a_counted_case_is_compared() -> None:
    luna = FakeLuna()
    calls = [triage_call("a", provider="openai"), triage_call("not-counted")]

    comparison = await compare([CASE], calls, lambda case: luna, THRESHOLDS)

    assert luna.asked == []
    assert comparison.lines[0].cases == 0
