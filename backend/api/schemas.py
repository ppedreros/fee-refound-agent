"""Request and response bodies (SPEC-api). The frontend's types are generated from these."""

import datetime as dt
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, PositiveInt


class QueueItem(BaseModel):
    id: int
    member_name: str  # first name and last initial: "Ana T."
    subject: str
    received_at: dt.datetime  # the oldest unanswered member message
    status: str
    topic: str | None
    amount: Decimal | None  # the recommended refund, if there is one
    checked_at: dt.datetime | None


class QueuePage(BaseModel):
    items: list[QueueItem]
    next_cursor: str | None


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fee_txn_id: PositiveInt | None = None  # "Pick the fee": one of the latest run's candidates


class RunStarted(BaseModel):
    run_id: UUID
