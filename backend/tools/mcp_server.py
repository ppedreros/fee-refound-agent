"""The read-only tools as an MCP server, for an external client such as Claude Code (SPEC-delivery,
"MCP server"):

    uv run python -m backend.tools.mcp_server

Over stdio, always as `agent_reader`, so nothing it is asked can write. What leaves is masked for a
client outside the app: an account number becomes "••4210", the member is named by first name
only, and message text goes through the same masking as a model's input, with the first name and
the last four digits put back. Every id and range is checked before a query runs.
"""

import asyncio
import datetime as dt
import sys
from collections.abc import Awaitable
from decimal import Decimal
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError as McpToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.settings import ROLE_FOR_URL
from backend.policy.search import search_clauses as find_clauses
from backend.privacy.mask import MaskingDictionary, mask
from backend.tools import queries
from backend.tools.descriptions import TxnKind
from backend.tools.errors import ToolError, ToolTimeout
from backend.tools.models import SubAccount, Transaction

type Id = Annotated[int, Field(gt=0, le=2**31 - 1)]
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)


class McpSettings(BaseSettings):
    """Only the reader's URL: the server has no other way into the database."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    agent_database_url: SecretStr

    @field_validator("agent_database_url")
    @classmethod
    def _reader_only(cls, value: SecretStr) -> SecretStr:
        role = ROLE_FOR_URL["agent_database_url"]
        if make_url(value.get_secret_value()).username != role:
            raise ValueError(f"must log in as {role}")
        return value


# --- What a client sees ---


class MessageOut(BaseModel):
    author: str  # "member" or "staff"
    body: str
    created_at: dt.datetime


class ConversationOut(BaseModel):
    id: int
    member_id: int
    member_first_name: str
    subject: str
    status: str
    created_at: dt.datetime
    messages: list[MessageOut]  # oldest first


class AccountOut(BaseModel):
    id: int
    account_number: str  # "••4210"
    is_primary: bool
    sub_accounts: list[SubAccount]


class TransactionOut(BaseModel):
    id: int
    sub_account_name: str
    date: dt.date
    description: str
    amount: Decimal
    balance_after: Decimal
    posting_ref: str
    kind: TxnKind
    fee_type: str | None


class ClauseOut(BaseModel):
    id: str
    doc_title: str
    section: str
    text: str


def build_server(reader: async_sessionmaker[AsyncSession]) -> MCPServer:
    server = MCPServer(
        "fee-refunds",
        instructions=(
            "Read-only tools over the credit union's demo data: conversations, accounts, "
            "transactions in posting order, fee refunds, and the policy clauses. Outputs are "
            "masked; nothing here can change data."
        ),
        log_level="WARNING",
    )

    @server.tool(annotations=READ_ONLY)
    async def get_conversation(conversation_id: Id) -> ConversationOut:
        """A conversation with its messages, oldest first. The member is named by first name."""
        async with reader() as session:
            conversation = await _run(
                queries.get_conversation(session, conversation_id),
                f"No conversation {conversation_id}.",
            )
            dictionary, first_name = await _dictionary(session, conversation.member_id)
        return ConversationOut(
            id=conversation.id,
            member_id=conversation.member_id,
            member_first_name=first_name,
            subject=_shown(conversation.subject, dictionary),
            status=conversation.status,
            created_at=conversation.created_at,
            messages=[
                MessageOut(
                    author=message.author,
                    body=_shown(message.body, dictionary),
                    created_at=message.created_at,
                )
                for message in conversation.messages
            ],
        )

    @server.tool(annotations=READ_ONLY)
    async def list_member_accounts(member_id: Id) -> list[AccountOut]:
        """The member's accounts and sub-accounts with balances; numbers show their last four."""
        async with reader() as session:
            accounts = await _run(queries.list_member_accounts(session, member_id))
        return [
            AccountOut(
                id=account.id,
                account_number=_last_four(account.account_number),
                is_primary=account.is_primary,
                sub_accounts=list(account.sub_accounts),
            )
            for account in accounts
        ]

    @server.tool(annotations=READ_ONLY)
    async def list_transactions(
        member_id: Id, start: dt.date, end: dt.date
    ) -> list[TransactionOut]:
        """The member's transactions from `start` to `end` (both included), in posting order."""
        if end < start:
            raise McpToolError("`end` must be on or after `start`.")
        async with reader() as session:
            transactions = await _run(queries.list_transactions(session, member_id, start, end))
            dictionary, _ = await _dictionary(session, member_id)
        return [_transaction(transaction, dictionary) for transaction in transactions]

    @server.tool(annotations=READ_ONLY)
    async def list_fee_refunds(member_id: Id, since: dt.date) -> list[TransactionOut]:
        """Fee refunds posted on or after `since`, as the core system recorded them."""
        async with reader() as session:
            refunds = await _run(queries.list_fee_refunds(session, member_id, since))
            dictionary, _ = await _dictionary(session, member_id)
        return [_transaction(refund, dictionary) for refund in refunds]

    @server.tool(annotations=READ_ONLY)
    async def search_clauses(
        query: Annotated[str, Field(min_length=2, max_length=200)],
        limit: Annotated[int, Field(ge=1, le=10)] = 5,
    ) -> list[ClauseOut]:
        """The policy clauses that match every word of `query` (web-search syntax: "or",
        quotes and -word work), best first."""
        async with reader() as session:
            clauses = await _run(find_clauses(session, query, limit))
        return [ClauseOut.model_validate(clause, from_attributes=True) for clause in clauses]

    return server


