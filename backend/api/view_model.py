"""One case for Luis's case pane (`GET /cases/{id}`, SPEC-api).

It reads the conversation, the member and the latest run's stored `result`, and renders every
sentence here, in English for Luis: the response carries text, never reason codes.
"""

import datetime as dt
import re
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.actions import actions_for
from backend.api.errors import NOT_FOUND, ApiError
from backend.api.queue import MEMBER_AUTHOR, OPEN_STATUSES
from backend.api.schemas import (
    AccountView,
    BelowZero,
    CandidateView,
    CaseView,
    CheckView,
    ClauseView,
    ConversationMessage,
    ConversationView,
    DecisionView,
    DraftView,
    EvidenceView,
    FeeDayRow,
    FeeDayView,
    FeeView,
    MemberView,
    ReasonView,
    RecommendationView,
    RefundRow,
    RefundsWindowView,
    RunView,
    StandingView,
    StepView,
    SubAccountView,
)
from backend.db.models import (
    Account,
    AgentRun,
    AgentStep,
    Case,
    Conversation,
    Decision,
    MemberProfile,
    Message,
    Refund,
    Staff,
    SubAccount,
)
from backend.policy.facts import Fact
from backend.policy.loader import PolicyParams
from backend.policy.reasons import (
    GROUPS,
    Language,
    ReasonCode,
    ReasonGroup,
    format_date,
    format_money,
    render_counterfactual,
    render_reason,
    render_summary,
)

LANG: Language = "en"  # Luis's page is in English; the reply keeps the member's language
FIRST_NAME = "{{first_name}}"
DEPOSIT_KINDS = ("payroll_deposit", "deposit")
MINUS = chr(0x2212)  # a real minus sign, as on a statement
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONEY = re.compile(r"^-?\d+(\.\d+)?$")  # the run stores money as text; counts stay numbers

type Json = dict[str, Any]


async def load_case_view(session: AsyncSession, case_id: int, params: PolicyParams) -> CaseView:
    conversation = await session.get(Conversation, case_id)
    if conversation is None:
        raise ApiError(404, *NOT_FOUND)
    profile = await session.get(MemberProfile, conversation.member_id)
    first_name = profile.first_name if profile else "the member"
    full_name = f"{profile.first_name} {profile.last_name}" if profile else "Member"

    case = await session.get(Case, case_id)
    run = await session.get(AgentRun, case.latest_run_id) if case and case.latest_run_id else None
    running = await session.scalar(
        select(AgentRun.id).where(AgentRun.case_id == case_id, AgentRun.status == "running")
    )
    status = case.status if case else "not_checked"
    result: Json = (run.result if run else None) or {}
    facts = _facts(result.get("facts", {}))

    fee = result.get("fee")
    recommendation = _recommendation(result)
    draft = _draft(result, first_name)
    candidates = result.get("candidates", [])
    return CaseView(
        id=case_id,
        conversation=await _conversation(session, conversation, full_name),
        member=await _member(session, conversation.member_id, full_name),
        status=status,
        topic=case.topic if case else None,
        language=result.get("language"),
        summary=render_summary(
            status, facts, LANG, first_name=first_name, reason=_decisive_reason(result)
        )
        if result
        else None,
        reasons=_reasons(result.get("reasons", []), facts, first_name),
        notes=_reasons(result.get("notes", []), facts, first_name),
        recommendation=recommendation,
        fee=_fee(fee) if fee else None,
        candidates=[
            CandidateView(fee_txn_id=c["id"], label=_candidate_label(c)) for c in candidates
        ],
        evidence=_evidence(result, facts, params),
        clause=ClauseView(**_pick(result["clause"], "doc_title", "section", "text"))
        if result.get("clause")
        else None,
        draft=draft,
        run=await _run(session, run) if run else None,
        decision=await _decision(session, case_id),
        actions=actions_for(status, result, params.staff_limit_usd),
        can_run=conversation.status in OPEN_STATUSES and running is None and status != "done",
        checking_run_id=running,
        can_pick_fee=ReasonCode.FEE_AMBIGUOUS.value in result.get("reasons", [])
        and bool(candidates),
    )


