"""In-process fake providers for the agent tests (D10: tests never use replay files or live
models)."""

from collections.abc import Mapping, Sequence
from decimal import Decimal

from backend.providers.types import (
    CallMeta,
    ChoiceAnswer,
    Classification,
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
