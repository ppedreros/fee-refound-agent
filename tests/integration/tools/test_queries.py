"""The agent's read-only tools, run as the read-only role against the seed (SPEC-data)."""

import datetime as dt
import json
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine, text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from backend.tools import queries
from backend.tools.errors import ToolError, ToolTimeout
from backend.tools.queries import (
    get_conversation,
    get_last_known_language,
    get_member_profile,
    list_fee_refunds,
    list_member_accounts,
    list_our_refunds,
    list_transactions,
)
from tests.integration.roles import TEST_AGENT_ROLE, role_url

FEE_DAY = dt.date(2026, 9, 14)


@pytest.fixture
async def reader(
    seeded: Engine, granted_roles: None, test_database_url: URL
) -> AsyncIterator[AsyncSession]:
    """An agent_reader session, as the graph's tools get it."""
    engine = create_async_engine(role_url(test_database_url, TEST_AGENT_ROLE))
    async with AsyncSession(engine) as session:
        yield session
    await engine.dispose()


def run_on_case(seeded: Engine, case_id: int, status: str, language: str, at: str) -> None:
    with seeded.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO cases (conversation_id, status) VALUES (:case, 'not_checked') "
                "ON CONFLICT DO NOTHING"
            ),
            {"case": case_id},
        )
        connection.execute(
            text(
                "INSERT INTO agent_runs (case_id, status, finished_at, result) "
                "VALUES (:case, :status, :at, CAST(:result AS jsonb))"
            ),
            {
                "case": case_id,
                "status": status,
                "at": at,
                "result": json.dumps({"language": language}),
            },
        )


# --- list_transactions ---


async def test_anas_fee_day_comes_back_in_posting_order_with_kinds(reader: AsyncSession) -> None:
    transactions = await list_transactions(reader, 301, FEE_DAY, FEE_DAY)

    assert [t.id for t in transactions] == [88001, 88002, 88003]
    assert [t.kind for t in transactions] == ["card_payment", "fee", "payroll_deposit"]


async def test_a_transaction_carries_what_the_rules_and_the_draft_need(
    reader: AsyncSession,
) -> None:
    fee = (await list_transactions(reader, 301, FEE_DAY, FEE_DAY))[1]

    assert fee.fee_type == "Courtesy Pay"
    assert fee.amount == Decimal("-35.00")
    assert fee.balance_after == Decimal("-75.00")
    assert fee.sub_account_name == "Everyday Checking"
    assert fee.posting_ref == "20260914-0005"


async def test_transactions_span_every_sub_account_of_the_member(reader: AsyncSession) -> None:
    transactions = await list_transactions(reader, 301, dt.date(2026, 1, 1), dt.date(2026, 12, 31))

    assert [t.id for t in transactions] == [87390, 87410, 88001, 88002, 88003]


async def test_another_members_transactions_never_leak_in(reader: AsyncSession) -> None:
    assert await list_transactions(reader, 288, dt.date(2026, 1, 1), FEE_DAY) == []


async def test_tools_return_frozen_models_not_database_rows(reader: AsyncSession) -> None:
    fee = (await list_transactions(reader, 301, FEE_DAY, FEE_DAY))[1]

    with pytest.raises(ValidationError):
        fee.amount = Decimal("-500.00")  # type: ignore[misc]  # must fail at runtime too


# --- the other tools ---


async def test_a_conversation_has_its_messages_in_order_with_who_wrote_them(
    reader: AsyncSession,
) -> None:
    conversation = await get_conversation(reader, 5011)

    assert (conversation.member_id, conversation.subject) == (288, "Card not working")
    assert conversation.status == "read_by_bank"
    assert [(m.author, m.body) for m in conversation.messages] == [
        ("member", "My card gets declined at the gas station."),
        ("staff", "Thanks, we are checking your card now."),
    ]


async def test_an_unknown_conversation_is_a_tool_error(reader: AsyncSession) -> None:
    with pytest.raises(ToolError) as error:
        await get_conversation(reader, 999_999)

    assert error.value.reason == "not_found"


async def test_the_member_profile_has_the_name(reader: AsyncSession) -> None:
    profile = await get_member_profile(reader, 301)

    assert (profile.first_name, profile.last_name) == ("Ana", "Torres")


