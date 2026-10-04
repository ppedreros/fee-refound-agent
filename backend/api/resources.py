"""What the API process holds while it runs: database sessions for each role and the providers.

Built once at startup from the settings. Tests pass their own factory, because settings insist on
the real role names.
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from typesafe_sdk import AsyncTypeSafeClient

from backend.core.clock import Clock, SystemClock
from backend.core.settings import Settings
from backend.policy.loader import PolicyParams, current_policy
from backend.providers.config import providers_config
from backend.providers.jev import JevClassifier
from backend.providers.types import (
    Classification,
    Classifier,
    ProviderUnavailable,
    Question,
    UnavailableReason,
)


@dataclass
class AppResources:
    writer_engine: AsyncEngine  # app_writer: API reads, the run trace, decisions; also /health
    reader_engine: AsyncEngine  # agent_reader: the only database access the graph gets
    classifier: Classifier
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


class UnavailableClassifier:
    """Stands in when there is no live classifier: every call fails with `reason`, and the
    graph's normal fallback follows. Replay mode replaces it in T29."""

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
    resources = AppResources(
        writer_engine=create_async_engine(
            settings.app_database_url.get_secret_value(), pool_pre_ping=True
        ),
        reader_engine=create_async_engine(
            settings.agent_database_url.get_secret_value(), pool_pre_ping=True
        ),
        classifier=UnavailableClassifier("replay_miss"),
        provider_modes={"jev": modes.jev, "openai": modes.openai},
    )
    if modes.jev == "live" and settings.jev_api_key is not None:
        client = AsyncTypeSafeClient(api_key=settings.jev_api_key.get_secret_value())
        resources.classifier = JevClassifier(client, config=providers_config().jev)
        resources.closers.append(client.aclose)
    return resources
