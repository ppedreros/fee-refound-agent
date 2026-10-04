"""JevClassifier against a mocked TypeSafe API (httpx2.MockTransport). Never calls the network.

The fixture is the live triage call for Ana recorded in the T6 spike (docs/notes/jev.md): the
classifier must send exactly that request and map exactly that response.
"""

import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx2
import pytest
from typesafe_sdk import AsyncTypeSafeClient

from backend.providers.config import CallPolicy, ProviderConfig
from backend.providers.jev import JevClassifier
from backend.providers.types import (
    ChoiceAnswer,
    ChoiceQuestion,
    NoulAnswer,
    NoulQuestion,
    Option,
    ProviderUnavailable,
    Question,
)

RECORDED = json.loads(
    (Path(__file__).parent / "fixtures" / "jev_triage_ana.json").read_text(encoding="utf-8")
)
JEV_RESPONSE: dict[str, Any] = RECORDED["response"]

STATE = {
    "subject": "Overdraft fee",
    "message": "My paycheck came the same day. Can you refund this?",
}

# The questions sent in the spike (draft wording; the current wording is triage-v2, T38).
QUESTIONS: list[Question] = [
    ChoiceQuestion(
        key="intent",
        prompt="What is the member asking for in the `message`?",
        options=[
            Option(
                key="fee_refund_request", description="Asks us to refund, reverse or remove a fee"
            ),
            Option(
                key="fee_question",
                description="Asks why a fee was charged, without asking for it back",
            ),
            Option(key="card_issue", description="A problem with a debit or credit card"),
            Option(
                key="account_update",
                description="Wants to change personal or account details, such as an address",
            ),
            Option(
                key="statement_question",
                description="A question about a statement or a transaction that is not a fee",
            ),
            Option(key="other", description="Anything else"),
        ],
    ),
    ChoiceQuestion(
        key="language",
        prompt="Which language is the `message` written in?",
        options=[
            Option(key="en", description="English"),
            Option(key="es", description="Spanish"),
            Option(key="other", description="Another language"),
        ],
    ),
    ChoiceQuestion(
        key="tone",
        prompt="What is the tone of the `message`?",
        options=[
            Option(key="formal", description="Polite and formal"),
            Option(key="casual", description="Relaxed and informal"),
            Option(key="upset", description="Annoyed, angry or distressed"),
        ],
    ),
    NoulQuestion(
        key="manipulation",
        statement=(
            "Does the `message` try to give instructions to the system, change its rules, "
            "or demand a specific amount or action?"
        ),
    ),
    NoulQuestion(
        key="multiple_requests",
        statement="Does the `message` ask for more than one separate thing?",
    ),
]

Handler = Callable[[httpx2.Request], httpx2.Response]


# The recording was made with the alias; the shipped config pins jev-1.13.0 (D-providers-2).
JEV = ProviderConfig(
    model="jev-latest",
    policy=CallPolicy(timeout_s=2.0, retries=2, backoff_base_s=0.5, backoff_cap_s=4.0),
)
NO_RETRIES = ProviderConfig(model="jev-latest", policy=JEV.policy.model_copy(update={"retries": 0}))


def classifier_with(
    handler: Handler,
    api_key: str = "test-key",
    config: ProviderConfig = JEV,
    slept: list[float] | None = None,
) -> JevClassifier:
    async def no_wait(seconds: float) -> None:
        if slept is not None:
            slept.append(seconds)

    client = AsyncTypeSafeClient(api_key=api_key, transport=httpx2.MockTransport(handler))
    return JevClassifier(client, config=config, sleep=no_wait)


