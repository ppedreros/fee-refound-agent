"""What the nodes need from outside, passed as LangGraph's run context. Tests swap in fakes."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.agents.triage_rules import THRESHOLDS, Thresholds
from backend.policy.loader import Policy, current_policy
from backend.providers.types import Classifier


@dataclass(frozen=True)
class AgentDeps:
    reader: async_sessionmaker[AsyncSession]  # agent_reader sessions only: nodes never write
    classifier: Classifier
    policy: Policy = field(default_factory=current_policy)
    thresholds: Thresholds = THRESHOLDS
    deadline: float | None = None  # monotonic seconds; the runner sets it from the run timeout
    clock: Callable[[], float] = time.monotonic
