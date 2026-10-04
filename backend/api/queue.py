"""The queue (`GET /cases`): open conversations by their oldest unanswered member message, or the
done ones, newest first. Keyset pagination on (received_at, id) with an opaque cursor."""

import base64
import binascii
import datetime as dt
import json
from typing import Literal

from sqlalchemy import Select, and_, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from backend.api.errors import ApiError
from backend.api.schemas import QueueItem, QueuePage
from backend.db.models import AgentRun, Case, Conversation, MemberProfile, Message

OPEN_STATUSES = ("waiting_for_bank", "read_by_bank")
MEMBER_AUTHOR = "^[0-9]+$"  # member ids are numeric; staff ids start with a letter

type View = Literal["open", "done"]


async def list_queue(
    session: AsyncSession, view: View, limit: int, cursor: str | None
) -> QueuePage:
    queue = _queue().subquery()
    newest_first = view == "done"
    order = (queue.c.received_at, queue.c.id)
    query = select(queue).limit(limit + 1)
    query = query.order_by(*(c.desc() for c in order)) if newest_first else query.order_by(*order)
    if cursor is not None:
        after_at, after_id = _decode(cursor)
        position = tuple_(*order)
        query = query.where(
            position < (after_at, after_id) if newest_first else position > (after_at, after_id)
        )
    query = query.where(
        or_(queue.c.case_status == "done", queue.c.conversation_status == "closed")
        if view == "done"
        else and_(
            queue.c.conversation_status.in_(OPEN_STATUSES),
            or_(queue.c.case_status.is_(None), queue.c.case_status != "done"),
        )
    )

    rows = (await session.execute(query)).all()
    page = rows[:limit]
    items = [
        QueueItem(
            id=row.id,
            member_name=_short_name(row.first_name, row.last_name),
            subject=row.subject,
            received_at=row.received_at,
            status=row.case_status or "not_checked",
            topic=row.topic,
            amount=row.amount if row.action in ("refund", "no_refund") else None,
            checked_at=row.checked_at,
        )
        for row in page
    ]
    last = page[-1] if len(rows) > limit else None
    return QueuePage(items=items, next_cursor=_encode(last.received_at, last.id) if last else None)


def _queue() -> Select[tuple[object, ...]]:
    member = Message.author_id.regexp_match(MEMBER_AUTHOR)
    staff_message, member_message = aliased(Message), aliased(Message)
    last_staff_reply = (
        select(func.max(staff_message.created_at))
        .where(
            staff_message.conversation_id == Conversation.id,
            ~staff_message.author_id.regexp_match(MEMBER_AUTHOR),
        )
        .scalar_subquery()
    )
    first_unanswered = (
        select(func.min(member_message.created_at))
        .where(
            member_message.conversation_id == Conversation.id,
            member_message.author_id.regexp_match(MEMBER_AUTHOR),
            or_(last_staff_reply.is_(None), member_message.created_at > last_staff_reply),
        )
        .scalar_subquery()
    )
    last_from_member = (
        select(func.max(Message.created_at))
        .where(Message.conversation_id == Conversation.id, member)
        .scalar_subquery()
    )
    recommendation = AgentRun.result["recommendation"]
    return (
        select(
            Conversation.id,
            Conversation.subject,
            Conversation.status.label("conversation_status"),
            MemberProfile.first_name,
            MemberProfile.last_name,
            Case.status.label("case_status"),
            Case.topic,
            AgentRun.finished_at.label("checked_at"),
            recommendation["amount"].astext.label("amount"),
            recommendation["action"].astext.label("action"),
            func.coalesce(first_unanswered, last_from_member, Conversation.created_at).label(
                "received_at"
            ),
        )
        .outerjoin(MemberProfile, MemberProfile.member_id == Conversation.member_id)
        .outerjoin(Case, Case.conversation_id == Conversation.id)
        .outerjoin(AgentRun, AgentRun.id == Case.latest_run_id)
    )


def _short_name(first: str | None, last: str | None) -> str:
    if not first:
        return "Member"
    return f"{first} {last[0]}." if last else first


def _encode(received_at: dt.datetime, case_id: int) -> str:
    raw = json.dumps([received_at.isoformat(), case_id]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode(cursor: str) -> tuple[dt.datetime, int]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        at, case_id = json.loads(base64.urlsafe_b64decode(padded))
        return dt.datetime.fromisoformat(at), int(case_id)
    except binascii.Error, ValueError, TypeError, json.JSONDecodeError:
        raise ApiError(422, "invalid_request", "Something in that request isn't valid.") from None
