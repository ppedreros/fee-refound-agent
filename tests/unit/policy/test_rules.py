"""The deterministic rules (SPEC-policy, "Rules"): table-driven, with the boundaries."""

import datetime as dt
from decimal import Decimal

import pytest

from backend.db.seed.scenarios import BRIEF
from backend.policy.loader import load_policy
from backend.policy.reasons import ReasonCode
from backend.policy.rules import (
    check_approval_limit,
    check_good_standing,
    check_not_already_refunded,
    check_yearly_limit,
    find_fee_candidates,
    verify_posting_order,
)
from backend.tools.descriptions import classify_description
from backend.tools.models import OurRefund, SubAccount, Transaction

FEE_DAY = dt.date(2026, 9, 14)
MESSAGE_AT = dt.datetime(2026, 9, 15, 8, 12, 44, tzinfo=dt.UTC)


def seeded_transactions() -> list[Transaction]:
    names = {row["id"]: row["name"] for row in BRIEF.rows["sub_accounts"]}
    transactions = []
    for row in BRIEF.rows["transactions"]:
        kind = classify_description(row["description"])
        transactions.append(
            Transaction(
                **row,
                sub_account_name=names[row["sub_account_id"]],
                kind=kind.kind,
                fee_type=kind.fee_type,
            )
        )
    return sorted(transactions, key=lambda t: t.posting_ref)


def seeded_sub_accounts() -> list[SubAccount]:
    return [
        SubAccount(**{k: row[k] for k in ("id", "type", "name", "balance", "available")})
        for row in BRIEF.rows["sub_accounts"]
        if row["account_id"] in (710, 711)
    ]


def txn(
    tid: int,
    seq: int,
    description: str,
    amount: str,
    balance_after: str,
    day: dt.date = FEE_DAY,
    sub_account_id: int = 1302,
) -> Transaction:
    kind = classify_description(description)
    return Transaction(
        id=tid,
        sub_account_id=sub_account_id,
        sub_account_name="Everyday Checking",
        date=day,
        description=description,
        amount=Decimal(amount),
        balance_after=Decimal(balance_after),
        posting_ref=f"{day:%Y%m%d}-{seq:04d}",
        kind=kind.kind,
        fee_type=kind.fee_type,
    )


BILL = "Withdrawal Debit Card CITY POWER & LIGHT"
FEE = "Fee Withdrawal ; Courtesy Pay fee"
PAYCHECK = "Deposit ACH ACME LOGISTICS*PAYROLL"
REFUND = "Deposit Fee Refund Courtesy Pay Fee"


# --- The worked example: Ana, fee 88002, with the shipped documents (AC2) ---


def test_anas_worked_example_passes_every_check() -> None:
    params = load_policy().params
    transactions = seeded_transactions()
    fee = next(t for t in transactions if t.id == 88002)
    same_day = [t for t in transactions if t.date == fee.date]
    refund_dates = [t.date for t in transactions if t.kind == "fee_refund"]

    results = [
        verify_posting_order(fee, same_day),
        check_yearly_limit(
            refund_dates, fee.date, params.max_refunds_in_window, params.window_days
        ),
        check_good_standing(seeded_sub_accounts()),
        check_not_already_refunded(fee, [], [t for t in transactions if t.kind == "fee_refund"]),
        check_approval_limit(-fee.amount, params.staff_limit_usd),
    ]

    assert [r.passed for r in results] == [True] * 5
    assert results[0].facts == {
        "deposit_date": FEE_DAY,
        "deposit_amount": Decimal("1400.00"),
        "deposit_kind": "payroll_deposit",
        "cause_kind": "card_payment",
        "deposit_posted_after_fee": True,
        "balance_if_deposit_first": Decimal("1360.00"),
    }
    assert results[1].facts == {"refunds_in_window": 2, "max_refunds": 3}


def test_the_fee_candidate_for_ana_is_88002() -> None:
    candidates = find_fee_candidates(seeded_transactions(), MESSAGE_AT)

    assert [c.id for c in candidates] == [88002]


# --- find_fee_candidates ---


@pytest.mark.parametrize(
    ("fee_day", "found"),
    [
        (dt.date(2026, 9, 15), True),  # the message's own day
        (dt.date(2026, 8, 16), True),  # 30 days before
        (dt.date(2026, 8, 15), False),  # 31 days before
        (dt.date(2026, 9, 16), False),  # after the message
    ],
)
def test_fee_candidates_are_fees_from_the_30_days_before_the_message(
    fee_day: dt.date, found: bool
) -> None:
    fee = txn(1, 5, FEE, "-35.00", "-75.00", day=fee_day)

    assert (find_fee_candidates([fee], MESSAGE_AT) == [fee]) is found


