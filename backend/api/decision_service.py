"""The decision (SPEC-api, `POST /cases/{id}/decision`): the only place where money moves.

It runs inside the caller's transaction and first locks the case row, so two requests for one
case (with the same key or not) are decided one after the other. Validation follows the spec's
order; the effects (decision, refund, reply, closed conversation, `done`, audit events, eval
candidate) commit together or not at all.
"""

import datetime as dt
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.actions import (
    Action,
    actions_for,
    fee_amount,
    recommendation_of,
    would_refund,
)
from backend.api.errors import NOT_FOUND, ApiError
from backend.api.schemas import DecisionRequest, DecisionResult
from backend.db.core_banking import PostgresCoreBanking
from backend.db.models import (
    Account,
    AgentRun,
    AgentStep,
    AuditEvent,
    Case,
    Conversation,
    Decision,
    EvalCandidate,
    MemberProfile,
    Message,
    Refund,
    Staff,
)
from backend.policy.loader import PolicyParams
from backend.privacy.mask import MaskingDictionary, mask

REPLY_MAX = 2000
REASON_MIN, REASON_MAX = 10, 500
FIRST_NAME = "{{first_name}}"
FEEDBACK_ACTIONS = ("edit", "reject", "reply_only")  # what Luis changed becomes an eval case

STALE_RUN = "This case was checked again. Please look at the new result."
OVER_LIMIT = "A supervisor needs to approve this refund. That happens outside this tool for now."


@dataclass(frozen=True)
class Actor:
    staff_id: str
    now: dt.datetime
    request_id: UUID | None


async def make_decision(
    session: AsyncSession,
    case_id: int,
    key: UUID,
    request: DecisionRequest,
    *,
    actor: Actor,
    params: PolicyParams,
) -> DecisionResult:
    conversation = await session.get(Conversation, case_id)
    if conversation is None:
        raise ApiError(404, *NOT_FOUND)
    case = await session.scalar(
        select(Case).where(Case.conversation_id == case_id).with_for_update()
    )
    reply, reason = _clean(request.reply_text), _clean(request.reason)

    # 2. The same key seen before: the stored response, or a mismatch.
    previous = await session.scalar(select(Decision).where(Decision.idempotency_key == key))
    if previous is not None:
        same = (previous.case_id, previous.run_id, previous.action, previous.final_reply) == (
            case_id,
            request.run_id,
            request.action,
            reply,
        ) and previous.reason == reason
        if not same:
            raise ApiError(
                422,
                "idempotency_mismatch",
                "This decision was already sent with different details.",
            )
        return await _stored_response(session, previous)

    # 3. Already decided.
    if case is not None and case.status == "done":
        raise ApiError(409, "already_decided", await _already_decided(session, case_id))

    # 4. Stale run.
    run = (
        await session.get(AgentRun, request.run_id)
        if case is not None and case.latest_run_id == request.run_id
        else None
    )
    if case is None or run is None or run.result is None:
        raise ApiError(409, "stale_run", STALE_RUN)
    result: dict[str, Any] = run.result

    # 5. The approval limit, before the action list, so the friendly message wins (D-api-1).
    fee = result.get("fee")
    refunds = fee is not None and would_refund(request.action, recommendation_of(result))
    if fee is not None and refunds and fee_amount(fee) > params.staff_limit_usd:
        raise ApiError(403, "over_limit", OVER_LIMIT)

    # 6. The action must be one the case offers.
    if request.action not in actions_for(case.status, result, params.staff_limit_usd):
        raise ApiError(422, "action_not_allowed", "That action isn't available for this case.")

    # 8. The reply and the reason. (7: the amount is the run's fee; it is never in the request.)
    reply = _checked_reply(reply)
    _check_reason(request.action, reason)

    decision_id = await session.scalar(
        insert(Decision)
        .values(
            case_id=case_id,
            run_id=run.id,
            idempotency_key=key,
            staff_id=actor.staff_id,
            action=request.action,
            final_reply=reply,
            reason=reason,
        )
        .returning(Decision.id)
    )
    if decision_id is None:
        raise RuntimeError("the decision row was not created")

    refunded: Decimal | None = None
    receipt = None
    if fee is not None and refunds:
        receipt = await PostgresCoreBanking(session).post_fee_refund(
            fee["id"], decision_id, actor.now.date()
        )
        refunded = None if receipt.already_done else receipt.amount

    message_id = await session.scalar(
        insert(Message)
        .values(conversation_id=case_id, author_id=actor.staff_id, body=reply, created_at=actor.now)
        .returning(Message.id)
    )
    await session.execute(
        update(Conversation).where(Conversation.id == case_id).values(status="closed")
    )
    await session.execute(
        update(Case)
        .where(Case.conversation_id == case_id)
        .values(status="done", updated_at=actor.now, row_version=Case.row_version + 1)
    )

    def audit(action: str, details: dict[str, Any]) -> AuditEvent:
        return AuditEvent(
            actor=actor.staff_id,
            action=action,
            case_id=case_id,
            run_id=run.id,
            request_id=actor.request_id,
            details=details,
        )

    events = [audit("decision_made", {"action": request.action, "refunded": bool(refunded)})]
    if receipt is not None and refunded is not None:
        events.append(
            audit(
                "refund_posted",
                {
                    "fee_txn_id": receipt.fee_txn_id,
                    "refund_txn_id": receipt.refund_txn_id,
                    "amount": str(receipt.amount),
                },
            )
        )
    events.append(audit("reply_sent", {"message_id": message_id, "chars": len(reply)}))
    session.add_all(events)

    if request.action in FEEDBACK_ACTIONS:
        outcome = "refund" if refunds else "none" if request.action == "reply_only" else "no_refund"
        session.add(
            await _eval_candidate(
                session, conversation, run, decision_id, request.action, reply, reason, outcome
            )
        )
    await session.flush()
    return DecisionResult(
        decision_id=decision_id,
        refunded=refunded is not None,
        amount=refunded,
        case_status="done",
    )


