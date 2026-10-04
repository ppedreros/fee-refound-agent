"""ClassifierChain: Jev first, Luna when Jev is unavailable, ClassifierUnavailable only after both
have failed (SPEC-providers; D-agent-7)."""

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Literal

import httpx2
import pytest
from typesafe_sdk import AsyncTypeSafeClient

from backend.agents.prompts import load_questions
from backend.providers.chain import ClassifierChain, ClassifierUnavailable
from backend.providers.config import CallPolicy, ProviderConfig
from backend.providers.jev import JevClassifier
from backend.providers.openai_classifier import OpenAIClassifier
from backend.providers.types import (
    CallMeta,
    ChoiceAnswer,
    Classification,
    ProviderUnavailable,
    Question,
    UnavailableReason,
)
from tests.unit.providers.openai_fakes import Recorder, client_for, no_sleep, response_body

QUESTIONS = load_questions("triage-v1").questions
STATE = {"subject": "Overdraft fee", "message": "My paycheck came the same day."}


class Stub:
    """A classifier that answers, or fails after a number of attempts."""

    def __init__(
        self,
        provider: Literal["jev", "openai"],
        *,
        fails: UnavailableReason | None = None,
        attempts: int = 1,
    ) -> None:
        self.provider: Literal["jev", "openai"] = provider
        self.fails = fails
        self.attempts = attempts
        self.deadlines: list[float | None] = []

    async def classify(
        self,
        state: Mapping[str, str],
        questions: Sequence[Question],
        *,
        prompt_version: str | None = None,  # part of the replay key
        deadline: float | None = None,
    ) -> Classification:
        self.deadlines.append(deadline)
        if self.fails is not None:
            error = ProviderUnavailable(self.fails)
            error.attempts = self.attempts
            raise error
        return Classification(
            answers={"intent": ChoiceAnswer(choice="fee_refund_request")},
            meta=CallMeta(
                provider=self.provider,
                model="jev-1.13.0" if self.provider == "jev" else "gpt-6-luna",
                mode="live",
                latency_ms=100,
                tokens_in=300,
                tokens_out=20,
                cost_usd=Decimal("0.000040"),
                attempts=self.attempts,
            ),
        )


async def test_jev_answers_and_luna_is_never_asked() -> None:
    jev, luna = Stub("jev"), Stub("openai")

    result = await ClassifierChain(jev, luna).classify(STATE, QUESTIONS, deadline=99.0)

    assert result.meta.provider == "jev"
    assert result.fallback_reason is None
    assert (jev.deadlines, luna.deadlines) == ([99.0], [])


async def test_when_jev_is_unavailable_luna_answers_and_every_attempt_counts() -> None:
    jev, luna = Stub("jev", fails="timeout", attempts=3), Stub("openai")

    result = await ClassifierChain(jev, luna).classify(STATE, QUESTIONS, deadline=99.0)

    assert (result.meta.provider, result.meta.model) == ("openai", "gpt-6-luna")
    assert result.meta.attempts == 4  # three to Jev, one to Luna
    assert result.fallback_reason == "timeout"
    assert luna.deadlines == [99.0]  # the backup gets the same run deadline


async def test_both_failing_is_classifier_unavailable() -> None:
    jev = Stub("jev", fails="timeout", attempts=3)
    luna = Stub("openai", fails="server_error", attempts=3)

    with pytest.raises(ClassifierUnavailable) as raised:
        await ClassifierChain(jev, luna).classify(STATE, QUESTIONS)

    assert isinstance(raised.value, ProviderUnavailable)  # nodes treat it like any outage
    assert (raised.value.reason, raised.value.primary_reason) == ("server_error", "timeout")
    assert raised.value.attempts == 6


async def test_with_the_real_adapters_a_jev_timeout_is_retried_twice_then_luna_answers() -> None:
    """SPEC-providers AC1, through both SDKs on mocked transports."""
    jev_requests: list[httpx2.Request] = []

    def jev_down(request: httpx2.Request) -> httpx2.Response:
        jev_requests.append(request)
        raise httpx2.ReadTimeout("slow")

    policy = CallPolicy(timeout_s=2, retries=2, backoff_base_s=0.5, backoff_cap_s=4)
    jev = JevClassifier(
        AsyncTypeSafeClient(api_key="test-key", transport=httpx2.MockTransport(jev_down)),
        config=ProviderConfig(model="jev-1.13.0", policy=policy),
        sleep=no_sleep,
    )
    labels = {
        "intent": "fee_refund_request",
        "language": "en",
        "tone": "casual",
        "manipulation": False,
        "multiple_requests": False,
    }
    luna_api = Recorder(httpx2.Response(200, json=response_body(labels, model="gpt-6-luna")))
    luna = OpenAIClassifier(
        client_for(luna_api),
        config=ProviderConfig(
            model="gpt-6-luna", policy=policy.model_copy(update={"timeout_s": 8})
        ),
        sleep=no_sleep,
    )

    result = await ClassifierChain(jev, luna).classify(STATE, QUESTIONS)

    assert len(jev_requests) == 3
    assert (result.meta.provider, result.meta.model, result.meta.attempts) == (
        "openai",
        "gpt-6-luna",
        4,
    )
    assert result.answers["intent"] == ChoiceAnswer(choice="fee_refund_request")
