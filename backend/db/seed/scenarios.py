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


# --- Scenarios 2-18 (SPEC-data, "Seed"). Ids follow one scheme, so they never collide with the
# brief's: conversation 5100+n, member 400+n, account 7000+10n+k, sub-account 1400+10n+k,
# transaction 90000+100n+k, message 9200+10n+k. Account numbers are "77" + n + k. ---

CREDIT_UNION = 7
MESSAGE_AT = "2026-09-15 09:00:00"


def member_scenario(
    n: int,
    title: str,
    *,
    name: tuple[str, str],
    subject: str,
    messages: list[str],
    sub_accounts: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
    received_at: str = MESSAGE_AT,
) -> Scenario:
    """One member with one open conversation. Messages are the member's, a minute apart."""
    member = 400 + n
    start = utc(received_at)
    accounts = sorted({sub["account_id"] for sub in sub_accounts})
    return Scenario(
        number=n,
        title=title,
        rows={
            "conversations": [
                {
                    "id": 5100 + n,
                    "member_id": member,
                    "subject": subject,
                    "status": "waiting_for_bank",
                    "created_at": start,
                }
            ],
            "messages": [
                {
                    "id": 9200 + 10 * n + k,
                    "conversation_id": 5100 + n,
                    "author_id": str(member),
                    "body": body,
                    "created_at": start + dt.timedelta(minutes=k - 1),
                }
                for k, body in enumerate(messages, start=1)
            ],
            "accounts": [
                {
                    "id": account,
                    "member_id": member,
                    "credit_union_id": CREDIT_UNION,
                    "account_number": f"77{n:02d}{account % 10:02d}",
                    "is_primary": account % 10 == 1,
                }
                for account in accounts
            ],
            "sub_accounts": sub_accounts,
            "transactions": transactions,
            "member_profiles": [{"member_id": member, "first_name": name[0], "last_name": name[1]}],
        },
    )


def sub_account(
    n: int,
    k: int,
    kind: str,
    name: str,
    balance: str,
    available: str | None = None,
    *,
    account: int = 1,
) -> dict[str, Any]:
    return {
        "id": 1400 + 10 * n + k,
        "account_id": 7000 + 10 * n + account,
        "type": kind,
        "name": name,
        "balance": Decimal(balance),
        "available": Decimal(available if available is not None else balance),
    }


def txn(
    n: int, k: int, sub: int, day: str, sequence: int, description: str, amount: str, after: str
) -> dict[str, Any]:
    """Transaction k of scenario n on sub-account k=`sub`, posted `sequence`-th on `day`."""
    date = dt.date.fromisoformat(day)
    return {
        "id": 90000 + 100 * n + k,
        "sub_account_id": 1400 + 10 * n + sub,
        "date": date,
        "description": description,
        "amount": Decimal(amount),
        "balance_after": Decimal(after),
        "posting_ref": f"{date:%Y%m%d}-{sequence:04d}",
    }


COURTESY_PAY = "Fee Withdrawal ; Courtesy Pay fee"
EXTENDED_OVERDRAFT = "Fee Withdrawal ; Extended Overdraft fee"
COURTESY_PAY_REFUND = "Deposit Fee Refund Courtesy Pay Fee"


def same_day_paycheck(
    n: int, day: str, *, bill: str = "Withdrawal Debit Card CITY POWER & LIGHT"
) -> list[dict[str, Any]]:
    """Ana's pattern: a $60 bill takes the balance below zero, the $35 fee follows, and the
    paycheck posts last the same day. With it first, the balance would have stayed positive."""
    return [
        txn(n, 1, 1, day, 0, bill, "-60.00", "-40.00"),
        txn(n, 2, 1, day, 5, COURTESY_PAY, "-35.00", "-75.00"),
        txn(n, 3, 1, day, 10, "Deposit ACH NORTHWIND FOODS*PAYROLL", "1250.00", "1175.00"),
    ]


def checking(n: int, balance: str = "1175.00") -> dict[str, Any]:
    return sub_account(n, 1, "CHECKING", "Everyday Checking", balance)


SCENARIO_6 = member_scenario(
    6,
    "Three fee refunds already in the 12 months before the fee: we recommend not refunding",
    name=("Grace", "Kim"),
    subject="Overdraft fee again",
    messages=["My paycheck came in the same day as this overdraft fee. Could you refund it?"],
    sub_accounts=[checking(6)],
    transactions=[
        txn(6, 4, 1, "2025-11-10", 2, COURTESY_PAY_REFUND, "35.00", "410.00"),
        txn(6, 5, 1, "2026-02-03", 2, COURTESY_PAY_REFUND, "35.00", "365.00"),
        txn(6, 6, 1, "2026-06-20", 2, COURTESY_PAY_REFUND, "35.00", "290.00"),
        *same_day_paycheck(6, "2026-09-14"),
    ],
)

SCENARIO_7 = member_scenario(
    7,
    "The paycheck arrived two days after the fee: we recommend not refunding",
    name=("Omar", "Haddad"),
    subject="Fee before payday",
    messages=["The overdraft fee hit right before my paycheck arrived. Can you take it back?"],
    sub_accounts=[checking(7, "885.00")],
    transactions=[
        txn(
            7, 1, 1, "2026-09-12", 0, "Withdrawal Debit Card CITY POWER & LIGHT", "-60.00", "-20.00"
        ),
        txn(7, 2, 1, "2026-09-12", 5, COURTESY_PAY, "-35.00", "-55.00"),
        txn(7, 3, 1, "2026-09-14", 3, "Deposit ACH NORTHWIND FOODS*PAYROLL", "940.00", "885.00"),
    ],
)

