"""What the API process holds while it runs: database sessions for each role and the providers.

Built once at startup from the settings. Tests pass their own factory, because settings insist on
the real role names.
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from typesafe_sdk import AsyncTypeSafeClient

from backend.core.clock import Clock, SystemClock
from backend.core.settings import Settings
from backend.policy.loader import PolicyParams, current_policy
from backend.providers.chain import ClassifierChain
from backend.providers.config import providers_config
from backend.providers.jev import JevClassifier
from backend.providers.openai_classifier import OpenAIClassifier
from backend.providers.openai_drafter import OpenAIDrafter
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


@dataclass
class AppResources:
    writer_engine: AsyncEngine  # app_writer: API reads, the run trace, decisions; also /health
    reader_engine: AsyncEngine  # agent_reader: the only database access the graph gets
    classifier: Classifier  # Jev, then Luna
    drafter: Drafter  # Sol
    provider_modes: dict[str, str]
    closers: list[Callable[[], Awaitable[None]]] = field(default_factory=list)
    policy_params: PolicyParams = field(default_factory=lambda: current_policy().params)
    clock: Clock = field(default_factory=SystemClock)

    def __post_init__(self) -> None:
        self.writer = async_sessionmaker(self.writer_engine, expire_on_commit=False)
        self.reader = async_sessionmaker(self.reader_engine, expire_on_commit=False)

    async def close(self) -> None:
        for close in self.closers:
            await close()
        await self.writer_engine.dispose()
        await self.reader_engine.dispose()


class UnavailableDrafter:
    """Stands in for Sol with no key: every call fails with `reason`, and the draft node uses the
    template with `drafter_down`. Replay mode replaces it in T29."""

    def __init__(self, reason: UnavailableReason) -> None:
        self._reason: UnavailableReason = reason

    async def draft(
        self, payload: DraftInput, *, instructions: str, deadline: float | None = None
    ) -> Draft:
        raise DrafterUnavailable(self._reason)


class UnavailableClassifier:
    """Stands in for a classifier with no key: every call fails with `reason`, and the chain
    moves on to the next one. Replay mode replaces it in T29."""

    def __init__(self, reason: UnavailableReason) -> None:
        self._reason: UnavailableReason = reason

    async def classify(
        self,
        state: Mapping[str, str],
        questions: Sequence[Question],
        *,
        deadline: float | None = None,
    ) -> Classification:
        raise ProviderUnavailable(self._reason)


def default_resources(settings: Settings) -> AppResources:
    modes = settings.provider_modes
    config = providers_config()
    closers: list[Callable[[], Awaitable[None]]] = []
    jev: Classifier = UnavailableClassifier("replay_miss")
    luna: Classifier = UnavailableClassifier("replay_miss")
    sol: Drafter = UnavailableDrafter("replay_miss")
    if modes.jev == "live" and settings.jev_api_key is not None:
        jev_client = AsyncTypeSafeClient(api_key=settings.jev_api_key.get_secret_value())
        jev = JevClassifier(jev_client, config=config.jev)
        closers.append(jev_client.aclose)
    if modes.openai == "live" and settings.openai_api_key is not None:
        # Our call policy owns retries, so the SDK makes exactly one attempt per call.
        openai_client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(), max_retries=0
        )
        luna = OpenAIClassifier(openai_client, config=config.luna)
        sol = OpenAIDrafter(openai_client, config=config.sol)
        closers.append(openai_client.close)
    return AppResources(
        writer_engine=create_async_engine(
            settings.app_database_url.get_secret_value(), pool_pre_ping=True
        ),
        reader_engine=create_async_engine(
            settings.agent_database_url.get_secret_value(), pool_pre_ping=True
        ),
        classifier=ClassifierChain(jev, luna),
        drafter=sol,
        provider_modes={"jev": modes.jev, "openai": modes.openai},
        closers=closers,
    )
