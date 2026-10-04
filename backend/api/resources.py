"""What the API process holds while it runs: database sessions for each role and the providers.

Built once at startup from the settings. Tests pass their own factory, because settings insist on
the real role names.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from backend.core.clock import Clock, SystemClock
from backend.core.settings import Settings
from backend.policy.loader import PolicyParams, current_policy
from backend.providers.factory import build_providers
from backend.providers.types import Classifier, Drafter


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


def default_resources(settings: Settings) -> AppResources:
    """Each provider in the mode the settings give it: live with its key, replay without one."""
    providers = build_providers(settings)
    return AppResources(
        writer_engine=create_async_engine(
            settings.app_database_url.get_secret_value(), pool_pre_ping=True
        ),
        reader_engine=create_async_engine(
            settings.agent_database_url.get_secret_value(), pool_pre_ping=True
        ),
        classifier=providers.classifier,
        drafter=providers.drafter,
        provider_modes=providers.modes,
        closers=providers.closers,
    )