SCENARIO_8 = member_scenario(
    8,
    "A past-due loan payment: we recommend not refunding",
    name=("Lucia", "Moreno"),
    subject="Overdraft fee",
    messages=["My salary arrived the same day as the overdraft fee. Can you refund the fee?"],
    sub_accounts=[
        checking(8),
        sub_account(8, 2, "LOAN", "Auto Loan", "8400.00", "-150.00", account=2),
    ],
    transactions=same_day_paycheck(8, "2026-09-14"),
)

SCENARIO_11 = member_scenario(
    11,
    "The fee was already refunded: we recommend not refunding",
    name=("Ethan", "Brooks"),
    subject="Refund the overdraft fee",
    messages=[
        "I was charged an overdraft fee on Sep 10 even though my paycheck came that day. "
        "Please refund it."
    ],
    sub_accounts=[checking(11, "1210.00")],
    transactions=[
        *same_day_paycheck(11, "2026-09-10"),
        txn(11, 4, 1, "2026-09-11", 1, COURTESY_PAY_REFUND, "35.00", "1210.00"),
    ],
)

SCENARIO_17 = member_scenario(
    17,
    "A $60 fee, above Luis's $50 approval limit: needs supervisor approval",
    name=("Nora", "Fischer"),
    subject="Overdraft charge",
    messages=["My paycheck landed the same day, but I was still charged $60. Can you refund it?"],
    sub_accounts=[checking(17, "1290.00")],
    transactions=[
        txn(
            17,
            1,
            1,
            "2026-09-14",
            0,
            "Withdrawal Debit Card CITY POWER & LIGHT",
            "-100.00",
            "-50.00",
        ),
        txn(17, 2, 1, "2026-09-14", 5, EXTENDED_OVERDRAFT, "-60.00", "-110.00"),
        txn(
            17, 3, 1, "2026-09-14", 10, "Deposit ACH NORTHWIND FOODS*PAYROLL", "1400.00", "1290.00"
        ),
    ],
)


def two_fees(n: int, day: str) -> list[dict[str, Any]]:
    """Two bills, two $35 fees, then the paycheck, all on one day: each fee follows its bill."""
    return [
        txn(n, 1, 1, day, 0, "Withdrawal Debit Card CITY POWER & LIGHT", "-60.00", "-40.00"),
        txn(n, 2, 1, day, 5, COURTESY_PAY, "-35.00", "-75.00"),
        txn(n, 3, 1, day, 8, "Withdrawal Debit Card STREAMFLIX", "-15.99", "-90.99"),
        txn(n, 4, 1, day, 9, COURTESY_PAY, "-35.00", "-125.99"),
        txn(n, 5, 1, day, 10, "Deposit ACH NORTHWIND FOODS*PAYROLL", "1250.00", "1124.01"),
    ]


SCENARIO_9 = member_scenario(
    9,
    "Two fees on the same day, and the message doesn't say which: needs your call",
    name=("Ben", "Carter"),
    subject="Overdraft fees",
    messages=["I got hit with overdraft fees again. Can you refund the fee?"],
    sub_accounts=[checking(9, "1124.01")],
    transactions=two_fees(9, "2026-09-14"),
)

SCENARIO_10 = member_scenario(
    10,
    "Two fees on the same day; the message names the electric bill: ready to refund",
    name=("Hannah", "Weiss"),
    subject="Fee after my electric bill",
    messages=[
        "My electric bill payment pushed me into overdraft and I got a fee for it, even though "
        "my paycheck came the same day. Can you refund that one?"
    ],
    sub_accounts=[checking(10, "1124.01")],
    transactions=two_fees(10, "2026-09-14"),
)

SCENARIO_15 = member_scenario(
    15,
    "A refund request with no fee in the last 30 days: needs your call",
    name=("Isabel", "Ruiz"),
    subject="Overdraft fee",
    messages=["Can you refund the overdraft fee I was charged?"],
    sub_accounts=[checking(15, "425.00")],
    transactions=[
        txn(
            15,
            1,
            1,
            "2026-07-20",
            0,
            "Withdrawal Debit Card CITY POWER & LIGHT",
            "-50.00",
            "-40.00",
        ),
        txn(15, 2, 1, "2026-07-20", 5, COURTESY_PAY, "-35.00", "-75.00"),
        txn(15, 3, 1, "2026-09-10", 2, "Deposit Mobile Check", "500.00", "425.00"),
    ],
)

# Scenario 5 is the brief's conversation 5008 ("Why was I charged $5 on my savings?"). The brief
# has no transaction for it, so the fee is added on Daniel's Primary Savings (1255), whose balance
# it already left at $1,040.
SCENARIO_5 = Scenario(
    number=5,
    title="A question about a $5 savings fee, not a refund request: needs your call",
    rows={
        "transactions": [
            {
                "id": 90501,
                "sub_account_id": 1255,
                "date": dt.date(2026, 9, 1),
                "description": "Fee Withdrawal ; Savings Below Minimum Balance fee",
                "amount": Decimal("-5.00"),
                "balance_after": Decimal("1040.00"),
                "posting_ref": "20260901-0003",
            }
        ]
    },
)

SCENARIOS = [
    BRIEF,
    SCENARIO_5,
    SCENARIO_6,
    SCENARIO_7,
    SCENARIO_8,
    SCENARIO_9,
    SCENARIO_10,
    SCENARIO_11,
    SCENARIO_15,
    SCENARIO_17,
]
