"""Which decision actions a case allows right now (SPEC-api, "Allowed actions per status").

The API computes them so the UI never guesses, and the decision endpoint enforces the same list.
"""

from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Literal

type Action = Literal["approve", "edit", "reject", "reply_only"]

NO_ACTIONS = frozenset({"not_checked", "checking", "not_about_fee", "done"})


def allowed_actions(
    status: str,
    recommendation: str,
    *,
    has_draft: bool,
    has_fee: bool,
    over_limit: bool,
) -> list[Action]:
    if status in NO_ACTIONS:
        return []
    actions: list[Action]
    if status == "needs_supervisor":
        actions = ["reject", "reply_only"]
    elif recommendation in ("refund", "no_refund"):
        actions = ["approve", "edit", "reject"]
    else:
        actions = ["reply_only", "reject"] if has_fee else ["reply_only"]

    if not has_draft:  # Luis can still write a reply himself, which is `edit`
        actions = [a for a in actions if a != "approve"]
    if over_limit:  # nothing that would move money above Luis's limit (D-api-1)
        actions = [a for a in actions if not would_refund(a, recommendation)]
    return actions


def actions_for(status: str, result: Mapping[str, Any], staff_limit: Decimal) -> list[Action]:
    """The actions for a case from its latest run's stored `result`."""
    fee = result.get("fee")
    return allowed_actions(
        status,
        recommendation_of(result),
        has_draft=bool(result.get("draft")),
        has_fee=fee is not None,
        over_limit=fee is not None and fee_amount(fee) > staff_limit,
    )


def recommendation_of(result: Mapping[str, Any]) -> str:
    action: str = (result.get("recommendation") or {}).get("action", "none")
    return action


def fee_amount(fee: Mapping[str, Any]) -> Decimal:
    """What refunding the fee would move: the fee transaction's amount, as a positive number."""
    return -Decimal(fee["amount"])


def would_refund(action: Action, recommendation: str) -> bool:
    """`approve` and `edit` follow the recommendation; `reject` acts against it, so it refunds
    when the recommendation is not to refund (or there is none, with a fee)."""
    if action in ("approve", "edit"):
        return recommendation == "refund"
    if action == "reject":
        return recommendation != "refund"
    return False
