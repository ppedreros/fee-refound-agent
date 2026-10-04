"""In-process fake providers for the agent tests (D10: tests never use replay files or live
models)."""

from collections.abc import Mapping, Sequence
from decimal import Decimal

from backend.policy.reasons import format_money
from backend.providers.types import (
    CallMeta,
    ChoiceAnswer,
    ChoiceQuestion,
    Classification,
    Draft,
    DrafterUnavailable,
    DraftInput,
    NoulAnswer,
    ProviderUnavailable,
    Question,
)


class FakeClassifier:
    """Answers like Jev would, or fails like a provider that is down (D10: tests use fakes)."""

    def __init__(self, answers: Mapping[str, ChoiceAnswer | NoulAnswer] | None) -> None:
        self.answers = answers
        self.states: list[Mapping[str, str]] = []

    async def classify(
        self,
        state: Mapping[str, str],
        questions: Sequence[Question],
        *,
        prompt_version: str | None = None,  # part of the replay key
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


def good_reply(payload: DraftInput) -> str:
    """What Sol would write: the placeholder, the decided amount, nothing else."""
    money = format_money(Decimal(payload.amount))
    return (
        "Hi {{first_name}}, thanks for reaching out. We've refunded the "
        f"{money} {payload.fee_type} fee to your {payload.sub_account_name} account."
    )


class FakeDrafter:
    """Writes like Sol would. Each entry of `replies` is one call: None means Sol is down, a
    string is that reply, and `good_reply` is used once the list runs out."""

    def __init__(self, replies: Sequence[str | None] = ()) -> None:
        self.replies = list(replies)
        self.payloads: list[DraftInput] = []

    async def draft(
        self,
        payload: DraftInput,
        *,
        instructions: str,
        prompt_version: str | None = None,
        deadline: float | None = None,
    ) -> Draft:
        self.payloads.append(payload)
        reply = self.replies.pop(0) if self.replies else good_reply(payload)
        if reply is None:
            raise DrafterUnavailable("timeout")
        return Draft(
            reply=reply,
            meta=CallMeta(
                provider="openai",
                model="gpt-6.1-sol",
                mode="live",
                latency_ms=900,
                tokens_in=1300,
                tokens_out=120,
                tokens_cached=1100,
                cost_usd=Decimal("0.001710"),
                attempts=1,
            ),
        )


class FakeRanker:
    """Answers the clause choice like Jev would: `choose` (a clause id, one of the options) with
    `confidence`, or fails like a provider that is down when `choose` is None."""

    def __init__(self, choose: str | None, confidence: float = 0.95) -> None:
        self.choose = choose
        self.confidence = confidence
        self.states: list[Mapping[str, str]] = []
        self.options: list[list[str]] = []

    async def classify(
        self,
        state: Mapping[str, str],
        questions: Sequence[Question],
        *,
        prompt_version: str | None = None,
        deadline: float | None = None,
    ) -> Classification:
        (question,) = questions
        assert isinstance(question, ChoiceQuestion)
        self.states.append(state)
        self.options.append([option.key for option in question.options])
        if self.choose is None:
            raise ProviderUnavailable("timeout")
        return Classification(
            answers={
                question.key: ChoiceAnswer(
                    choice=self.choose,
                    probabilities={self.choose: self.confidence},
                    confidence=self.confidence,
                )
            },
            meta=CallMeta(
                provider="jev",
                model="jev-1.13.0",
                mode="live",
                latency_ms=250,
                tokens_in=600,
                tokens_out=0,
                cost_usd=Decimal("0.000025"),
                attempts=1,
            ),
        )
