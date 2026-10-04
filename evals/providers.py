"""The providers an eval run gives the graph (SPEC-evals, "Runner").

- **replay**: the committed recordings. A fallback case gets a temp copy with some of them
  removed (`replay_without`), so the miss is real and the normal fallback follows.
- **live**: the real models, with the keys from the environment.
- **live with `--record`**: fills in what is missing. A call that has a recording is answered
  from it; any other goes to the live model and is recorded. So recording the new cases never
  rewrites the answers the other cases already replay, and costs only the misses.

`--classifier backup` gives triage to Luna directly instead of the Jev-then-Luna chain. The
fee and clause choices stay with Jev (they need its calibrated confidence).
"""

import json
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Literal

from backend.core.settings import Settings
from backend.providers.chain import ClassifierChain
from backend.providers.config import providers_config
from backend.providers.factory import Providers, build_providers
from backend.providers.replay import RECORDINGS_DIR, ReplayStore
from backend.providers.types import (
    Classification,
    Classifier,
    Draft,
    Drafter,
    DraftInput,
    ProviderUnavailable,
    Question,
)
from evals.case import Mode, Recording

type ClassifierChoice = Literal["jev", "backup"]


class FillClassifier:
    """The recording when there is one, otherwise the live model (which records its answer)."""

    def __init__(self, replay: Classifier, recording: Classifier) -> None:
        self._replay = replay
        self._recording = recording

    async def classify(
        self,
        state: Mapping[str, str],
        questions: Sequence[Question],
        *,
        prompt_version: str | None = None,
        deadline: float | None = None,
    ) -> Classification:
        try:
            return await self._replay.classify(
                state, questions, prompt_version=prompt_version, deadline=deadline
            )
        except ProviderUnavailable as miss:
            if miss.reason != "replay_miss":
                raise
        return await self._recording.classify(
            state, questions, prompt_version=prompt_version, deadline=deadline
        )


class FillDrafter:
    def __init__(self, replay: Drafter, recording: Drafter) -> None:
        self._replay = replay
        self._recording = recording

    async def draft(
        self,
        payload: DraftInput,
        *,
        instructions: str,
        prompt_version: str | None = None,
        deadline: float | None = None,
    ) -> Draft:
        try:
            return await self._replay.draft(
                payload, instructions=instructions, prompt_version=prompt_version, deadline=deadline
            )
        except ProviderUnavailable as miss:
            if miss.reason != "replay_miss":
                raise
        return await self._recording.draft(
            payload, instructions=instructions, prompt_version=prompt_version, deadline=deadline
        )


def build(
    settings: Settings,
    *,
    mode: Mode,
    record: bool = False,
    classifier: ClassifierChoice = "jev",
    store: ReplayStore | None = None,
) -> Providers:
    replay = build_providers(settings.model_copy(update={"provider_mode": "replay"}), store=store)
    if mode == "replay":
        providers = replay
    else:
        live = build_providers(settings.model_copy(update={"provider_mode": "live"}), record=record)
        providers = _filled(replay, live) if record else live
    if classifier == "backup":
        providers = replace(providers, classifier=chain_of(providers).backup)
    return providers


def store_without(recordings: Sequence[Recording], root: Path) -> ReplayStore:
    """A temp copy of the recordings without the given providers' answers."""
    shutil.copytree(RECORDINGS_DIR, root)
    if "jev" in recordings:
        shutil.rmtree(root / "jev", ignore_errors=True)
    config = providers_config()
    models = {
        config.luna.model if name == "luna" else config.sol.model
        for name in recordings
        if name != "jev"
    }
    for path in (root / "openai").rglob("*.json"):
        if json.loads(path.read_text(encoding="utf-8"))["model"] in models:
            path.unlink()
    return ReplayStore(root)


def _filled(replay: Providers, live: Providers) -> Providers:
    replay_chain, live_chain = chain_of(replay), chain_of(live)
    jev = FillClassifier(replay_chain.primary, live_chain.primary)
    return Providers(
        classifier=ClassifierChain(jev, FillClassifier(replay_chain.backup, live_chain.backup)),
        drafter=FillDrafter(replay.drafter, live.drafter),
        chooser=jev,
        modes=live.modes,
        closers=live.closers,
    )


def chain_of(providers: Providers) -> ClassifierChain:
    if not isinstance(providers.classifier, ClassifierChain):
        raise TypeError("expected the Jev-then-Luna chain")
    return providers.classifier
