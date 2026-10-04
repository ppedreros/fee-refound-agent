"""Request and response bodies (SPEC-api). The frontend's types are generated from these."""

import datetime as dt
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PositiveInt

from backend.api.actions import Action

# The UI maps each of these to its own words, so they are closed sets in the schema.
type CaseStatus = Literal[
    "not_checked",
    "checking",
    "ready_to_refund",
    "recommend_no_refund",
    "needs_supervisor",
    "needs_your_call",
    "not_about_fee",
    "done",
]
type Topic = Literal[
    "fee_refund_request",
    "fee_question",
    "card_issue",
    "account_update",
    "statement_question",
    "other",
]


class QueueItem(BaseModel):
    id: int
    member_name: str  # first name and last initial: "Ana T."
    subject: str
    received_at: dt.datetime  # the oldest unanswered member message
    status: CaseStatus
    topic: Topic | None
    amount: Decimal | None  # the recommended refund, if there is one
    checked_at: dt.datetime | None


class QueuePage(BaseModel):
    items: list[QueueItem]
    next_cursor: str | None


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fee_txn_id: PositiveInt | None = None  # "Pick the fee": one of the latest run's candidates


class RunStarted(BaseModel):
    run_id: UUID


# --- GET /cases/{id} (the case pane) ---


class ConversationMessage(BaseModel):
    author: Literal["member", "staff"]
    author_name: str
    body: str
    created_at: dt.datetime


class ConversationView(BaseModel):
    subject: str
    status: str
    messages: list[ConversationMessage]


class SubAccountView(BaseModel):
    name: str
    type: str
    balance: Decimal
    available: Decimal


class AccountView(BaseModel):
    account_id: int
    masked_number: str  # "••4210"; the full number only through the audited reveal
    sub_accounts: list[SubAccountView]


class MemberView(BaseModel):
    name: str
    accounts: list[AccountView]


class ReasonView(BaseModel):
    message: str
    next_step: str | None


class RecommendationView(BaseModel):
    action: Literal["refund", "no_refund", "none"]
    amount: Decimal | None


class FeeView(BaseModel):
    fee_txn_id: int
    date: dt.date
    amount: Decimal
    fee_type: str | None
    description: str
    sub_account_name: str
    source: Literal["rule", "jev", "staff"] | None  # how the fee was chosen


class CandidateView(BaseModel):
    fee_txn_id: int
    label: str  # "Sep 14 · -$35.00 · Courtesy Pay fee", with a real minus sign


class FeeDayRow(BaseModel):
    position: int
    description: str
    amount: Decimal
    balance_after: Decimal
    kind: str
    is_fee: bool
    is_deposit: bool


class FeeDayView(BaseModel):
    date: dt.date
    rows: list[FeeDayRow]
    summary: str | None


class RefundRow(BaseModel):
    date: dt.date
    fee_type: str | None
    amount: Decimal


class RefundsWindowView(BaseModel):
    start: dt.date
    end: dt.date
    count: int
    max_allowed: int
    items: list[RefundRow]


class BelowZero(BaseModel):
    name: str
    type: str
    available: Decimal


class StandingView(BaseModel):
    ok: bool
    below_zero: list[BelowZero]


class CheckView(BaseModel):
    label: str
    passed: bool
    facts: dict[str, str | int | bool | list[str]]  # dates and money as text, as in the run


class EvidenceView(BaseModel):
    fee_day: FeeDayView | None
    refunds_in_window: RefundsWindowView | None
    standing: StandingView | None
    checks: list[CheckView]


class ClauseView(BaseModel):
    doc_title: str
    section: str
    text: str


class DraftView(BaseModel):
    text: str
    source: Literal["model", "template"]


class StepView(BaseModel):
    node: str  # the UI maps node names to plain labels
    state: Literal["finished", "failed"]
    latency_ms: int


class RunView(BaseModel):
    run_id: UUID
    checked_at: dt.datetime | None
    duration_ms: int | None
    cost_usd: Decimal | None
    provider_mode: dict[str, str]
    steps: list[StepView]


class DecisionView(BaseModel):
    by: str
    at: dt.datetime
    action: Action
    refunded: bool
    amount: Decimal | None
    reply: str | None


class CaseView(BaseModel):
    id: int
    conversation: ConversationView
    member: MemberView
    status: CaseStatus
    topic: Topic | None
    language: str | None
    summary: str | None
    reasons: list[ReasonView]
    notes: list[ReasonView]
    recommendation: RecommendationView
    fee: FeeView | None
    candidates: list[CandidateView]
    evidence: EvidenceView
    clause: ClauseView | None
    draft: DraftView | None
    run: RunView | None
    decision: DecisionView | None
    actions: list[Action]
    can_run: bool
    can_pick_fee: bool
    checking_run_id: UUID | None  # the check in progress, whose live steps the page follows


# --- POST /cases/{id}/decision ---


class DecisionRequest(BaseModel):
    """What Luis decided. The amount is never here: it is always the run's fee (D-api-3). Length
    and content rules are checked by the handler, in the spec's order."""

    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    action: Action
    reply_text: str = Field(max_length=20_000)
    reason: str | None = Field(default=None, max_length=5_000)


class DecisionResult(BaseModel):
    decision_id: UUID
    refunded: bool
    amount: Decimal | None  # what this decision refunded
    case_status: CaseStatus