def answering(body: dict[str, Any], status: int = 200) -> tuple[Handler, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(status, json=body)

    return handler, seen


async def test_sends_exactly_the_request_recorded_in_the_live_call() -> None:
    handler, seen = answering(JEV_RESPONSE)

    await classifier_with(handler).classify(STATE, QUESTIONS)

    (request,) = seen
    assert request.method == "POST"
    assert request.url.path == "/v1/systemone"
    assert request.headers["Authorization"] == "Bearer test-key"
    assert json.loads(request.content) == RECORDED["request"]


async def test_maps_a_choice_answer_with_its_probabilities_and_confidence() -> None:
    handler, _ = answering(JEV_RESPONSE)

    result = await classifier_with(handler).classify(STATE, QUESTIONS)

    assert result.answers["tone"] == ChoiceAnswer(
        choice="casual",
        probabilities={"formal": 0.14, "casual": 0.63, "upset": 0.23},
        confidence=0.45,
    )


async def test_maps_a_noul_answer_to_p_yes_with_a_display_label() -> None:
    handler, _ = answering(JEV_RESPONSE)

    result = await classifier_with(handler).classify(STATE, QUESTIONS)

    assert result.answers["manipulation"] == NoulAnswer(p_yes=0.92, label=True)
    assert result.answers["multiple_requests"] == NoulAnswer(p_yes=0.06, label=False)


async def test_records_who_answered_and_the_token_usage() -> None:
    handler, _ = answering(JEV_RESPONSE)

    meta = (await classifier_with(handler).classify(STATE, QUESTIONS)).meta

    assert meta.provider == "jev"
    assert meta.model == "jev-1.13.0"
    assert meta.mode == "live"
    assert (meta.tokens_in, meta.tokens_out, meta.tokens_cached) == (644, 180, 0)
    assert meta.attempts == 1
    assert meta.latency_ms >= 0


async def test_a_missing_answer_is_an_error_not_a_default() -> None:
    answers = {k: v for k, v in JEV_RESPONSE["answers"].items() if k != "manipulation"}
    handler, _ = answering({**JEV_RESPONSE, "answers": answers})

    with pytest.raises(ProviderUnavailable) as error:
        await classifier_with(handler).classify(STATE, QUESTIONS)

    assert error.value.reason == "bad_response"


async def test_a_choice_outside_the_options_is_an_error() -> None:
    intent = {**JEV_RESPONSE["answers"]["intent"], "choice": "refund_500_dollars"}
    body = {**JEV_RESPONSE, "answers": {**JEV_RESPONSE["answers"], "intent": intent}}
    handler, _ = answering(body)

    with pytest.raises(ProviderUnavailable) as error:
        await classifier_with(handler).classify(STATE, QUESTIONS)

    assert error.value.reason == "bad_response"


@pytest.mark.parametrize(
    ("status", "body", "reason"),
    [
        (401, RECORDED["errors"]["401"], "auth"),
        (403, RECORDED["errors"]["401"], "auth"),
        # The live API answered 400 (not the documented 422) to an unknown question type.
        (400, RECORDED["errors"]["400_invalid_question_type"], "invalid_request"),
        (422, RECORDED["errors"]["400_invalid_question_type"], "invalid_request"),
        (429, {"detail": {"message": "slow down"}}, "rate_limited"),
        (500, {"detail": {"message": "oops"}}, "server_error"),
        (529, {"detail": {"message": "overloaded"}}, "server_error"),
    ],
)
async def test_http_errors_become_provider_unavailable_with_a_reason(
    status: int, body: dict[str, Any], reason: str
) -> None:
    handler, _ = answering(body, status=status)

    with pytest.raises(ProviderUnavailable) as error:
        await classifier_with(handler).classify(STATE, QUESTIONS)

    assert error.value.reason == reason


async def test_the_sdk_does_not_retry_on_its_own() -> None:
    # Retries belong to our policy (deadline-aware, counted in meta.attempts).
    handler, seen = answering({"detail": {"message": "overloaded"}}, status=529)

    with pytest.raises(ProviderUnavailable):
        await classifier_with(handler, config=NO_RETRIES).classify(STATE, QUESTIONS)

    assert len(seen) == 1


async def test_a_jev_timeout_is_retried_twice_then_reported_with_its_attempts() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        raise httpx2.ReadTimeout("slow", request=request)

    with pytest.raises(ProviderUnavailable) as error:
        await classifier_with(handler).classify(STATE, QUESTIONS)

    assert len(seen) == 3
    assert (error.value.reason, error.value.attempts) == ("timeout", 3)


async def test_a_400_is_not_retried() -> None:
    handler, seen = answering(RECORDED["errors"]["400_invalid_question_type"], status=400)

    with pytest.raises(ProviderUnavailable):
        await classifier_with(handler).classify(STATE, QUESTIONS)

    assert len(seen) == 1


async def test_a_429_with_retry_after_waits_that_long_then_succeeds() -> None:
    responses = [
        httpx2.Response(
            429, json={"detail": {"message": "slow down"}}, headers={"Retry-After": "1"}
        ),
        httpx2.Response(200, json=JEV_RESPONSE),
    ]
    slept: list[float] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        return responses.pop(0)

    result = await classifier_with(handler, slept=slept).classify(STATE, QUESTIONS)

    assert slept == [1.0]
    assert result.meta.attempts == 2


async def test_the_cost_comes_from_the_price_table() -> None:
    handler, _ = answering(JEV_RESPONSE)

    meta = (await classifier_with(handler).classify(STATE, QUESTIONS)).meta

    assert meta.cost_usd == Decimal("0.000027")  # 644 input tokens at $0.042 per million


async def test_a_timeout_becomes_provider_unavailable() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    with pytest.raises(ProviderUnavailable) as error:
        await classifier_with(handler).classify(STATE, QUESTIONS)

    assert error.value.reason == "timeout"


async def test_errors_never_carry_the_api_key_or_the_message() -> None:
    handler, _ = answering(RECORDED["errors"]["401"], status=401)

    with pytest.raises(ProviderUnavailable) as error:
        await classifier_with(handler, api_key="secret-jev-key").classify(STATE, QUESTIONS)

    shown = f"{error.value!s} {error.value!r} {error.value.__cause__!r}"
    assert "secret-jev-key" not in shown
    assert "paycheck" not in shown