# --- Conversation and member ---


async def _conversation(
    session: AsyncSession, conversation: Conversation, member_name: str
) -> ConversationView:
    messages = (
        await session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at, Message.id)
        )
    ).all()
    staff_ids = {m.author_id for m in messages if not re.match(MEMBER_AUTHOR, m.author_id)}
    staff = await session.execute(
        select(Staff.id, Staff.display_name).where(Staff.id.in_(staff_ids))
    )
    names = {row.id: row.display_name for row in staff}
    return ConversationView(
        subject=conversation.subject,
        status=conversation.status,
        messages=[
            ConversationMessage(
                author="staff" if m.author_id in staff_ids else "member",
                author_name=names.get(m.author_id, "Staff")
                if m.author_id in staff_ids
                else member_name,
                body=m.body,
                created_at=m.created_at,
            )
            for m in messages
        ],
    )


async def _member(session: AsyncSession, member_id: int, full_name: str) -> MemberView:
    accounts = (
        await session.scalars(
            select(Account).where(Account.member_id == member_id).order_by(Account.id)
        )
    ).all()
    subs = (
        await session.scalars(
            select(SubAccount)
            .where(SubAccount.account_id.in_([a.id for a in accounts]))
            .order_by(SubAccount.id)
        )
    ).all()
    return MemberView(
        name=full_name,
        accounts=[
            AccountView(
                account_id=account.id,
                masked_number=f"••{account.account_number[-4:]}",
                sub_accounts=[
                    SubAccountView(
                        name=s.name, type=s.type, balance=s.balance, available=s.available
                    )
                    for s in subs
                    if s.account_id == account.id
                ],
            )
            for account in accounts
        ],
    )


# --- The latest run's result ---


def _facts(raw: Json) -> dict[str, Fact]:
    """Back to typed facts, so the reason templates format dates and money."""
    facts: dict[str, Fact] = {}
    for key, value in raw.items():
        if isinstance(value, str) and _DATE.match(value):
            facts[key] = dt.date.fromisoformat(value)
        elif isinstance(value, str) and _MONEY.match(value):
            facts[key] = Decimal(value)
        else:
            facts[key] = value
    return facts


def _decisive_reason(result: Json) -> ReasonCode | None:
    decisive = next(
        (c for c in result.get("checks", []) if c["rule"] == result.get("decisive_rule")), None
    )
    return ReasonCode(decisive["reason"]) if decisive and decisive.get("reason") else None


def _reasons(codes: list[str], facts: dict[str, Fact], first_name: str) -> list[ReasonView]:
    rendered = [
        render_reason(ReasonCode(code), facts, LANG, first_name=first_name)
        for code in codes
        if GROUPS[ReasonCode(code)] is not ReasonGroup.ROUTING  # the topic label says it
    ]
    return [ReasonView(message=r.message, next_step=r.next_step) for r in rendered]


def _recommendation(result: Json) -> RecommendationView:
    recommendation = result.get("recommendation") or {}
    amount = recommendation.get("amount")
    return RecommendationView(
        action=recommendation.get("action", "none"),
        amount=Decimal(amount) if amount is not None else None,
    )


def _fee(fee: Json) -> FeeView:
    return FeeView(
        fee_txn_id=fee["id"],
        source=fee.get("source"),
        **_pick(fee, "date", "amount", "fee_type", "description", "sub_account_name"),
    )


def _candidate_label(txn: Json) -> str:
    """Sep 14 · -$35.00 · Courtesy Pay fee · after CITY POWER & LIGHT -$60.00, with real minus
    signs: the payment that caused each fee tells two same-day fees apart."""
    amount = abs(Decimal(txn["amount"]))
    what = f"{txn['fee_type']} fee" if txn.get("fee_type") else txn["description"]
    day = format_date(dt.date.fromisoformat(txn["date"]), LANG)
    label = f"{day} · {MINUS}${amount:,.2f} · {what}"
    after = txn.get("after")
    if after:
        label += f" · after {after['payee']} {MINUS}${abs(Decimal(after['amount'])):,.2f}"
    return label


