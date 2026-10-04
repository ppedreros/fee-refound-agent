"""SQLAlchemy models for every table in SPEC-data ("Tables").

The migration in `alembic/versions` creates them, and a test checks that the two agree. Money is
numeric(12,2), enumerations are text with a CHECK, timestamps are timestamptz (UTC).
"""

import datetime as dt
from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

CONVERSATION_STATUSES = ("waiting_for_bank", "waiting_for_member", "read_by_bank", "closed")
SUB_ACCOUNT_TYPES = ("SAVINGS", "CHECKING", "LOAN")
TOPICS = (
    "fee_refund_request",
    "fee_question",
    "card_issue",
    "account_update",
    "statement_question",
    "other",
)
CASE_STATUSES = (
    "not_checked",
    "checking",
    "ready_to_refund",
    "recommend_no_refund",
    "needs_supervisor",
    "needs_your_call",
    "not_about_fee",
    "done",
)
RUN_STATUSES = ("running", "completed", "failed", "interrupted")
RUN_OUTCOMES = (
    "ready_to_refund",
    "recommend_no_refund",
    "needs_supervisor",
    "needs_your_call",
    "not_about_fee",
)
CLASSIFIERS = ("jev", "backup")
STEP_KINDS = ("rule", "jev", "llm", "tool")
STEP_STATUSES = ("finished", "failed")
DECISION_ACTIONS = ("approve", "edit", "reject", "reply_only")
EVAL_CANDIDATE_KINDS = ("edit", "reject", "reply_only")

# Rows the app creates (replies, refund transactions) get ids from here up, so they never collide
# with the fixed ids the seed loads from the brief and the scenarios.
APP_GENERATED_IDS_START = 1_000_000

Money = sa.Numeric(12, 2)
Cost = sa.Numeric(10, 6)
Timestamp = sa.DateTime(timezone=True)
NOW = sa.text("now()")

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def one_of(column: str, values: tuple[str, ...]) -> sa.CheckConstraint:
    allowed = ", ".join(f"'{value}'" for value in values)
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=f"{column}_allowed")


class Base(DeclarativeBase):
    metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)


# --- Given by the brief (columns unchanged) ---


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        one_of("status", CONVERSATION_STATUSES),
        sa.Index(None, "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=False)
    member_id: Mapped[int] = mapped_column(sa.BigInteger)
    subject: Mapped[str] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(sa.Text)
    created_at: Mapped[dt.datetime] = mapped_column(Timestamp)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (sa.Index(None, "conversation_id", "created_at"),)

    id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.Identity(start=APP_GENERATED_IDS_START), primary_key=True
    )
    conversation_id: Mapped[int] = mapped_column(sa.ForeignKey("conversations.id"))
    author_id: Mapped[str] = mapped_column(sa.Text)  # a member id, or a staff id like "S07"
    body: Mapped[str] = mapped_column(sa.Text)
    created_at: Mapped[dt.datetime] = mapped_column(Timestamp)


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (sa.Index(None, "member_id"),)

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=False)
    member_id: Mapped[int] = mapped_column(sa.BigInteger)
    credit_union_id: Mapped[int] = mapped_column(sa.BigInteger)
    account_number: Mapped[str] = mapped_column(sa.Text)
    is_primary: Mapped[bool] = mapped_column(sa.Boolean)


class SubAccount(Base):
    __tablename__ = "sub_accounts"
    __table_args__ = (one_of("type", SUB_ACCOUNT_TYPES),)

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=False)
    account_id: Mapped[int] = mapped_column(sa.ForeignKey("accounts.id"))
    type: Mapped[str] = mapped_column(sa.Text)
    name: Mapped[str] = mapped_column(sa.Text)
    balance: Mapped[Decimal] = mapped_column(Money)
    # For a LOAN, available < 0 means a payment is past due (SPEC-data convention).
    available: Mapped[Decimal] = mapped_column(Money)


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        sa.CheckConstraint(r"posting_ref ~ '^\d{8}-\d{4}$'", name="posting_ref_format"),
        sa.UniqueConstraint("sub_account_id", "posting_ref"),
        sa.Index(None, "sub_account_id", "date"),
    )

    id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.Identity(start=APP_GENERATED_IDS_START), primary_key=True
    )
    sub_account_id: Mapped[int] = mapped_column(sa.ForeignKey("sub_accounts.id"))
    date: Mapped[dt.date] = mapped_column(sa.Date)
    description: Mapped[str] = mapped_column(sa.Text)
    amount: Mapped[Decimal] = mapped_column(Money)
    balance_after: Mapped[Decimal] = mapped_column(Money)
    posting_ref: Mapped[str] = mapped_column(sa.Text)  # YYYYMMDD-NNNN: date, then order that day


