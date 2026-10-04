"""The agent's read-only tools (SPEC-data, "Read-only tools").

Each one takes an `agent_reader` session, returns frozen models, and raises `ToolTimeout` or
`ToolError` instead of a driver error. After a timeout, throw the session away: its connection
may still be busy with the cancelled statement.
"""

import asyncio
import datetime as dt
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from functools import wraps
from pathlib import Path
from typing import Any, Literal, cast

import yaml
from psycopg.errors import QueryCanceled
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import models as db
from backend.tools.descriptions import classify_description
from backend.tools.errors import ToolError, ToolTimeout
from backend.tools.models import (
    Account,
    Conversation,
    MemberProfile,
    Message,
    OurRefund,
    SubAccount,
    Transaction,
)

CONFIG_FILE = Path(__file__).resolve().parents[1] / "core" / "config" / "tools.yaml"
TOOL_TIMEOUT_S = float(yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))["timeout_s"])

type Language = Literal["en", "es", "other"]
LANGUAGES: tuple[Language, ...] = ("en", "es", "other")


def read_tool[**P, R](tool: Callable[P, Awaitable[R]]) -> Callable[P, Coroutine[Any, Any, R]]:
    """Apply the tool timeout and turn every database failure into a typed tool error."""

    @wraps(tool)
    async def run(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            async with asyncio.timeout(TOOL_TIMEOUT_S):
                return await tool(*args, **kwargs)
        except TimeoutError:
            raise ToolTimeout from None
        except DBAPIError as error:
            if isinstance(error.orig, QueryCanceled):  # the role's statement_timeout fired
                raise ToolTimeout from None
            raise ToolError("database") from None
        except SQLAlchemyError, OSError:
            raise ToolError("database") from None

    return run


@read_tool
async def get_conversation(session: AsyncSession, conversation_id: int) -> Conversation:
    conversation = (
        await session.execute(
            select(
                db.Conversation.id,
                db.Conversation.member_id,
                db.Conversation.subject,
                db.Conversation.status,
                db.Conversation.created_at,
            ).where(db.Conversation.id == conversation_id)
        )
    ).one_or_none()
    if conversation is None:
        raise ToolError("not_found")

    messages = await session.execute(
        select(db.Message.id, db.Message.author_id, db.Message.body, db.Message.created_at)
        .where(db.Message.conversation_id == conversation_id)
        .order_by(db.Message.created_at, db.Message.id)
    )
    return Conversation(
        id=conversation.id,
        member_id=conversation.member_id,
        subject=conversation.subject,
        status=conversation.status,
        created_at=conversation.created_at,
        messages=tuple(
            Message(
                id=message.id,
                # Members are numeric ids; staff ids start with a letter ("S07", "SYSTEM").
                author="member" if message.author_id.isdigit() else "staff",
                body=message.body,
                created_at=message.created_at,
            )
            for message in messages
        ),
    )


@read_tool
async def get_member_profile(session: AsyncSession, member_id: int) -> MemberProfile:
    profile = (
        await session.execute(
            select(
                db.MemberProfile.member_id,
                db.MemberProfile.first_name,
                db.MemberProfile.last_name,
            ).where(db.MemberProfile.member_id == member_id)
        )
    ).one_or_none()
    if profile is None:
        raise ToolError("not_found")
    return MemberProfile.model_validate(profile._asdict())


@read_tool
async def list_member_accounts(session: AsyncSession, member_id: int) -> list[Account]:
    accounts = (
        await session.execute(
            select(db.Account.id, db.Account.account_number, db.Account.is_primary)
            .where(db.Account.member_id == member_id)
            .order_by(db.Account.is_primary.desc(), db.Account.id)
        )
    ).all()
    sub_accounts = (
        await session.execute(
            select(
                db.SubAccount.id,
                db.SubAccount.account_id,
                db.SubAccount.type,
                db.SubAccount.name,
                db.SubAccount.balance,
                db.SubAccount.available,
            )
            .where(db.SubAccount.account_id.in_([account.id for account in accounts]))
            .order_by(db.SubAccount.id)
        )
    ).all()
    return [
        Account(
            id=account.id,
            account_number=account.account_number,
            is_primary=account.is_primary,
            sub_accounts=tuple(
                SubAccount.model_validate(sub._asdict())
                for sub in sub_accounts
                if sub.account_id == account.id
            ),
        )
        for account in accounts
    ]


@read_tool
async def list_transactions(
    session: AsyncSession, member_id: int, start: dt.date, end: dt.date
) -> list[Transaction]:
    """The member's transactions on every sub-account from `start` to `end` (both included),
    in posting order."""
    return await _member_transactions(session, member_id, start, end)


@read_tool
async def list_fee_refunds(
    session: AsyncSession, member_id: int, since: dt.date
) -> list[Transaction]:
    """Fee refunds posted on or after `since`, as the core system recorded them."""
    transactions = await _member_transactions(session, member_id, since, None)
    return [transaction for transaction in transactions if transaction.kind == "fee_refund"]


@read_tool
async def list_our_refunds(session: AsyncSession, member_id: int) -> list[OurRefund]:
    refunds = await session.execute(
        select(db.Refund.fee_txn_id, db.Refund.amount, db.Refund.created_at.label("refunded_at"))
        .join(db.Transaction, db.Transaction.id == db.Refund.fee_txn_id)
        .join(db.SubAccount, db.SubAccount.id == db.Transaction.sub_account_id)
        .join(db.Account, db.Account.id == db.SubAccount.account_id)
        .where(db.Account.member_id == member_id)
        .order_by(db.Refund.created_at)
    )
    return [OurRefund.model_validate(refund._asdict()) for refund in refunds]


@read_tool
async def get_last_known_language(
    session: AsyncSession, member_id: int, exclude_case_id: int
) -> Language | None:
    """The language of the member's latest completed run on another conversation (D3 fallback)."""
    language = db.AgentRun.result["language"].astext
    found = await session.scalar(
        select(language)
        .join(db.Conversation, db.Conversation.id == db.AgentRun.case_id)
        .where(
            db.Conversation.member_id == member_id,
            db.AgentRun.case_id != exclude_case_id,
            db.AgentRun.status == "completed",
            language.is_not(None),
        )
        .order_by(db.AgentRun.finished_at.desc().nulls_last())
        .limit(1)
    )
    return cast(Language, found) if found in LANGUAGES else None


async def _member_transactions(
    session: AsyncSession, member_id: int, start: dt.date, end: dt.date | None
) -> list[Transaction]:
    query = (
        select(
            db.Transaction.id,
            db.Transaction.sub_account_id,
            db.SubAccount.name.label("sub_account_name"),
            db.Transaction.date,
            db.Transaction.description,
            db.Transaction.amount,
            db.Transaction.balance_after,
            db.Transaction.posting_ref,
        )
        .join(db.SubAccount, db.SubAccount.id == db.Transaction.sub_account_id)
        .join(db.Account, db.Account.id == db.SubAccount.account_id)
        .where(db.Account.member_id == member_id, db.Transaction.date >= start)
        .order_by(db.Transaction.posting_ref, db.Transaction.sub_account_id, db.Transaction.id)
    )
    if end is not None:
        query = query.where(db.Transaction.date <= end)
    return [_transaction(row._asdict()) for row in await session.execute(query)]


def _transaction(fields: Mapping[str, Any]) -> Transaction:
    kind = classify_description(fields["description"])
    return Transaction(**fields, kind=kind.kind, fee_type=kind.fee_type)
