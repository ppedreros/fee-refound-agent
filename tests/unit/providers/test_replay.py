"""Replay mode (D10; SPEC-providers, "Provider modes"): real answers recorded once, served again
by the hash of what was asked. A miss is an outage like any other, so the fallback follows."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from backend.agents.prompts import load_questions
from backend.providers.replay import (
    RecordingClassifier,
    RecordingDrafter,
    ReplayClassifier,
    ReplayDrafter,
    ReplayStore,
    replay_key,
)
from backend.providers.types import DraftInput, ProviderUnavailable
from tests.integration.agents.fakes import FakeClassifier, FakeDrafter, jev_answers

QUESTIONS = load_questions("triage-v2").questions
STATE = {"subject": "Overdraft fee", "message": "My paycheck came the same day."}
PAYLOAD = DraftInput(
    language="en",
    tone="casual",
    outcome="refund",
    amount="35.00",
    fee_date="2026-09-14",
    fee_type="Courtesy Pay",
    sub_account_name="Everyday Checking",
    facts=["The paycheck arrived the same day and the bill posted before it."],
    policy_clause=None,
)


def key(**changes: object) -> str:
    asked: dict[str, object] = {
        "provider": "jev",
        "model": "jev-1.13.0",
        "prompt_version": "triage-v2",
        "masked_input": STATE,
        "questions": [q.model_dump(mode="json") for q in QUESTIONS],
    }
    return replay_key(**(asked | changes))  # type: ignore[arg-type]


def test_the_same_question_always_has_the_same_key() -> None:
    reordered = {"message": STATE["message"], "subject": STATE["subject"]}

    assert key() == key(masked_input=reordered)
    assert len(key()) == 64


@pytest.mark.parametrize(
    "change",
    [
        {"prompt_version": "triage-v3"},
        {"model": "jev-1.14.0"},
        {"provider": "openai"},
        {"masked_input": STATE | {"message": "Something else."}},
    ],
)
def test_anything_that_changes_the_answer_changes_the_key(change: dict[str, object]) -> None:
    assert key(**change) != key()


async def test_a_recorded_answer_is_served_again_in_replay_mode(tmp_path: Path) -> None:
    store = ReplayStore(tmp_path)
    live = RecordingClassifier(
        FakeClassifier(jev_answers()), store, provider="jev", model="jev-1.13.0"
    )
    recorded = await live.classify(STATE, QUESTIONS, prompt_version="triage-v2")

    replayed = await ReplayClassifier(store, provider="jev", model="jev-1.13.0").classify(
        STATE, QUESTIONS, prompt_version="triage-v2"
    )

    assert replayed.answers == recorded.answers
    assert replayed.meta.mode == "replay"
    assert (replayed.meta.tokens_in, replayed.meta.cost_usd) == (760, Decimal("0.000032"))
    (path,) = tmp_path.rglob("*.json")
    assert path.parent.parent.name == "jev"
    assert path.parent.name == path.stem[:2]
    file = json.loads(path.read_text(encoding="utf-8"))
    assert file["sha256"] == path.stem
    assert file["request"]["masked_input"] == STATE
    assert file["prompt_version"] == "triage-v2"
    assert file["recorded_at"]


async def test_an_unrecorded_question_is_a_replay_miss(tmp_path: Path) -> None:
    replay = ReplayClassifier(ReplayStore(tmp_path), provider="jev", model="jev-1.13.0")

    with pytest.raises(ProviderUnavailable) as raised:
        await replay.classify(STATE, QUESTIONS, prompt_version="triage-v2")

    assert raised.value.reason == "replay_miss"


async def test_a_recorded_reply_is_served_again(tmp_path: Path) -> None:
    store = ReplayStore(tmp_path)
    recorded = await RecordingDrafter(FakeDrafter(), store, model="gpt-6.1-sol").draft(
        PAYLOAD, instructions="prompt", prompt_version="draft-v1"
    )

    replayed = await ReplayDrafter(store, model="gpt-6.1-sol").draft(
        PAYLOAD, instructions="prompt", prompt_version="draft-v1"
    )

    assert replayed.reply == recorded.reply
    assert (replayed.meta.mode, replayed.meta.tokens_cached) == ("replay", 1100)
    (path,) = tmp_path.rglob("*.json")
    assert path.parent.parent.name == "openai"


async def test_a_reply_for_other_facts_is_a_miss(tmp_path: Path) -> None:
    store = ReplayStore(tmp_path)
    await RecordingDrafter(FakeDrafter(), store, model="gpt-6.1-sol").draft(
        PAYLOAD, instructions="prompt", prompt_version="draft-v1"
    )
    other = PAYLOAD.model_copy(update={"amount": "60.00"})

    with pytest.raises(ProviderUnavailable) as raised:
        await ReplayDrafter(store, model="gpt-6.1-sol").draft(
            other, instructions="prompt", prompt_version="draft-v1"
        )

    assert raised.value.reason == "replay_miss"
