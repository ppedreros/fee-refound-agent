"""Seed scenarios (SPEC-data, "Seed"). Scenario 1 is the brief's data, verbatim.

Cells the brief's PDF wraps onto two lines are one string joined by a space. The brief's
timestamps carry no zone; they are stored as UTC. Each later scenario (2-18) is one member with a
conversation, accounts and transactions; their tasks add them here, and `evals` reuses them.
"""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

type Rows = dict[str, list[dict[str, Any]]]


@dataclass(frozen=True)
class Scenario:
    number: int
    title: str
    rows: Rows


def utc(timestamp: str) -> dt.datetime:
    return dt.datetime.fromisoformat(timestamp).replace(tzinfo=dt.UTC)


STAFF = [
    {"id": "S07", "display_name": "Luis"},
    {"id": "S14", "display_name": "Sam"},  # the brief's message 9119 is from S14
    {"id": "SYSTEM", "display_name": "Automatic approval"},  # only if auto-approve is ever on
]

BRIEF = Scenario(
    number=1,
    title="The brief: Ana's overdraft fee (5012) and the other conversations",
    rows={
        "conversations": [
            {
                "id": 5012,
                "member_id": 301,
                "subject": "Overdraft fee",
                "status": "waiting_for_bank",
                "created_at": utc("2026-09-15 08:12:44"),
            },
            {
                "id": 5011,
                "member_id": 288,
                "subject": "Card not working",
                "status": "read_by_bank",
                "created_at": utc("2026-09-14 17:03:10"),
            },
            {
                "id": 5010,
                "member_id": 276,
                "subject": "Update my address",
                "status": "waiting_for_member",
                "created_at": utc("2026-09-14 11:40:02"),
            },
            {
                "id": 5009,
                "member_id": 301,
                "subject": "Statement question",
                "status": "closed",
                "created_at": utc("2026-08-02 09:15:30"),
            },
            {
                "id": 5008,
                "member_id": 254,
                "subject": "Fee on my savings",
                "status": "waiting_for_bank",
                "created_at": utc("2026-09-13 19:22:51"),
            },
        ],
        "messages": [
            {
                "id": 9120,
                "conversation_id": 5012,
                "author_id": "301",
                "body": "My paycheck came the same day. Can you refund this?",
                "created_at": utc("2026-09-15 08:12:44"),
            },
            {
                "id": 9119,
                "conversation_id": 5011,
                "author_id": "S14",
                "body": "Thanks, we are checking your card now.",
                "created_at": utc("2026-09-14 17:40:12"),
            },
            {
                "id": 9118,
                "conversation_id": 5011,
                "author_id": "288",
                "body": "My card gets declined at the gas station.",
                "created_at": utc("2026-09-14 17:03:10"),
            },
            {
                "id": 9117,
                "conversation_id": 5010,
                "author_id": "276",
                "body": "I moved, how do I change my address?",
                "created_at": utc("2026-09-14 11:40:02"),
            },
            {
                "id": 9116,
                "conversation_id": 5008,
                "author_id": "254",
                "body": "Why was I charged $5 on my savings?",
                "created_at": utc("2026-09-13 19:22:51"),
            },
        ],
        "accounts": [
            {
                "id": 710,
                "member_id": 301,
                "credit_union_id": 7,
                "account_number": "884210",
                "is_primary": True,
            },
            {
                "id": 711,
                "member_id": 301,
                "credit_union_id": 7,
                "account_number": "884211",
                "is_primary": False,
            },
            {
                "id": 702,
                "member_id": 288,
                "credit_union_id": 7,
                "account_number": "883977",
                "is_primary": True,
            },
            {
                "id": 699,
                "member_id": 276,
                "credit_union_id": 7,
                "account_number": "883540",
                "is_primary": True,
            },
            {
                "id": 655,
                "member_id": 254,
                "credit_union_id": 9,
                "account_number": "510332",
                "is_primary": True,
            },
        ],
        "sub_accounts": [
            {
                "id": 1301,
                "account_id": 710,
                "type": "SAVINGS",
                "name": "Primary Savings",
                "balance": Decimal("215.40"),
                "available": Decimal("210.40"),
            },
            {
                "id": 1302,
                "account_id": 710,
                "type": "CHECKING",
                "name": "Everyday Checking",
                "balance": Decimal("1325.00"),
                "available": Decimal("1325.00"),
            },
            {
                "id": 1303,
                "account_id": 711,
                "type": "SAVINGS",
                "name": "Vacation Savings",
                "balance": Decimal("48.00"),
                "available": Decimal("48.00"),
            },
            {
                "id": 1290,
                "account_id": 702,
                "type": "CHECKING",
                "name": "Everyday Checking",
                "balance": Decimal("92.17"),
                "available": Decimal("92.17"),
            },
            {
                "id": 1255,
                "account_id": 655,
                "type": "SAVINGS",
                "name": "Primary Savings",
                "balance": Decimal("1040.00"),
                "available": Decimal("1040.00"),
            },
        ],
        "transactions": [
            {
                "id": 88001,
                "sub_account_id": 1302,
                "date": dt.date(2026, 9, 14),
                "description": "Withdrawal Debit Card CITY POWER & LIGHT",
                "amount": Decimal("-60.00"),
                "balance_after": Decimal("-40.00"),
                "posting_ref": "20260914-0000",
            },
            {
                "id": 88002,
                "sub_account_id": 1302,
                "date": dt.date(2026, 9, 14),
                "description": "Fee Withdrawal ; Courtesy Pay fee",
                "amount": Decimal("-35.00"),
                "balance_after": Decimal("-75.00"),
                "posting_ref": "20260914-0005",
            },
            {
                "id": 88003,
                "sub_account_id": 1302,
                "date": dt.date(2026, 9, 14),
                "description": "Deposit ACH ACME LOGISTICS*PAYROLL",
                "amount": Decimal("1400.00"),
                "balance_after": Decimal("1325.00"),
                "posting_ref": "20260914-0010",
            },
            {
                "id": 87410,
                "sub_account_id": 1302,
                "date": dt.date(2026, 3, 3),
                "description": "Deposit Fee Refund Courtesy Pay Fee",
                "amount": Decimal("35.00"),
                "balance_after": Decimal("412.10"),
                "posting_ref": "20260303-0002",
            },
            {
                "id": 87390,
                "sub_account_id": 1301,
                "date": dt.date(2026, 1, 20),
                "description": "Deposit Fee Refund Out of Network Fee",
                "amount": Decimal("5.00"),
                "balance_after": Decimal("880.45"),
                "posting_ref": "20260120-0002",
            },
        ],
        # The brief has no names (D-data-3). Ana's is used across the specs; the rest are made up.
        "member_profiles": [
            {"member_id": 301, "first_name": "Ana", "last_name": "Torres"},
            {"member_id": 288, "first_name": "Marcus", "last_name": "Reed"},
            {"member_id": 276, "first_name": "Priya", "last_name": "Nair"},
            {"member_id": 254, "first_name": "Daniel", "last_name": "Okafor"},
        ],
    },
)

SCENARIOS = [BRIEF]