async def test_accounts_come_with_their_sub_accounts_primary_first(reader: AsyncSession) -> None:
    accounts = await list_member_accounts(reader, 301)

    assert [(a.id, a.account_number, a.is_primary) for a in accounts] == [
        (710, "884210", True),
        (711, "884211", False),
    ]
    assert [(s.id, s.type, s.name, s.available) for s in accounts[0].sub_accounts] == [
        (1301, "SAVINGS", "Primary Savings", Decimal("210.40")),
        (1302, "CHECKING", "Everyday Checking", Decimal("1325.00")),
    ]


async def test_fee_refunds_since_a_date(reader: AsyncSession) -> None:
    refunds = await list_fee_refunds(reader, 301, since=dt.date(2025, 9, 14))

    assert [(r.id, r.fee_type) for r in refunds] == [
        (87390, "Out of Network"),
        (87410, "Courtesy Pay"),
    ]
    assert await list_fee_refunds(reader, 301, since=dt.date(2026, 3, 4)) == []


async def test_our_refunds_are_the_refund_rows_for_the_members_fees(
    reader: AsyncSession, seeded: Engine
) -> None:
    assert await list_our_refunds(reader, 301) == []
    with seeded.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO cases (conversation_id, status) VALUES (5012, 'done');"
                "INSERT INTO agent_runs (id, case_id, status) "
                "VALUES ('00000000-0000-0000-0000-000000000001', 5012, 'completed');"
                "INSERT INTO decisions (id, case_id, run_id, idempotency_key, staff_id, action) "
                "VALUES ('00000000-0000-0000-0000-0000000000d1', 5012, "
                "'00000000-0000-0000-0000-000000000001', gen_random_uuid(), 'S07', 'approve');"
                "INSERT INTO refunds (fee_txn_id, amount, decision_id) "
                "VALUES (88002, 35.00, '00000000-0000-0000-0000-0000000000d1')"
            )
        )

    refunds = await list_our_refunds(reader, 301)

    assert [(r.fee_txn_id, r.amount) for r in refunds] == [(88002, Decimal("35.00"))]
    assert await list_our_refunds(reader, 288) == []


async def test_last_known_language_comes_from_the_latest_completed_run_elsewhere(
    reader: AsyncSession, seeded: Engine
) -> None:
    run_on_case(seeded, 5009, "completed", "es", "2026-08-03 10:00:00+00")
    run_on_case(seeded, 5009, "failed", "en", "2026-08-04 10:00:00+00")
    run_on_case(seeded, 5012, "completed", "en", "2026-09-15 09:00:00+00")

    assert await get_last_known_language(reader, 301, exclude_case_id=5012) == "es"
    assert await get_last_known_language(reader, 301, exclude_case_id=5009) == "en"
    assert await get_last_known_language(reader, 288, exclude_case_id=5011) is None


# --- timeouts and errors ---


async def test_a_query_stuck_behind_a_lock_raises_tool_timeout(
    reader: AsyncSession, seeded: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(queries, "TOOL_TIMEOUT_S", 0.5)
    with seeded.connect() as owner:
        lock = owner.begin()
        owner.execute(text("LOCK TABLE transactions IN ACCESS EXCLUSIVE MODE"))

        with pytest.raises(ToolTimeout):
            await list_transactions(reader, 301, FEE_DAY, FEE_DAY)

        lock.rollback()


async def test_the_database_statement_timeout_also_becomes_tool_timeout(
    reader: AsyncSession, seeded: Engine
) -> None:
    await reader.execute(text("SET statement_timeout = '200ms'"))
    with seeded.connect() as owner:
        lock = owner.begin()
        owner.execute(text("LOCK TABLE transactions IN ACCESS EXCLUSIVE MODE"))

        with pytest.raises(ToolTimeout):
            await list_transactions(reader, 301, FEE_DAY, FEE_DAY)

        lock.rollback()


async def test_a_database_failure_is_a_tool_error_not_a_driver_error(
    seeded: Engine, granted_roles: None, test_database_url: URL
) -> None:
    wrong_password = role_url(test_database_url, TEST_AGENT_ROLE).set(password="wrong")
    engine = create_async_engine(wrong_password)
    async with AsyncSession(engine) as session:
        with pytest.raises(ToolError) as error:
            await get_member_profile(session, 301)
    await engine.dispose()

    assert error.value.reason == "database"
    assert not isinstance(error.value, ToolTimeout)
