"""Recording (D10): run the seed scenarios with live providers wrapped in recorders, then replay
them with no providers at all and get the same case. Fakes stand in for the live models here."""

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.agents.deps import AgentDeps
from backend.providers.chain import ClassifierChain
from backend.providers.factory import UnavailableClassifier
from backend.providers.replay import (
    RecordingClassifier,
    RecordingDrafter,
    ReplayClassifier,
    ReplayDrafter,
    ReplayStore,
)
from backend.record import CASES, NEVER_RECORDED, record_cases
from tests.integration.agents.fakes import FakeChooser, FakeClassifier, FakeDrafter, jev_answers


def test_every_scenario_is_recorded_except_the_one_that_shows_the_fallback() -> None:
    recorded = {case for case, _ in CASES}

    assert {5118} == NEVER_RECORDED
    assert recorded.isdisjoint(NEVER_RECORDED)
    assert {5012, 5011, 5010, 5009, 5008, 5106, 5117} <= recorded
    assert (5109, 90902) in CASES and (5109, 90904) in CASES  # "Pick the fee", both ways


async def test_a_recorded_case_replays_the_same_with_no_models(
    reader: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    store = ReplayStore(tmp_path)
    jev = RecordingClassifier(
        FakeClassifier(jev_answers()), store, provider="jev", model="jev-1.13.0"
    )
    chooser = RecordingClassifier(
        FakeChooser(clause="fee-refund-policy#4"), store, provider="jev", model="jev-1.13.0"
    )
    live = AgentDeps(
        reader=reader,
        classifier=ClassifierChain(jev, UnavailableClassifier("auth")),
        drafter=RecordingDrafter(FakeDrafter(), store, model="gpt-6.1-sol"),
        chooser=chooser,
    )

    (recorded,) = await record_cases(live, [(5012, None)])

    replay_jev = ReplayClassifier(store, provider="jev", model="jev-1.13.0")
    replay = AgentDeps(
        reader=reader,
        classifier=ClassifierChain(replay_jev, UnavailableClassifier("replay_miss")),
        drafter=ReplayDrafter(store, model="gpt-6.1-sol"),
        chooser=replay_jev,
    )
    (replayed,) = await record_cases(replay, [(5012, None)])

    assert recorded == replayed == (5012, None, "ready_to_refund")
    assert {path.parent.parent.name for path in tmp_path.rglob("*.json")} == {"jev", "openai"}
