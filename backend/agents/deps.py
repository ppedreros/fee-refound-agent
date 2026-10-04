"""What the nodes need from outside, passed as LangGraph's run context. Tests swap in fakes."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.agents.triage_rules import THRESHOLDS, Thresholds
from backend.policy.loader import Policy, current_policy
from backend.providers.types import Classifier, Drafter


@dataclass(frozen=True)
class AgentDeps:
    reader: async_sessionmaker[AsyncSession]  # agent_reader sessions only: nodes never write
    classifier: Classifier  # Jev, then Luna (ClassifierChain)
    drafter: Drafter  # Sol
    # Jev alone, for the fee and clause choices: a choice needs a calibrated confidence, which
    # the backup doesn't give. None: two fees are ambiguous, and the rule's clause is quoted.
    chooser: Classifier | None = None
    policy: Policy = field(default_factory=current_policy)
    thresholds: Thresholds = THRESHOLDS
    deadline: float | None = None  # monotonic seconds; the runner sets it from the run timeout
    reserve_s: float = 0.0  # kept back from model calls, so their fallback finishes in the run
    clock: Callable[[], float] = time.monotonic

    @property
    def model_deadline(self) -> float | None:
        """When a model call must end: the run's deadline less the reserve. Reads keep the
        whole run, so a slow model never costs the evidence."""
        return None if self.deadline is None else self.deadline - self.reserve_s