def test_refunds_and_other_debits_are_not_fee_candidates() -> None:
    others = [txn(1, 0, BILL, "-60.00", "-40.00"), txn(2, 1, REFUND, "35.00", "-5.00")]

    assert find_fee_candidates(others, MESSAGE_AT) == []


# --- verify_posting_order ---


def test_a_deposit_that_posted_later_the_same_day_and_would_have_covered_passes() -> None:
    day = [
        txn(1, 0, BILL, "-60.00", "-40.00"),
        txn(2, 5, FEE, "-35.00", "-75.00"),
        txn(3, 10, PAYCHECK, "1400.00", "1325.00"),
    ]

    result = verify_posting_order(day[1], day)

    assert result.passed
    assert result.clause_id == "fee-refund-policy#4"


def test_a_deposit_covering_exactly_the_payment_passes() -> None:
    day = [
        txn(1, 0, BILL, "-60.00", "-40.00"),
        txn(2, 5, FEE, "-35.00", "-75.00"),
        txn(3, 10, PAYCHECK, "40.00", "-35.00"),
    ]

    result = verify_posting_order(day[1], day)

    assert result.passed
    assert result.facts["balance_if_deposit_first"] == Decimal("0.00")


def test_no_deposit_that_day_fails_and_reports_the_next_one() -> None:
    day = [txn(1, 0, BILL, "-60.00", "-40.00"), txn(2, 5, FEE, "-35.00", "-75.00")]
    later = [txn(3, 0, PAYCHECK, "1400.00", "1325.00", day=dt.date(2026, 9, 16))]

    result = verify_posting_order(day[1], day, following=later)

    assert not result.passed
    assert result.reason is ReasonCode.DEPOSIT_NOT_SAME_DAY
    assert result.facts["next_deposit_date"] == dt.date(2026, 9, 16)


def test_a_deposit_that_would_not_have_covered_the_payment_fails() -> None:
    day = [
        txn(1, 0, BILL, "-60.00", "-40.00"),
        txn(2, 5, FEE, "-35.00", "-75.00"),
        txn(3, 10, PAYCHECK, "30.00", "-45.00"),
    ]

    result = verify_posting_order(day[1], day)

    assert result.reason is ReasonCode.DEPOSIT_NOT_SAME_DAY
    assert result.facts["balance_if_deposit_first"] == Decimal("-10.00")


def test_a_deposit_that_posted_before_the_fee_still_has_to_cover_the_payment() -> None:
    day = [
        txn(1, 0, PAYCHECK, "10.00", "30.00"),
        txn(2, 1, BILL, "-60.00", "-30.00"),
        txn(3, 5, FEE, "-35.00", "-65.00"),
    ]

    result = verify_posting_order(day[2], day)

    assert result.reason is ReasonCode.DEPOSIT_NOT_SAME_DAY
    assert result.facts["deposit_posted_after_fee"] is False


def test_a_fee_refund_is_not_a_deposit() -> None:
    day = [
        txn(1, 0, BILL, "-60.00", "-40.00"),
        txn(2, 5, FEE, "-35.00", "-75.00"),
        txn(3, 10, REFUND, "35.00", "-40.00"),
    ]

    assert verify_posting_order(day[1], day).reason is ReasonCode.DEPOSIT_NOT_SAME_DAY


def test_debits_after_the_fee_do_not_count_against_the_deposit() -> None:
    day = [
        txn(1, 0, BILL, "-60.00", "-40.00"),
        txn(2, 5, FEE, "-35.00", "-75.00"),
        txn(3, 6, "Withdrawal ATM", "-500.00", "-575.00"),
        txn(4, 10, PAYCHECK, "1400.00", "825.00"),
    ]

    result = verify_posting_order(day[1], day)

    assert result.passed
    assert result.facts["balance_if_deposit_first"] == Decimal("1360.00")


def test_other_sub_accounts_are_ignored() -> None:
    day = [
        txn(1, 0, BILL, "-60.00", "-40.00"),
        txn(2, 5, FEE, "-35.00", "-75.00"),
        txn(9, 1, PAYCHECK, "1400.00", "1615.40", sub_account_id=1301),
    ]

    assert verify_posting_order(day[1], day).reason is ReasonCode.DEPOSIT_NOT_SAME_DAY


