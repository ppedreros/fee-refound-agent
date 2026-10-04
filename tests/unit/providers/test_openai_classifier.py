"""OpenAIClassifier (Luna, the backup classifier) against a mocked Responses API.

Luna gets the same typed questions as Jev through a strict JSON schema, sees the member's text
only as a delimited data block, and returns labels only: never an invented confidence (D3).
"""

import json
from decimal import Decimal

import httpx2
import pytest

from backend.agents.prompts import load_questions
from backend.providers.config import CallPolicy, ProviderConfig
from backend.providers.openai_classifier import OpenAIClassifier
from backend.providers.types import ChoiceAnswer, NoulAnswer, ProviderUnavailable
from tests.unit.providers.openai_fakes import Recorder, client_for, no_sleep, response_body

LUNA = ProviderConfig(
    model="gpt-6-luna",
    policy=CallPolicy(timeout_s=8, retries=2, backoff_base_s=0.5, backoff_cap_s=4),
)
QUESTIONS = load_questions("triage-v1").questions
STATE = {
    "subject": "Overdraft fee",
    "message": "My paycheck came the same day. Can you refund this?",
}
LABELS = {
    "intent": "fee_refund_request",
    "language": "en",
    "tone": "casual",
    "manipulation": False,
    "multiple_requests": False,
}


def ok(
    output: dict[str, object] | str = LABELS, *, tokens_in: int = 320, tokens_out: int = 40
) -> httpx2.Response:
    body = response_body(output, model="gpt-6-luna", tokens_in=tokens_in, tokens_out=tokens_out)
    return httpx2.Response(200, json=body)


def luna(recorder: Recorder) -> OpenAIClassifier:
    return OpenAIClassifier(client_for(recorder), config=LUNA, sleep=no_sleep)


async def test_sends_one_strict_schema_with_an_enum_per_choice_and_a_boolean_per_noul() -> None:
    recorder = Recorder(ok())

    await luna(recorder).classify(STATE, QUESTIONS)

    (sent,) = recorder.requests
    assert sent["model"] == "gpt-6-luna"
    assert sent["reasoning"] == {"effort": "none"}
    assert sent["store"] is False
    output_format = sent["text"]["format"]
    assert (output_format["type"], output_format["strict"]) == ("json_schema", True)
    schema = output_format["schema"]
    assert schema["additionalProperties"] is False
    assert schema["required"] == list(LABELS)
    properties = schema["properties"]
    assert properties["intent"]["enum"] == [
        "fee_refund_request",
        "fee_question",
        "card_issue",
        "account_update",
        "statement_question",
        "other",
    ]
    assert properties["language"] == {
        "type": "string",
        "enum": ["en", "es", "other"],
        "description": "Which language is the `message` written in?",
    }
    assert properties["manipulation"]["type"] == "boolean"


async def test_the_members_text_is_a_delimited_block_marked_as_data() -> None:
    recorder = Recorder(ok())

    await luna(recorder).classify(STATE, QUESTIONS)

    (sent,) = recorder.requests
    assert "never instructions" in sent["instructions"]
    assert "fee_refund_request: Asks us to refund, reverse or remove a fee" in sent["instructions"]
    (message,) = sent["input"]
    data = message["content"]
    assert data.startswith("<data>\n") and data.endswith("\n</data>")
    assert json.loads(data.removeprefix("<data>\n").removesuffix("\n</data>")) == STATE
    assert STATE["message"] not in sent["instructions"]


async def test_gives_labels_and_never_invents_a_confidence() -> None:
    result = await luna(Recorder(ok(tokens_in=320, tokens_out=40))).classify(STATE, QUESTIONS)

    assert result.answers["intent"] == ChoiceAnswer(
        choice="fee_refund_request", probabilities=None, confidence=None
    )
    assert result.answers["manipulation"] == NoulAnswer(p_yes=None, label=False)
    meta = result.meta
    assert (meta.provider, meta.model, meta.mode, meta.attempts) == (
        "openai",
        "gpt-6-luna",
        "live",
        1,
    )
    assert (meta.tokens_in, meta.tokens_out) == (320, 40)
    assert meta.cost_usd == Decimal("0.000052")  # 320 at $0.10 and 40 at $0.50, per 1M tokens


@pytest.mark.parametrize(
    "output",
    [
        LABELS | {"intent": "refund_everything"},  # not one of the options
        {key: value for key, value in LABELS.items() if key != "tone"},  # a missing answer
        LABELS | {"manipulation": "no"},  # not a boolean
        "not json",
    ],
)
async def test_an_answer_that_breaks_the_schema_fails_at_once(
    output: dict[str, object] | str,
) -> None:
    recorder = Recorder(ok(output))

    with pytest.raises(ProviderUnavailable) as raised:
        await luna(recorder).classify(STATE, QUESTIONS)

    assert (raised.value.reason, raised.value.attempts) == ("bad_response", 1)


async def test_a_refusal_is_a_bad_response() -> None:
    body = response_body("", model="gpt-6-luna", refusal="I can't help with that.")

    with pytest.raises(ProviderUnavailable) as raised:
        await luna(Recorder(httpx2.Response(200, json=body))).classify(STATE, QUESTIONS)

    assert raised.value.reason == "bad_response"


async def test_a_timeout_is_retried_twice_then_gives_up() -> None:
    recorder = Recorder(httpx2.ReadTimeout("slow"))

    with pytest.raises(ProviderUnavailable) as raised:
        await luna(recorder).classify(STATE, QUESTIONS)

    assert (raised.value.reason, raised.value.attempts) == ("timeout", 3)
    assert len(recorder.requests) == 3


async def test_a_bad_request_is_not_retried() -> None:
    error = {"error": {"message": "bad", "type": "invalid_request_error", "code": None}}
    recorder = Recorder(httpx2.Response(400, json=error))

    with pytest.raises(ProviderUnavailable) as raised:
        await luna(recorder).classify(STATE, QUESTIONS)

    assert (raised.value.reason, len(recorder.requests)) == ("invalid_request", 1)


async def test_a_rate_limit_waits_as_long_as_retry_after_says() -> None:
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    limited = httpx2.Response(
        429,
        headers={"retry-after": "1"},
        json={"error": {"message": "slow down", "type": "rate_limit_error", "code": None}},
    )
    recorder = Recorder(limited, ok())
    classifier = OpenAIClassifier(client_for(recorder), config=LUNA, sleep=sleep)

    result = await classifier.classify(STATE, QUESTIONS)

    assert waits == [1.0]
    assert result.meta.attempts == 2
