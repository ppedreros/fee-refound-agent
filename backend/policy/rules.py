"""The eligibility rules (SPEC-policy, "Rules"). Pure functions over typed inputs: none of them
reads the database or the clock. Each one declares the clause it implements."""

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal
from itertools import pairwise

from backend.policy.models import Fact, RuleResult
from backend.policy.reasons import ReasonCode
from backend.tools.models import OurRefund, SubAccount, Transaction

DEPOSIT_KINDS = frozenset({"payroll_deposit", "deposit"})  # fee refunds are not deposits
CORE_REFUND_MATCH_DAYS = 30  # D-policy-3


def find_fee_candidates(
    txns: Sequence[Transaction], message_at: dt.datetime, lookback_days: int = 30
) -> list[Transaction]:
    """Fees (kind `fee`, money out) posted in the `lookback_days` up to the message's day."""
    last = message_at.date()
    first = last - dt.timedelta(days=lookback_days)
    return [t for t in txns if t.kind == "fee" and t.amount < 0 and first <= t.date <= last]


def verify_posting_order(
    fee: Transaction,
    same_day_txns: Sequence[Transaction],
    following: Sequence[Transaction] = (),
) -> RuleResult:
    """D-policy-4: a non-refund deposit posted the same day would have covered the payment if it
    had posted first. Also checks that the day's balances add up (`data_mismatch`)."""
    clause = "fee-refund-policy#4"
    day = sorted(
        (t for t in same_day_txns if t.sub_account_id == fee.sub_account_id and t.date == fee.date),
        key=lambda t: t.posting_ref,
    )
    if not _balances_chain(day):
        return RuleResult(
            rule="verify_posting_order",
            passed=False,
            reason=ReasonCode.DATA_MISMATCH,
            clause_id=clause,
        )

    deposits = [t for t in day if t.kind in DEPOSIT_KINDS and t.amount > 0]
    if not deposits:
        facts: dict[str, Fact] = {}
        next_deposit = next(
            (
                t
                for t in sorted(following, key=lambda t: t.posting_ref)
                if t.sub_account_id == fee.sub_account_id
                and t.kind in DEPOSIT_KINDS
                and t.amount > 0
                and t.date > fee.date
            ),
            None,
        )
        if next_deposit is not None:
            facts["next_deposit_date"] = next_deposit.date
            facts["next_deposit_amount"] = next_deposit.amount
        return RuleResult(
            rule="verify_posting_order",
            passed=False,
            reason=ReasonCode.DEPOSIT_NOT_SAME_DAY,
            clause_id=clause,
            facts=facts,
        )

    opening = day[0].balance_after - day[0].amount
    # The debits up to the payment that caused the fee: every non-fee debit posted before it.
    debits_before_fee = sum(
        (
            t.amount
            for t in day
            if t.posting_ref < fee.posting_ref and t.amount < 0 and t.kind != "fee"
        ),
        Decimal("0"),
    )
    deposit_total = sum((t.amount for t in deposits), Decimal("0"))
    balance_if_deposit_first = opening + deposit_total + debits_before_fee
    passed = balance_if_deposit_first >= 0
    return RuleResult(
        rule="verify_posting_order",
        passed=passed,
        reason=None if passed else ReasonCode.DEPOSIT_NOT_SAME_DAY,
        clause_id=clause,
        facts={
            "deposit_date": deposits[0].date,
            "deposit_amount": deposit_total,
            "deposit_posted_after_fee": any(t.posting_ref > fee.posting_ref for t in deposits),
            "balance_if_deposit_first": balance_if_deposit_first,
        },
    )


def check_not_already_refunded(
    fee: Transaction, our_refunds: Sequence[OurRefund], refund_txns: Sequence[Transaction]
) -> RuleResult:
    """D-policy-3: no refund row of ours for this fee, and no core refund of the same fee type
    and amount within 30 days after the fee (core refunds don't name the fee they refund)."""
    clause = "fee-refund-policy#5"
    ours = next((r for r in our_refunds if r.fee_txn_id == fee.id), None)
    if ours is not None:
        return RuleResult(
            rule="check_not_already_refunded",
            passed=False,
            reason=ReasonCode.ALREADY_REFUNDED,
            clause_id=clause,
            facts={"refunded_on": ours.refunded_at.date()},
        )

    latest = fee.date + dt.timedelta(days=CORE_REFUND_MATCH_DAYS)
    core = next(
        (
            t
            for t in refund_txns
            if t.kind == "fee_refund"
            and t.fee_type == fee.fee_type
            and t.amount == -fee.amount
            and fee.date <= t.date <= latest
        ),
        None,
    )
    if core is not None:
        return RuleResult(
            rule="check_not_already_refunded",
            passed=False,
            reason=ReasonCode.ALREADY_REFUNDED,
            clause_id=clause,
            facts={"refunded_on": core.date},
        )
    return RuleResult(rule="check_not_already_refunded", passed=True, clause_id=clause)


def check_yearly_limit(
    refund_dates: Sequence[dt.date], fee_date: dt.date, max_refunds: int, window_days: int
) -> RuleResult:
    """D-policy-1/2: fewer than `max_refunds` fee refunds (any type) in the `window_days` ending
    on the fee date."""
    in_window = [d for d in refund_dates if 0 <= (fee_date - d).days < window_days]
    passed = len(in_window) < max_refunds
    return RuleResult(
        rule="check_yearly_limit",
        passed=passed,
        reason=None if passed else ReasonCode.YEARLY_LIMIT,
        clause_id="fee-refund-policy#2",
        facts={"refunds_in_window": len(in_window), "max_refunds": max_refunds},
    )


def check_good_standing(sub_accounts: Sequence[SubAccount]) -> RuleResult:
    """D-data-1: no sub-account has `available < 0` (for a loan, a past-due payment)."""
    overdue = [s for s in sub_accounts if s.available < 0]
    if not overdue:
        return RuleResult(rule="check_good_standing", passed=True, clause_id="fee-refund-policy#3")
    return RuleResult(
        rule="check_good_standing",
        passed=False,
        reason=ReasonCode.NOT_GOOD_STANDING,
        clause_id="fee-refund-policy#3",
        facts={
            "overdue_accounts": [s.name for s in overdue],
            "overdue_types": sorted({s.type for s in overdue}),
        },
    )


def check_approval_limit(amount: Decimal, staff_limit: Decimal) -> RuleResult:
    passed = amount <= staff_limit
    return RuleResult(
        rule="check_approval_limit",
        passed=passed,
        reason=None if passed else ReasonCode.OVER_LIMIT,
        clause_id="staff-approval-limits#1",
        facts={"amount": amount, "staff_limit": staff_limit},
    )


def _balances_chain(day: Sequence[Transaction]) -> bool:
    """Each balance_after is the previous one plus the amount, to the cent."""
    return all(
        current.balance_after == previous.balance_after + current.amount
        for previous, current in pairwise(day)
    )
