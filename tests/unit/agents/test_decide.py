"""Recommendation, status precedence and "clear" (SPEC-agent, "Decision")."""

import datetime as dt
import itertools
from collections.abc import Callable
from decimal import Decimal

import pytest

from backend.agents.decide import Decision, FeeSource, RecommendationAction, case_status, decide
from backend.agents.triage_rules import Triage
from backend.policy.models import RuleResult
from backend.policy.reasons import GROUPS, ReasonCode, ReasonGroup
from backend.tools.models import Transaction

R = ReasonCode
FEE_DAY = dt.date(2026, 9, 14)
ACTIONS: tuple[RecommendationAction, ...] = ("refund", "no_refund", "none")


def fee(amount: str = "-35.00", tid: int = 88002) -> Transaction:
    return Transaction(
        id=tid,
        sub_account_id=1302,
        sub_account_name="Everyday Checking",
        date=FEE_DAY,
        description="Fee Withdrawal ; Courtesy Pay fee",
        amount=Decimal(amount),
        balance_after=Decimal("-75.00"),
        posting_ref="20260914-0005",
        kind="fee",
        fee_type="Courtesy Pay",
    )


def triage(**changes: object) -> Triage:
    base = Triage(
        about_fee=True,
        topic="fee_refund_request",
        classifier_used="jev",
        intent_confidence=1.0,
        language="en",
        tone="casual",
        manipulation_p_yes=0.03,
        reasons=(),
    )
    return base.model_copy(update=changes)


def checks(**failing: ReasonCode) -> list[RuleResult]:
    """Every rule passing, except the ones named as rule=reason."""
    rules = {
        "check_not_already_refunded": "fee-refund-policy#5",
        "verify_posting_order": "fee-refund-policy#4",
        "check_yearly_limit": "fee-refund-policy#2",
        "check_good_standing": "fee-refund-policy#3",
        "check_approval_limit": "staff-approval-limits#1",
    }
    return [
        RuleResult(
            rule=rule,
            passed=rule not in failing,
            reason=failing.get(rule),
            clause_id=clause,
        )
        for rule, clause in rules.items()
    ]


# --- Ana ---


def test_ana_is_ready_to_refund_and_clear() -> None:
    decision = decide(triage=triage(), fee=fee(), fee_source="rule", checks=checks(), reasons=())

    assert decision.status == "ready_to_refund"
    assert decision.recommendation.action == "refund"
    assert decision.recommendation.amount == Decimal("35.00")
    assert decision.recommendation.fee_txn_id == 88002
    assert decision.decisive_clause_id == "fee-refund-policy#4"
    assert decision.clear is True
    assert decision.would_auto_approve is True


def ana_with(
    triage_: Triage | None = None, fee_: Transaction | None = None, source: FeeSource = "rule"
) -> Decision:
    return decide(
        triage=triage_ or triage(),
        fee=fee_ or fee(),
        fee_source=source,
        checks=checks(),
        reasons=(),
    )


NOT_CLEAR = {
    "backup classifier": lambda: ana_with(triage(classifier_used="backup", intent_confidence=None)),
    "fee chosen by Jev": lambda: ana_with(source="jev"),
    "fee picked by staff": lambda: ana_with(source="staff"),
    "above $35": lambda: ana_with(fee_=fee("-36.00")),  # still within Luis's $50
    "manipulation unknown": lambda: ana_with(triage(manipulation_p_yes=None)),
}


@pytest.mark.parametrize("make", NOT_CLEAR.values(), ids=NOT_CLEAR.keys())
def test_any_missing_condition_makes_the_case_not_clear(make: Callable[[], Decision]) -> None:
    decision = make()

    assert decision.clear is False
    assert decision.would_auto_approve is False


# --- Recommendation ---


@pytest.mark.parametrize(
    ("failing", "decisive"),
    [
        (
            {
                "check_not_already_refunded": R.ALREADY_REFUNDED,
                "check_yearly_limit": R.YEARLY_LIMIT,
            },
            R.ALREADY_REFUNDED,
        ),
        (
            {"verify_posting_order": R.DEPOSIT_NOT_SAME_DAY, "check_yearly_limit": R.YEARLY_LIMIT},
            R.DEPOSIT_NOT_SAME_DAY,
        ),
        (
            {"check_yearly_limit": R.YEARLY_LIMIT, "check_good_standing": R.NOT_GOOD_STANDING},
            R.YEARLY_LIMIT,
        ),
        ({"check_good_standing": R.NOT_GOOD_STANDING}, R.NOT_GOOD_STANDING),
    ],
)
def test_the_first_failing_policy_rule_decides(
    failing: dict[str, ReasonCode], decisive: ReasonCode
) -> None:
    decision = decide(
        triage=triage(), fee=fee(), fee_source="rule", checks=checks(**failing), reasons=()
    )

    assert decision.status == "recommend_no_refund"
    assert decision.recommendation.action == "no_refund"
    assert decision.reasons == (decisive,)


