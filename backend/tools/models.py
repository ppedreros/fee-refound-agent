"""What the read-only tools return: frozen models, never database rows (SPEC-data)."""

import datetime as dt
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from backend.tools.descriptions import TxnKind


class Message(BaseModel, frozen=True):
    id: int
    author: Literal["member", "staff"]
    body: str
    created_at: dt.datetime


class Conversation(BaseModel, frozen=True):
    id: int
    member_id: int
    subject: str
    status: str
    created_at: dt.datetime
    messages: tuple[Message, ...]  # oldest first


class MemberProfile(BaseModel, frozen=True):
    member_id: int
    first_name: str
    last_name: str


class SubAccount(BaseModel, frozen=True):
    id: int
    type: Literal["SAVINGS", "CHECKING", "LOAN"]
    name: str  # the display name the member sees, for example "Everyday Checking"
    balance: Decimal
    available: Decimal


class Account(BaseModel, frozen=True):
    id: int
    account_number: str  # for the masking dictionary; Luis's page shows it as ••4210
    is_primary: bool
    sub_accounts: tuple[SubAccount, ...]


class Transaction(BaseModel, frozen=True):
    id: int
    sub_account_id: int
    sub_account_name: str
    date: dt.date
    description: str
    amount: Decimal
    balance_after: Decimal
    posting_ref: str
    kind: TxnKind
    fee_type: str | None


class OurRefund(BaseModel, frozen=True):
    """A refund this app posted (a `refunds` row), for the "already refunded" check."""

    fee_txn_id: int
    amount: Decimal
    refunded_at: dt.datetime