async def _run[T](query: Awaitable[T], not_found: str = "Nothing was found.") -> T:
    """Await a read tool, turning its typed errors into messages a client can show."""
    try:
        return await query
    except ToolTimeout:
        raise McpToolError("The database took too long. Please try again.") from None
    except ToolError as error:
        raise McpToolError(
            not_found if error.reason == "not_found" else "The read failed."
        ) from None


async def _dictionary(session: AsyncSession, member_id: int) -> tuple[MaskingDictionary, str]:
    profile = await _run(queries.get_member_profile(session, member_id))
    numbers = await _run(queries.list_account_numbers(session, member_id))
    dictionary = MaskingDictionary(
        first_name=profile.first_name, last_name=profile.last_name, account_numbers=numbers
    )
    return dictionary, profile.first_name


def _shown(text: str, dictionary: MaskingDictionary) -> str:
    """Masked as for a model, then the first name and each account's last four put back."""
    masked = mask(text, dictionary)
    shown = masked.text
    for placeholder, value in masked.mapping.items():
        if placeholder.startswith("[FIRST_NAME"):
            shown = shown.replace(placeholder, value)
        elif placeholder.startswith("[ACCOUNT"):
            shown = shown.replace(placeholder, _last_four(value))
    return shown


def _last_four(account_number: str) -> str:
    return f"••{account_number[-4:]}"


def _transaction(transaction: Transaction, dictionary: MaskingDictionary) -> TransactionOut:
    return TransactionOut(
        id=transaction.id,
        sub_account_name=transaction.sub_account_name,
        date=transaction.date,
        description=_shown(transaction.description, dictionary),
        amount=transaction.amount,
        balance_after=transaction.balance_after,
        posting_ref=transaction.posting_ref,
        kind=transaction.kind,
        fee_type=transaction.fee_type,
    )


def main() -> None:
    settings = McpSettings()  # read from the environment (and .env)
    engine = create_async_engine(settings.agent_database_url.get_secret_value())
    server = build_server(async_sessionmaker(engine, expire_on_commit=False))
    # psycopg's async mode needs a selector loop on Windows; Linux doesn't care.
    factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(server.run_stdio_async(), loop_factory=factory)


if __name__ == "__main__":
    main()
