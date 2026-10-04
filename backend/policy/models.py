"""What the rules return (SPEC-policy, "Rules")."""

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel

from backend.policy.reasons import ReasonCode

# Facts are typed values, not sentences: the UI and the draft turn them into words.
type Fact = Decimal | dt.date | bool | int | str | list[str]


class RuleResult(BaseModel, frozen=True):
    rule: str
    passed: bool
    reason: ReasonCode | None = None
    clause_id: str  # the clause the rule implements
    facts: dict[str, Fact] = {}
