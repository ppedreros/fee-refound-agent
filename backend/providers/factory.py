"""Builds the providers each process uses, in the mode the settings give each one (D10).

- `live`: the real adapter, with its key. Live without a key is "unavailable" (`auth`), so the
  fallback follows instead of a crash.
- `replay`: the committed recordings; a miss is `replay_miss`.
- `record=True` (the evals runner's `--record` only): the live adapter, writing what it gets.

Luna and Sol share the `openai` mode and one client. Jev and Luna form the classifier chain.
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field

from openai import AsyncOpenAI
from typesafe_sdk import AsyncTypeSafeClient

from backend.core.settings import Settings
from backend.providers.chain import ClassifierChain
from backend.providers.config import providers_config
from backend.providers.jev import JevClassifier
from backend.providers.openai_classifier import OpenAIClassifier
from backend.providers.openai_drafter import OpenAIDrafter
from backend.providers.replay import (
    RecordingClassifier,
    RecordingDrafter,
    ReplayClassifier,
    ReplayDrafter,
    ReplayStore,
)
from backend.providers.types import (
    Classification,
    Classifier,
    Draft,
    Drafter,
    DrafterUnavailable,
    DraftInput,
    ProviderUnavailable,
    Question,
    UnavailableReason,
)


class UnavailableClassifier:
    """Stands in for a classifier that can't run: every call fails with `reason`, and the chain
    moves on to the next one."""

    def __init__(self, reason: UnavailableReason) -> None:
        self._reason: UnavailableReason = reason

    async def classify(
        self,
        state: Mapping[str, str],
        questions: Sequence[Question],
        *,
        prompt_version: str | None = None,
        deadline: float | None = None,
    ) -> Classification:
        raise ProviderUnavailable(self._reason)


class UnavailableDrafter:
    """Stands in for Sol when it can't run: the draft node uses the template with
    `drafter_down`."""

    def __init__(self, reason: UnavailableReason) -> None:
        self._reason: UnavailableReason = reason

    async def draft(
        self,
        payload: DraftInput,
        *,
        instructions: str,
        prompt_version: str | None = None,
        deadline: float | None = None,
    ) -> Draft:
        raise DrafterUnavailable(self._reason)


@dataclass
class Providers:
    classifier: Classifier  # Jev, then Luna
    drafter: Drafter  # Sol
    chooser: Classifier  # Jev alone for the fee and clause choices: they need its confidence
    modes: dict[str, str]
    closers: list[Callable[[], Awaitable[None]]] = field(default_factory=list)

    async def close(self) -> None:
        for close in self.closers:
            await close()


def build_providers(
    settings: Settings, *, record: bool = False, store: ReplayStore | None = None
) -> Providers:
    store = store or ReplayStore()
    config = providers_config()
    modes = settings.provider_modes
    closers: list[Callable[[], Awaitable[None]]] = []

    jev: Classifier
    if modes.jev == "replay":
        jev = ReplayClassifier(store, provider="jev", model=config.jev.model)
    elif settings.jev_api_key is None:
        jev = UnavailableClassifier("auth")
    else:
        jev_client = AsyncTypeSafeClient(api_key=settings.jev_api_key.get_secret_value())
        closers.append(jev_client.aclose)
        jev = JevClassifier(jev_client, config=config.jev)
        if record:
            jev = RecordingClassifier(jev, store, provider="jev", model=config.jev.model)

    luna: Classifier
    sol: Drafter
    if modes.openai == "replay":
        luna = ReplayClassifier(store, provider="openai", model=config.luna.model)
        sol = ReplayDrafter(store, model=config.sol.model)
    elif settings.openai_api_key is None:
        luna, sol = UnavailableClassifier("auth"), UnavailableDrafter("auth")
    else:
        # Our call policy owns retries, so the SDK makes exactly one attempt per call.
        client = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value(), max_retries=0)
        closers.append(client.close)
        luna = OpenAIClassifier(client, config=config.luna)
        sol = OpenAIDrafter(client, config=config.sol)
        if record:
            luna = RecordingClassifier(luna, store, provider="openai", model=config.luna.model)
            sol = RecordingDrafter(sol, store, model=config.sol.model)

    return Providers(
        classifier=ClassifierChain(jev, luna),
        drafter=sol,
        chooser=jev,
        modes={"jev": modes.jev, "openai": modes.openai},
        closers=closers,
    )