# --- Extensions (new tables, documented in the README) ---


class MemberProfile(Base):
    __tablename__ = "member_profiles"

    member_id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=False)
    first_name: Mapped[str] = mapped_column(sa.Text)
    last_name: Mapped[str] = mapped_column(sa.Text)


class Staff(Base):
    __tablename__ = "staff"

    id: Mapped[str] = mapped_column(sa.Text, primary_key=True)  # for example "S07"
    display_name: Mapped[str] = mapped_column(sa.Text)


# --- Policy (schema here; content and loader in SPEC-policy) ---


class PolicyClause(Base):
    __tablename__ = "policy_clauses"
    __table_args__ = (sa.Index(None, "search", postgresql_using="gin"),)

    id: Mapped[str] = mapped_column(sa.Text, primary_key=True)  # for example fee-refund-policy#2
    doc_slug: Mapped[str] = mapped_column(sa.Text)
    doc_title: Mapped[str] = mapped_column(sa.Text)
    section: Mapped[str] = mapped_column(sa.Text)
    text: Mapped[str] = mapped_column(sa.Text)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    policy_version: Mapped[str] = mapped_column(sa.Text)
    search: Mapped[str] = mapped_column(
        TSVECTOR,
        sa.Computed(
            "setweight(to_tsvector('english', doc_title || ' ' || section), 'A') || "
            "setweight(to_tsvector('english', text), 'B')",
            persisted=True,
        ),
    )


