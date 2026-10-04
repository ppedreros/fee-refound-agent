"""The core-banking adapter (SPEC-data, "Core-banking adapter"): the one write path for money.

`PostgresCoreBanking` simulates the core in the same database (D-data-2). It works inside the
caller's transaction, so the decision, the refund and the reply commit or roll back together
(SPEC-api, "Effects"). A real core integration would replace this class, not the protocol.
"""

import datetime as dt
from decimal import Decimal
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Refund, SubAccount, Transaction
from backend.tools.descriptions import classify_description


class RefundReceipt(BaseModel, frozen=True):
    fee_txn_id: int
    refund_txn_id: int | None
    amount: Decimal
    already_done: bool  # the fee was refunded before; this call moved no money


class CoreBankingError(Exception):
    def __init__(self, reason: Literal["not_a_fee"]) -> None:
        super().__init__(reason)
        self.reason = reason


class CoreBanking(Protocol):
    async def post_fee_refund(
        self, fee_txn_id: int, decision_id: UUID, on: dt.date
    ) -> RefundReceipt: ...


class PostgresCoreBanking:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def post_fee_refund(
        self, fee_txn_id: int, decision_id: UUID, on: dt.date
    ) -> RefundReceipt:
        session = self._session
        fee = (
            await session.execute(
                select(
                    Transaction.sub_account_id, Transaction.description, Transaction.amount
                ).where(Transaction.id == fee_txn_id)
            )
        ).one_or_none()
        kind = classify_description(fee.description) if fee else None
        if fee is None or kind is None or kind.kind != "fee" or fee.amount >= 0:
            raise CoreBankingError("not_a_fee")
        amount = -fee.amount

        # One refund per fee (D-data-2). A concurrent call waits here until the first commits.
        refund_id = await session.scalar(
            insert(Refund)
            .values(fee_txn_id=fee_txn_id, amount=amount, decision_id=decision_id)
            .on_conflict_do_nothing(index_elements=[Refund.fee_txn_id])
            .returning(Refund.id)
        )
        if refund_id is None:
            existing = (
                await session.execute(
                    select(Refund.refund_txn_id, Refund.amount).where(
                        Refund.fee_txn_id == fee_txn_id
                    )
                )
            ).one()
            return RefundReceipt(
                fee_txn_id=fee_txn_id,
                refund_txn_id=existing.refund_txn_id,
                amount=existing.amount,
                already_done=True,
            )

        # The lock orders refunds on one sub-account, so balances and posting refs chain.
        balance = (
            await session.execute(
                select(SubAccount.balance)
                .where(SubAccount.id == fee.sub_account_id)
                .with_for_update()
            )
        ).scalar_one()
        day = on.strftime("%Y%m%d")
        last_ref = await session.scalar(
            select(func.max(Transaction.posting_ref)).where(
                Transaction.sub_account_id == fee.sub_account_id,
                Transaction.posting_ref.like(f"{day}-%"),
            )
        )
        sequence = int(last_ref.split("-")[1]) + 1 if last_ref else 0
        what = f" {kind.fee_type} Fee" if kind.fee_type else ""
        refund_txn_id = await session.scalar(
            insert(Transaction)
            .values(
                sub_account_id=fee.sub_account_id,
                date=on,
                description=f"Deposit Fee Refund{what}",  # as the core writes them in the brief
                amount=amount,
                balance_after=balance + amount,
                posting_ref=f"{day}-{sequence:04d}",
            )
            .returning(Transaction.id)
        )
        await session.execute(
            update(SubAccount)
            .where(SubAccount.id == fee.sub_account_id)
            .values(balance=SubAccount.balance + amount, available=SubAccount.available + amount)
        )
        await session.execute(
            update(Refund).where(Refund.id == refund_id).values(refund_txn_id=refund_txn_id)
        )
        return RefundReceipt(
            fee_txn_id=fee_txn_id, refund_txn_id=refund_txn_id, amount=amount, already_done=False
        )
