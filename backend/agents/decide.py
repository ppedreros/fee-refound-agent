"""The deterministic decision (SPEC-agent, "Decision"): recommendation, status, and "clear".

No model decides anything here. `case_status` is also used by `finalize`, because a reason can
appear after `decide` (the drafter failing adds `drafter_down`).
"""

from collections.abc import Sequence
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from backend.agents.triage_rules import THRESHOLDS, Thresholds, Triage
from backend.policy.models import RuleResult
from backend.policy.reasons import GROUPS, ReasonCode, ReasonGroup
from backend.tools.models import Transaction

type RecommendationAction = Literal["refund", "no_refund", "none"]
type FeeSource = Literal["rule", "jev", "staff"]
type CaseOutcome = Literal[
    "ready_to_refund", "recommend_no_refund", "needs_supervisor", "needs_your_call", "not_about_fee"
]

# The decisive rule of a decline is the first failing one, in this order (SPEC-agent).
DECLINE_ORDER = (
    "check_not_already_refunded",
    "verify_posting_order",
    "check_yearly_limit",
    "check_good_standing",
)
NEEDS_YOUR_CALL = frozenset({ReasonGroup.UNCERTAINTY, ReasonGroup.FAILURE})
NO_USABLE_DATA = frozenset({ReasonCode.DATA_TIMEOUT, ReasonCode.DATA_MISMATCH})


class Recommendation(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: RecommendationAction
    amount: Decimal | None = None  # always the fee's amount, never anything from the message
    fee_txn_id: int | None = None


class Decision(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: CaseOutcome
    recommendation: Recommendation
    decisive_rule: str | None  # the rule whose clause the case quotes
    decisive_clause_id: str | None
    reasons: tuple[ReasonCode, ...]  # what Luis sees, in order; notes excluded
    notes: tuple[ReasonCode, ...]
    clear: bool
    would_auto_approve: bool


def decide(
    *,
    triage: Triage,
    fee: Transaction | None,
    fee_source: FeeSource | None,
    checks: Sequence[RuleResult],
    reasons: Sequence[ReasonCode],
    thresholds: Thresholds = THRESHOLDS,
) -> Decision:
    by_rule = {check.rule: check for check in checks}
    codes = [*triage.reasons, *reasons]
    codes += [c.reason for c in checks if c.reason is ReasonCode.DATA_MISMATCH]

    decisive: RuleResult | None = None
    if fee is None or not triage.about_fee or NO_USABLE_DATA & set(codes):
        action: RecommendationAction = "none"
    elif ReasonCode.FEE_QUESTION in codes:
        # We don't recommend refunding what wasn't asked for, and there is no refund to decline:
        # the checks stay visible as evidence, and the fee schedule explains the fee (D-agent-1).
        action = "none"
    else:
        failed = [by_rule[r] for r in DECLINE_ORDER if r in by_rule and not by_rule[r].passed]
        if failed:
            action, decisive = "no_refund", failed[0]
            codes.append(_reason(decisive))
        else:
            action = "refund"
            decisive = by_rule.get("verify_posting_order")
            limit = by_rule.get("check_approval_limit")
            if limit is not None and not limit.passed:
                codes.append(_reason(limit))
                decisive = limit

    status = case_status(codes, action, about_fee=triage.about_fee)
    recommendation = Recommendation(
        action=action,
        amount=-fee.amount if fee is not None and action != "none" else None,
        fee_txn_id=fee.id if fee is not None else None,
    )
    posting = by_rule.get("verify_posting_order")
    clear = (
        status == "ready_to_refund"
        and triage.classifier_used == "jev"
        and triage.intent_confidence is not None
        and triage.intent_confidence >= thresholds.intent_min_confidence
        and fee_source == "rule"
        and posting is not None
        and posting.passed
        and triage.manipulation_p_yes is not None
        and triage.manipulation_p_yes <= thresholds.manipulation_clear_max_p_yes
        and recommendation.amount is not None
        and recommendation.amount <= thresholds.clear_max_amount_usd
    )
    unique = list(dict.fromkeys(codes))
    return Decision(
        status=status,
        recommendation=recommendation,
        decisive_rule=decisive.rule if decisive is not None else None,
        decisive_clause_id=decisive.clause_id if decisive is not None else None,
        reasons=tuple(c for c in unique if GROUPS[c] is not ReasonGroup.NOTE),
        notes=tuple(c for c in unique if GROUPS[c] is ReasonGroup.NOTE),
        clear=clear,
        would_auto_approve=clear,
    )


def case_status(
    codes: Sequence[ReasonCode], action: RecommendationAction, *, about_fee: bool
) -> CaseOutcome:
    """Exactly one status, in the order of precedence of D4a. Notes never change it."""
    if not about_fee:
        return "not_about_fee"
    if any(GROUPS[code] in NEEDS_YOUR_CALL for code in codes):
        return "needs_your_call"
    if action == "refund" and ReasonCode.OVER_LIMIT in codes:
        return "needs_supervisor"
    if action == "no_refund":
        return "recommend_no_refund"
    if action == "refund":
        return "ready_to_refund"
    return "needs_your_call"  # no recommendation without a reason: Luis decides


def _reason(result: RuleResult) -> ReasonCode:
    if result.reason is None:
        raise ValueError(f"{result.rule} failed without a reason")
    return result.reason