def test_a_balance_chain_off_by_one_cent_is_a_data_mismatch() -> None:
    day = [
        txn(1, 0, BILL, "-60.00", "-40.00"),
        txn(2, 5, FEE, "-35.00", "-75.00"),
        txn(3, 10, PAYCHECK, "1400.00", "1325.01"),
    ]

    result = verify_posting_order(day[1], day)

    assert not result.passed
    assert result.reason is ReasonCode.DATA_MISMATCH


# --- check_yearly_limit ---


def days_before(days: int) -> dt.date:
    return FEE_DAY - dt.timedelta(days=days)


@pytest.mark.parametrize(
    ("refund_days_before", "passed"),
    [
        ([10, 200], True),  # Ana: 2 < 3
        ([10, 200, 300], False),  # exactly 3
        ([10, 200, 364], False),  # 364 days before counts
        ([10, 200, 365], True),  # 365 days before doesn't
        ([10, 200, -1], True),  # after the fee doesn't
        ([], True),
    ],
)
def test_the_yearly_limit(refund_days_before: list[int], passed: bool) -> None:
    result = check_yearly_limit([days_before(d) for d in refund_days_before], FEE_DAY, 3, 365)

    assert result.passed is passed
    assert result.clause_id == "fee-refund-policy#2"
    assert result.reason is (None if passed else ReasonCode.YEARLY_LIMIT)


# --- check_good_standing ---


def sub(type_: str, available: str, name: str = "Account") -> SubAccount:
    return SubAccount(
        id=1, type=type_, name=name, balance=Decimal(available), available=Decimal(available)
    )


@pytest.mark.parametrize(
    ("accounts", "passed"),
    [
        ([sub("CHECKING", "1325.00"), sub("SAVINGS", "0.00")], True),
        ([sub("CHECKING", "1325.00"), sub("LOAN", "-120.00", "Auto Loan")], False),
        ([sub("CHECKING", "-0.01")], False),
    ],
)
def test_good_standing(accounts: list[SubAccount], passed: bool) -> None:
    result = check_good_standing(accounts)

    assert result.passed is passed
    assert result.clause_id == "fee-refund-policy#3"
    assert result.reason is (None if passed else ReasonCode.NOT_GOOD_STANDING)


def test_good_standing_names_the_overdue_accounts() -> None:
    result = check_good_standing([sub("LOAN", "-120.00", "Auto Loan")])

    assert result.facts == {"overdue_accounts": ["Auto Loan"], "overdue_types": ["LOAN"]}


# --- check_not_already_refunded ---

THE_FEE = txn(88002, 5, FEE, "-35.00", "-75.00")


def core_refund(day: dt.date, amount: str = "35.00", description: str = REFUND) -> Transaction:
    return txn(5, 2, description, amount, "100.00", day=day)


@pytest.mark.parametrize(
    ("refund_txns", "passed"),
    [
        ([], True),
        ([core_refund(FEE_DAY + dt.timedelta(days=3))], False),
        ([core_refund(FEE_DAY + dt.timedelta(days=30))], False),
        ([core_refund(FEE_DAY + dt.timedelta(days=31))], True),
        ([core_refund(FEE_DAY - dt.timedelta(days=1))], True),  # before the fee
        ([core_refund(FEE_DAY + dt.timedelta(days=3), amount="5.00")], True),
        (
            [
                core_refund(
                    FEE_DAY + dt.timedelta(days=3),
                    description="Deposit Fee Refund Out of Network Fee",
                )
            ],
            True,
        ),
    ],
)
def test_already_refunded_in_the_core_system(refund_txns: list[Transaction], passed: bool) -> None:
    result = check_not_already_refunded(THE_FEE, [], refund_txns)

    assert result.passed is passed
    assert result.clause_id == "fee-refund-policy#5"


def test_already_refunded_by_this_app() -> None:
    ours = [
        OurRefund(
            fee_txn_id=88002,
            amount=Decimal("35.00"),
            refunded_at=dt.datetime(2026, 9, 16, tzinfo=dt.UTC),
        )
    ]

    result = check_not_already_refunded(THE_FEE, ours, [])

    assert result.reason is ReasonCode.ALREADY_REFUNDED
    assert result.facts["refunded_on"] == dt.date(2026, 9, 16)


# --- check_approval_limit ---


@pytest.mark.parametrize(("amount", "passed"), [("35.00", True), ("50.00", True), ("50.01", False)])
def test_the_staff_approval_limit(amount: str, passed: bool) -> None:
    result = check_approval_limit(Decimal(amount), Decimal("50"))

    assert result.passed is passed
    assert result.clause_id == "staff-approval-limits#1"
    assert result.reason is (None if passed else ReasonCode.OVER_LIMIT)