# --- App tables ---


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = (one_of("topic", TOPICS), one_of("status", CASE_STATUSES))

    conversation_id: Mapped[int] = mapped_column(
        sa.ForeignKey("conversations.id"), primary_key=True, autoincrement=False
    )
    topic: Mapped[str | None] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(sa.Text)
    # cases and agent_runs point at each other, so this key is added after both tables exist.
    latest_run_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("agent_runs.id", use_alter=True)
    )
    updated_at: Mapped[dt.datetime] = mapped_column(Timestamp, server_default=NOW)
    row_version: Mapped[int] = mapped_column(sa.Integer, server_default=sa.text("1"))


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        one_of("status", RUN_STATUSES),
        one_of("outcome", RUN_OUTCOMES),
        one_of("classifier_used", CLASSIFIERS),
        sa.Index(None, "case_id", "started_at"),
        # One active run per case (D-api-2).
        sa.Index(
            "uq_agent_runs_one_running_per_case",
            "case_id",
            unique=True,
            postgresql_where=sa.text("status = 'running'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=sa.text("gen_random_uuid()"))
    case_id: Mapped[int] = mapped_column(sa.ForeignKey("cases.conversation_id"))
    status: Mapped[str] = mapped_column(sa.Text)
    started_at: Mapped[dt.datetime] = mapped_column(Timestamp, server_default=NOW)
    finished_at: Mapped[dt.datetime | None] = mapped_column(Timestamp)
    outcome: Mapped[str | None] = mapped_column(sa.Text)
    reason_codes: Mapped[list[str]] = mapped_column(ARRAY(sa.Text), server_default=sa.text("'{}'"))
    would_auto_approve: Mapped[bool | None] = mapped_column(sa.Boolean)
    classifier_used: Mapped[str | None] = mapped_column(sa.Text)
    provider_mode: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    policy_version: Mapped[str | None] = mapped_column(sa.Text)
    prompt_versions: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    total_latency_ms: Mapped[int | None] = mapped_column(sa.Integer)
    tokens_in: Mapped[int | None] = mapped_column(sa.Integer)
    tokens_out: Mapped[int | None] = mapped_column(sa.Integer)
    tokens_cached: Mapped[int | None] = mapped_column(sa.Integer)
    tokens_cache_write: Mapped[int | None] = mapped_column(sa.Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Cost)


class AgentStep(Base):
    __tablename__ = "agent_steps"
    __table_args__ = (
        one_of("kind", STEP_KINDS),
        one_of("status", STEP_STATUSES),
        sa.Index(None, "run_id"),
    )

    id: Mapped[int] = mapped_column(sa.BigInteger, sa.Identity(), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(sa.ForeignKey("agent_runs.id"))
    node: Mapped[str] = mapped_column(sa.Text)
    kind: Mapped[str] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(sa.Text)
    started_at: Mapped[dt.datetime] = mapped_column(Timestamp)
    latency_ms: Mapped[int] = mapped_column(sa.Integer)
    model: Mapped[str | None] = mapped_column(sa.Text)
    prompt_version: Mapped[str | None] = mapped_column(sa.Text)
    tokens_in: Mapped[int | None] = mapped_column(sa.Integer)
    tokens_out: Mapped[int | None] = mapped_column(sa.Integer)
    tokens_cached: Mapped[int | None] = mapped_column(sa.Integer)
    tokens_cache_write: Mapped[int | None] = mapped_column(sa.Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Cost)
    attempts: Mapped[int | None] = mapped_column(sa.Integer)
    error_code: Mapped[str | None] = mapped_column(sa.Text)
    input_masked: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Decision(Base):
    __tablename__ = "decisions"
    __table_args__ = (one_of("action", DECISION_ACTIONS), sa.Index(None, "case_id"))

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=sa.text("gen_random_uuid()"))
    case_id: Mapped[int] = mapped_column(sa.ForeignKey("cases.conversation_id"))
    run_id: Mapped[UUID] = mapped_column(sa.ForeignKey("agent_runs.id"))
    idempotency_key: Mapped[UUID] = mapped_column(unique=True)
    staff_id: Mapped[str] = mapped_column(sa.ForeignKey("staff.id"))
    action: Mapped[str] = mapped_column(sa.Text)
    final_reply: Mapped[str | None] = mapped_column(sa.Text)
    reason: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[dt.datetime] = mapped_column(Timestamp, server_default=NOW)


class Refund(Base):
    __tablename__ = "refunds"
    __table_args__ = (sa.CheckConstraint("amount > 0", name="amount_positive"),)

    id: Mapped[int] = mapped_column(sa.BigInteger, sa.Identity(), primary_key=True)
    # UNIQUE: one refund per fee. This is the money-level idempotency (D-data-2).
    fee_txn_id: Mapped[int] = mapped_column(sa.ForeignKey("transactions.id"), unique=True)
    refund_txn_id: Mapped[int | None] = mapped_column(sa.ForeignKey("transactions.id"))
    amount: Mapped[Decimal] = mapped_column(Money)
    decision_id: Mapped[UUID] = mapped_column(sa.ForeignKey("decisions.id"))
    created_at: Mapped[dt.datetime] = mapped_column(Timestamp, server_default=NOW)


class AuditEvent(Base):
    """Append-only: a trigger (in the migration) rejects UPDATE and DELETE. No foreign keys,
    so the log never depends on the rows it describes. No personal data in `details`."""

    __tablename__ = "audit_events"
    __table_args__ = (sa.Index(None, "case_id"),)

    id: Mapped[int] = mapped_column(sa.BigInteger, sa.Identity(), primary_key=True)
    at: Mapped[dt.datetime] = mapped_column(Timestamp, server_default=NOW)
    actor: Mapped[str] = mapped_column(sa.Text)  # a staff id, or "system"
    action: Mapped[str] = mapped_column(sa.Text)
    case_id: Mapped[int | None] = mapped_column(sa.BigInteger)
    run_id: Mapped[UUID | None]
    request_id: Mapped[UUID | None]
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sa.text("'{}'"))


class EvalCandidate(Base):
    __tablename__ = "eval_candidates"
    __table_args__ = (one_of("kind", EVAL_CANDIDATE_KINDS),)

    id: Mapped[int] = mapped_column(sa.BigInteger, sa.Identity(), primary_key=True)
    case_id: Mapped[int] = mapped_column(sa.ForeignKey("cases.conversation_id"))
    run_id: Mapped[UUID] = mapped_column(sa.ForeignKey("agent_runs.id"))
    decision_id: Mapped[UUID] = mapped_column(sa.ForeignKey("decisions.id"))
    kind: Mapped[str] = mapped_column(sa.Text)
    masked_input: Mapped[dict[str, Any]] = mapped_column(JSONB)
    expected: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = mapped_column(Timestamp, server_default=NOW)
    exported_at: Mapped[dt.datetime | None] = mapped_column(Timestamp)
