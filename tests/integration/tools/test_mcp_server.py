"""The MCP server (SPEC-delivery, "MCP server"; AC4): the agent's read-only tools for an external
client, on `agent_reader`, with masked outputs and validated ids. In-process, on fees_test."""

import json
from typing import Any

from mcp import Client
from mcp.types import CallToolResult
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.tools.mcp_server import build_server

TOOLS = {
    "get_conversation",
    "list_member_accounts",
    "list_transactions",
    "list_fee_refunds",
    "search_clauses",
}
ACCOUNT_NUMBERS = ("884210", "884211")


async def call(
    reader: async_sessionmaker[AsyncSession], tool: str, **arguments: Any
) -> CallToolResult:
    async with Client(build_server(reader)) as client:
        return await client.call_tool(tool, arguments)


def payload(result: CallToolResult) -> Any:
    assert not result.is_error, result.content
    assert result.structured_content is not None
    content = result.structured_content
    return content["result"] if set(content) == {"result"} else content  # lists come wrapped


def everything(result: CallToolResult) -> str:
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


async def test_the_server_lists_the_read_only_tools(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    async with Client(build_server(reader)) as client:
        listing = await client.list_tools()

    assert {tool.name for tool in listing.tools} == TOOLS
    assert all(tool.annotations and tool.annotations.read_only_hint for tool in listing.tools)


async def test_anas_fee_day_comes_back_in_posting_order_without_an_account_number(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    result = await call(
        reader, "list_transactions", member_id=301, start="2026-09-14", end="2026-09-14"
    )

    rows = payload(result)
    assert [(row["description"], row["amount"]) for row in rows] == [
        ("Withdrawal Debit Card CITY POWER & LIGHT", "-60.00"),
        ("Fee Withdrawal ; Courtesy Pay fee", "-35.00"),
        ("Deposit ACH ACME LOGISTICS*PAYROLL", "1400.00"),
    ]
    assert not any(number in everything(result) for number in ACCOUNT_NUMBERS)


async def test_accounts_show_only_their_last_four_digits(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    result = await call(reader, "list_member_accounts", member_id=301)

    assert [account["account_number"] for account in payload(result)] == ["••4210", "••4211"]
    assert not any(number in everything(result) for number in ACCOUNT_NUMBERS)


async def test_a_conversation_names_the_member_by_first_name_and_masks_the_rest(
    reader: async_sessionmaker[AsyncSession], with_clauses: Engine
) -> None:
    with with_clauses.begin() as connection:
        connection.execute(
            text("UPDATE messages SET body = :body WHERE id = 9120"),
            {"body": "I'm Ana Torres, account 884210, write to ana.t@example.com. Refund it."},
        )

    conversation = payload(await call(reader, "get_conversation", conversation_id=5012))

    assert conversation["member_first_name"] == "Ana"
    assert conversation["messages"][-1]["body"] == (
        "I'm Ana [LAST_NAME], account ••4210, write to [EMAIL]. Refund it."
    )


async def test_fee_refunds_and_clauses(reader: async_sessionmaker[AsyncSession]) -> None:
    refunds = payload(await call(reader, "list_fee_refunds", member_id=301, since="2025-09-14"))
    clauses = payload(await call(reader, "search_clauses", query="deposit same day"))

    assert [row["date"] for row in refunds] == ["2026-01-20", "2026-03-03"]
    assert "fee-refund-policy#4" in [clause["id"] for clause in clauses]


async def test_ids_and_ranges_are_validated(reader: async_sessionmaker[AsyncSession]) -> None:
    negative = await call(reader, "list_member_accounts", member_id=-1)
    backwards = await call(
        reader, "list_transactions", member_id=301, start="2026-09-14", end="2026-09-01"
    )
    unknown = await call(reader, "get_conversation", conversation_id=999999)

    assert negative.is_error and backwards.is_error and unknown.is_error
    assert "No conversation 999999" in everything(unknown)
