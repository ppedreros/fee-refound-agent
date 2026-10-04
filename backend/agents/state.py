"""The graph's state (SPEC-agent, "State"). Nodes return partial updates; `reasons` collects codes
from any node through a reducer, because the reads run in parallel."""

import datetime as dt
import operator
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from backend.agents.decide import Decision, FeeSource
from backend.agents.triage_rules import Triage
from backend.policy.models import RuleResult
from backend.policy.reasons import ReasonCode
from backend.privacy.mask import MaskingDictionary
from backend.tools.models import Account, OurRefund, Transaction


class ClauseRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    doc_title: str
    section: str
    text: str
    found_by: Literal["search_confirmed", "rule_fallback"]


class DraftReply(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str  # keeps the {{first_name}} placeholder; the API fills it in for Luis
    source: Literal["model", "template"]


class GraphState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Set by the runner
    case_id: int
    run_id: UUID
    pinned_fee_txn_id: int | None = None

    # load_conversation (the masking dictionary never goes into a step record)
    member_id: int | None = None
    message_at: dt.datetime | None = None
    masked_subject: str | None = None
    masked_message: str | None = None
    message_truncated: bool = False
    masking: MaskingDictionary | None = None
    last_known_language: str | None = None

    triage: Triage | None = None

    # The parallel reads
    accounts: list[Account] = []
    transactions: list[Transaction] = []
    refunds: list[Transaction] = []  # fee refunds as the core system recorded them
    our_refunds: list[OurRefund] = []

    fee: Transaction | None = None
    fee_source: FeeSource | None = None
    candidates: list[Transaction] = []
    checks: list[RuleResult] = []
    decision: Decision | None = None
    clause: ClauseRef | None = None
    draft: DraftReply | None = None

    reasons: Annotated[list[ReasonCode], operator.add] = []
    result: dict[str, Any] | None = None