def test_a_refund_above_the_limit_needs_a_supervisor() -> None:
    decision = decide(
        triage=triage(),
        fee=fee("-60.00"),
        fee_source="rule",
        checks=checks(check_approval_limit=R.OVER_LIMIT),
        reasons=(),
    )

    assert decision.status == "needs_supervisor"
    assert decision.recommendation.action == "refund"
    assert decision.decisive_clause_id == "staff-approval-limits#1"


def test_a_decline_above_the_limit_is_still_a_decline() -> None:
    decision = decide(
        triage=triage(),
        fee=fee("-60.00"),
        fee_source="rule",
        checks=checks(check_yearly_limit=R.YEARLY_LIMIT, check_approval_limit=R.OVER_LIMIT),
        reasons=(),
    )

    assert decision.status == "recommend_no_refund"


def test_a_fee_question_gets_no_recommendation_but_keeps_the_fee() -> None:
    decision = decide(
        triage=triage(topic="fee_question", reasons=(R.FEE_QUESTION,)),
        fee=fee(),
        fee_source="rule",
        checks=checks(),
        reasons=(),
    )

    assert decision.status == "needs_your_call"
    assert decision.recommendation.action == "none"
    assert decision.recommendation.fee_txn_id == 88002


def test_no_fee_means_no_recommendation() -> None:
    decision = decide(
        triage=triage(), fee=None, fee_source=None, checks=[], reasons=(R.FEE_NOT_FOUND,)
    )

    assert (decision.status, decision.recommendation.action) == ("needs_your_call", "none")


def test_a_data_mismatch_means_no_recommendation() -> None:
    decision = decide(
        triage=triage(),
        fee=fee(),
        fee_source="rule",
        checks=checks(verify_posting_order=R.DATA_MISMATCH),
        reasons=(),
    )

    assert decision.status == "needs_your_call"
    assert decision.recommendation.action == "none"
    assert R.DATA_MISMATCH in decision.reasons


def test_a_message_not_about_a_fee_exits_early() -> None:
    decision = decide(
        triage=triage(about_fee=False, topic="card_issue", reasons=(R.NOT_FEE_REQUEST,)),
        fee=None,
        fee_source=None,
        checks=[],
        reasons=(),
    )

    assert decision.status == "not_about_fee"


def test_classifier_down_keeps_the_recommendation() -> None:
    decision = decide(
        triage=triage(classifier_used=None, intent_confidence=None, reasons=(R.CLASSIFIER_DOWN,)),
        fee=fee(),
        fee_source="rule",
        checks=checks(),
        reasons=(),
    )

    assert decision.status == "needs_your_call"
    assert decision.recommendation.action == "refund"


# --- Status precedence, for every pair of competing codes ---

MANUAL = [c for c in R if GROUPS[c] in (ReasonGroup.UNCERTAINTY, ReasonGroup.FAILURE)]
POLICY = [c for c in R if GROUPS[c] is ReasonGroup.POLICY]


@pytest.mark.parametrize(("first", "second"), list(itertools.combinations(MANUAL, 2)))
def test_two_uncertainty_or_failure_codes_need_your_call(
    first: ReasonCode, second: ReasonCode
) -> None:
    assert case_status([first, second], "refund", about_fee=True) == "needs_your_call"


@pytest.mark.parametrize(("manual", "policy"), list(itertools.product(MANUAL, POLICY)))
def test_an_uncertainty_or_failure_beats_any_policy_outcome(
    manual: ReasonCode, policy: ReasonCode
) -> None:
    for action in ACTIONS:
        assert case_status([policy, manual], action, about_fee=True) == "needs_your_call"


@pytest.mark.parametrize(
    ("codes", "action", "status"),
    [
        ([R.OVER_LIMIT], "refund", "needs_supervisor"),
        ([R.OVER_LIMIT, R.YEARLY_LIMIT], "no_refund", "recommend_no_refund"),
        ([R.YEARLY_LIMIT], "no_refund", "recommend_no_refund"),
        ([], "refund", "ready_to_refund"),
        ([R.CLASSIFIED_WITH_BACKUP], "refund", "ready_to_refund"),  # a note changes nothing
        ([R.CLASSIFIED_WITH_BACKUP, R.YEARLY_LIMIT], "no_refund", "recommend_no_refund"),
        ([R.DRAFTER_DOWN], "refund", "needs_your_call"),
        ([R.CLASSIFIER_DOWN], "refund", "needs_your_call"),
        ([], "none", "needs_your_call"),
    ],
)
def test_status_precedence(
    codes: list[ReasonCode], action: RecommendationAction, status: str
) -> None:
    assert case_status(codes, action, about_fee=True) == status


def test_the_early_exit_wins_over_everything() -> None:
    assert case_status([R.MANIPULATION], "none", about_fee=False) == "not_about_fee"
