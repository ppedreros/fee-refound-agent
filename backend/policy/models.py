"""What the rules return (SPEC-policy, "Rules")."""

from pydantic import BaseModel

from backend.policy.facts import Fact
from backend.policy.reasons import ReasonCode


class RuleResult(BaseModel, frozen=True):
    rule: str
    passed: bool
    reason: ReasonCode | None = None
    clause_id: str  # the clause the rule implements
    facts: dict[str, Fact] = {}
