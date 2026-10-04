"""The core-banking adapter (SPEC-data, "Core-banking adapter"): one refund per fee, atomically,
as `app_writer`, whatever the timing (AC6), and the seed keeps or resets it (AC3)."""

import asyncio
import datetime as dt
from collections.abc import AsyncIterator
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, insert, select
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.db.core_banking import CoreBankingError, PostgresCoreBanking, RefundReceipt
from backend.db.models import AgentRun, Case, Decision, Refund, SubAccount, Transaction
from backend.db.seed import reset, seed
from tests.integration.roles import TEST_APP_ROLE, role_url

ON = dt.date(2026, 10, 4)
ANA_CHECKING = 1302


@pytest.fixture
async def writer(
    seeded: Engine, granted_roles: None, test_database_url: URL
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(role_url(test_database_url, TEST_APP_ROLE))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def new_decision(writer: async_sessionmaker[AsyncSession]) -> UUID:
    """A decision row for case 5012, which the refund points at."""
    async with writer() as session, session.begin():
        if await session.get(Case, 5012) is None:
            session.add(Case(conversation_id=5012, status="ready_to_refund"))
            await session.flush()
        run_id = await session.scalar(
            insert(AgentRun).values(case_id=5012, status="completed").returning(AgentRun.id)
        )
        decision_id: UUID | None = await session.scalar(
            insert(Decision)
            .values(
                case_id=5012,
                run_id=run_id,
                idempotency_key=uuid4(),
                staff_id="S07",
                action="approve",
            )
            .returning(Decision.id)
        )
    assert decision_id is not None
    return decision_id


async def refund(
    writer: async_sessionmaker[AsyncSession], fee_txn_id: int, decision_id: UUID
) -> RefundReceipt:
    async with writer() as session, session.begin():
        return await PostgresCoreBanking(session).post_fee_refund(fee_txn_id, decision_id, ON)


async def refund_rows(writer: async_sessionmaker[AsyncSession]) -> list[Transaction]:
    async with writer() as session:
        rows = await session.scalars(
            select(Transaction).where(
                Transaction.sub_account_id == ANA_CHECKING, Transaction.date == ON
            )
        )
        return list(rows)


async def checking(writer: async_sessionmaker[AsyncSession]) -> tuple[Decimal, Decimal]:
    async with writer() as session:
        row = (
            await session.execute(
                select(SubAccount.balance, SubAccount.available).where(
                    SubAccount.id == ANA_CHECKING
                )
            )
        ).one()
        return row.balance, row.available


async def test_a_refund_posts_a_transaction_and_raises_the_balance(
    writer: async_sessionmaker[AsyncSession],
) -> None:
    receipt = await refund(writer, 88002, await new_decision(writer))

    assert (receipt.fee_txn_id, receipt.amount, receipt.already_done) == (
        88002,
        Decimal("35.00"),
        False,
    )
    (posted,) = await refund_rows(writer)
    assert posted.id == receipt.refund_txn_id
    assert posted.description == "Deposit Fee Refund Courtesy Pay Fee"  # as the core writes them
    assert (posted.amount, posted.balance_after) == (Decimal("35.00"), Decimal("1360.00"))
    assert posted.posting_ref == "20261004-0000"
    assert await checking(writer) == (Decimal("1360.00"), Decimal("1360.00"))
    async with writer() as session:
        stored = await session.scalar(select(Refund).where(Refund.fee_txn_id == 88002))
    assert stored is not None and stored.refund_txn_id == posted.id


async def test_a_second_call_is_already_done_and_moves_no_money(
    writer: async_sessionmaker[AsyncSession],
) -> None:
    first = await refund(writer, 88002, await new_decision(writer))

    second = await refund(writer, 88002, await new_decision(writer))

    assert second.already_done is True
    assert (second.refund_txn_id, second.amount) == (first.refund_txn_id, first.amount)
    assert len(await refund_rows(writer)) == 1
    assert await checking(writer) == (Decimal("1360.00"), Decimal("1360.00"))


async def test_two_concurrent_calls_refund_once(
    writer: async_sessionmaker[AsyncSession],
) -> None:
    decisions = [await new_decision(writer), await new_decision(writer)]

    receipts = await asyncio.gather(*(refund(writer, 88002, d) for d in decisions))

    assert sorted(r.already_done for r in receipts) == [False, True]
    assert len(await refund_rows(writer)) == 1
    assert await checking(writer) == (Decimal("1360.00"), Decimal("1360.00"))


async def test_only_a_fee_can_be_refunded(writer: async_sessionmaker[AsyncSession]) -> None:
    decision_id = await new_decision(writer)

    with pytest.raises(CoreBankingError) as raised:
        await refund(writer, 88001, decision_id)  # the electric bill, not a fee

    assert raised.value.reason == "not_a_fee"
    assert await refund_rows(writer) == []


async def test_a_restart_keeps_the_refund_and_a_reset_restores_the_demo(
    writer: async_sessionmaker[AsyncSession], seeded: Engine
) -> None:
    await refund(writer, 88002, await new_decision(writer))

    with seeded.begin() as connection:  # what every start runs
        seed(connection)
    assert await checking(writer) == (Decimal("1360.00"), Decimal("1360.00"))
    assert len(await refund_rows(writer)) == 1

    with seeded.begin() as connection:  # bootstrap --reset
        reset(connection)
        seed(connection)
    assert await checking(writer) == (Decimal("1325.00"), Decimal("1325.00"))
    assert await refund_rows(writer) == []
    async with writer() as session:
        assert await session.scalar(select(func.count()).select_from(Refund)) == 0