def _clean(text: str | None) -> str | None:
    if text is None:
        return None
    return text.strip() or None


def _checked_reply(reply: str | None) -> str:
    if reply is None or len(reply) > REPLY_MAX:
        raise ApiError(422, "invalid_reply", "The reply needs 1 to 2,000 characters.")
    if any(char not in "\n\r\t" and unicodedata.category(char) == "Cc" for char in reply):
        raise ApiError(422, "invalid_reply", "The reply has a character we can't send.")
    if FIRST_NAME in reply:
        raise ApiError(422, "invalid_reply", "The reply still has a placeholder for the name.")
    return reply


def _check_reason(action: Action, reason: str | None) -> None:
    if action == "approve" and reason is not None:
        raise ApiError(422, "invalid_reason", "A reason isn't needed to approve.")
    if action == "reject" and (reason is None or not REASON_MIN <= len(reason) <= REASON_MAX):
        raise ApiError(422, "invalid_reason", "Please say why, in 10 to 500 characters.")
    if reason is not None and len(reason) > REASON_MAX:
        raise ApiError(422, "invalid_reason", "The reason can have up to 500 characters.")


async def _stored_response(session: AsyncSession, decision: Decision) -> DecisionResult:
    amount = await session.scalar(select(Refund.amount).where(Refund.decision_id == decision.id))
    status = await session.scalar(
        select(Case.status).where(Case.conversation_id == decision.case_id)
    )
    return DecisionResult(
        decision_id=decision.id,
        refunded=amount is not None,
        amount=amount,
        case_status=status or "done",
    )


async def _already_decided(session: AsyncSession, case_id: int) -> str:
    row = (
        await session.execute(
            select(Staff.display_name, Decision.created_at)
            .join(Staff, Staff.id == Decision.staff_id)
            .where(Decision.case_id == case_id)
            .order_by(Decision.created_at.desc())
            .limit(1)
        )
    ).one_or_none()
    if row is None:
        return "This case is already done."
    return f"{row.display_name} already decided this case at {row.created_at:%H:%M}."


async def _eval_candidate(
    session: AsyncSession,
    conversation: Conversation,
    run: AgentRun,
    decision_id: UUID,
    action: str,
    reply: str | None,
    reason: str | None,
    outcome: str,
) -> EvalCandidate:
    """What Luis did, as a future eval case (SPEC-evals, "Feedback loop"). Names and account
    numbers are masked; the case data stays by reference."""
    profile = await session.get(MemberProfile, conversation.member_id)
    numbers = (
        await session.scalars(
            select(Account.account_number).where(Account.member_id == conversation.member_id)
        )
    ).all()
    dictionary = MaskingDictionary(
        first_name=profile.first_name if profile else "",
        last_name=profile.last_name if profile else "",
        account_numbers=list(numbers),
    )
    triage_input = await session.scalar(
        select(AgentStep.input_masked).where(AgentStep.run_id == run.id, AgentStep.node == "triage")
    )
    result = run.result or {}
    return EvalCandidate(
        case_id=conversation.id,
        run_id=run.id,
        decision_id=decision_id,
        kind=action,
        masked_input={
            "case_id": conversation.id,
            "run_id": str(run.id),
            "triage": triage_input,
        },
        expected={
            "status": result.get("status"),
            "action": action,
            "recommendation": outcome,
            "reference_text": mask(reply, dictionary).text if action == "edit" and reply else None,
            "reason": mask(reason, dictionary).text if reason else None,
        },
    )