def _draft(result: Json, first_name: str) -> DraftView | None:
    draft = result.get("draft")
    if not draft:
        return None
    return DraftView(text=draft["text"].replace(FIRST_NAME, first_name), source=draft["source"])


def _evidence(result: Json, facts: dict[str, Fact], params: PolicyParams) -> EvidenceView:
    evidence, fee = result.get("evidence") or {}, result.get("fee")
    fee_day = refunds = standing = None
    if fee:
        fee_date = dt.date.fromisoformat(fee["date"])
        fee_day = FeeDayView(
            date=fee_date,
            rows=[
                FeeDayRow(
                    position=position,
                    is_fee=t["id"] == fee["id"],
                    is_deposit=t["kind"] in DEPOSIT_KINDS,
                    **_pick(t, "description", "amount", "balance_after", "kind"),
                )
                for position, t in enumerate(evidence.get("fee_day", []), start=1)
            ],
            summary=render_counterfactual(facts, LANG),
        )
        start = fee_date - dt.timedelta(days=params.window_days - 1)
        items = [
            RefundRow(**_pick(t, "date", "fee_type", "amount"))
            for t in evidence.get("refunds", [])
            if start <= dt.date.fromisoformat(t["date"]) <= fee_date
        ]
        refunds = RefundsWindowView(
            start=start,
            end=fee_date,
            count=len(items),
            max_allowed=params.max_refunds_in_window,
            items=items,
        )
    if evidence.get("sub_accounts"):
        below_zero = [
            BelowZero(**_pick(s, "name", "type", "available"))
            for s in evidence["sub_accounts"]
            if Decimal(s["available"]) < 0
        ]
        standing = StandingView(ok=not below_zero, below_zero=below_zero)
    checks = [
        CheckView(
            label=_check_label(c["rule"], params), passed=c["passed"], facts=c.get("facts", {})
        )
        for c in result.get("checks", [])
    ]
    return EvidenceView(
        fee_day=fee_day, refunds_in_window=refunds, standing=standing, checks=checks
    )


def _check_label(rule: str, params: PolicyParams) -> str:
    labels = {
        "verify_posting_order": "A same-day deposit would have covered the payment",
        "check_not_already_refunded": "This fee hasn't been refunded yet",
        "check_yearly_limit": (
            f"Fewer than {params.max_refunds_in_window} refunds in the last 12 months"
        ),
        "check_good_standing": "No unpaid balances",
        "check_approval_limit": (
            f"Within your {format_money(params.staff_limit_usd)} approval limit"
        ),
    }
    return labels.get(rule, "Policy check")


async def _run(session: AsyncSession, run: AgentRun) -> RunView:
    steps = (
        await session.scalars(
            select(AgentStep)
            .where(AgentStep.run_id == run.id)
            .order_by(AgentStep.started_at, AgentStep.id)
        )
    ).all()
    return RunView(
        run_id=run.id,
        checked_at=run.finished_at,
        duration_ms=run.total_latency_ms,
        cost_usd=run.cost_usd,
        provider_mode=run.provider_mode or {},
        steps=[StepView(node=s.node, state=s.status, latency_ms=s.latency_ms) for s in steps],
    )


async def _decision(session: AsyncSession, case_id: int) -> DecisionView | None:
    row = (
        await session.execute(
            select(Decision, Staff.display_name, Refund.amount)
            .join(Staff, Staff.id == Decision.staff_id)
            .outerjoin(Refund, Refund.decision_id == Decision.id)
            .where(Decision.case_id == case_id)
            .order_by(Decision.created_at.desc())
            .limit(1)
        )
    ).one_or_none()
    if row is None:
        return None
    decision, staff_name, refunded = row
    return DecisionView(
        by=staff_name,
        at=decision.created_at,
        action=decision.action,
        refunded=refunded is not None,
        amount=refunded,
        reply=decision.final_reply,
    )


def _pick(data: Json, *keys: str) -> Json:
    return {key: data.get(key) for key in keys}
