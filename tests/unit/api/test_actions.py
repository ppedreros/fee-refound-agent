"""Which decision actions the case allows (SPEC-api, "Allowed actions per status")."""

import pytest

from backend.api.actions import allowed_actions


@pytest.mark.parametrize(
    ("status", "recommendation", "has_draft", "has_fee", "over_limit", "expected"),
    [
        ("ready_to_refund", "refund", True, True, False, ["approve", "edit", "reject"]),
        ("recommend_no_refund", "no_refund", True, True, False, ["approve", "edit", "reject"]),
        ("needs_supervisor", "refund", True, True, True, ["reject", "reply_only"]),
        ("needs_your_call", "refund", True, True, False, ["approve", "edit", "reject"]),
        ("needs_your_call", "none", False, True, False, ["reply_only", "reject"]),
        ("needs_your_call", "none", False, False, False, ["reply_only"]),
        ("not_checked", "none", False, False, False, []),
        ("checking", "none", False, False, False, []),
        ("not_about_fee", "none", False, False, False, []),
        ("done", "refund", True, True, False, []),
    ],
)
def test_actions_per_status(
    status: str,
    recommendation: str,
    has_draft: bool,
    has_fee: bool,
    over_limit: bool,
    expected: list[str],
) -> None:
    actions = allowed_actions(
        status,
        recommendation,
        has_draft=has_draft,
        has_fee=has_fee,
        over_limit=over_limit,
    )

    assert actions == expected


def test_approve_needs_a_draft_but_edit_lets_luis_write_one() -> None:
    actions = allowed_actions(
        "needs_your_call", "refund", has_draft=False, has_fee=True, over_limit=False
    )

    assert actions == ["edit", "reject"]


@pytest.mark.parametrize(
    ("status", "recommendation", "expected"),
    [
        ("needs_your_call", "refund", ["reject"]),  # approve and edit would refund
        ("recommend_no_refund", "no_refund", ["approve", "edit"]),  # refund anyway would
        ("needs_your_call", "none", ["reply_only"]),
    ],
)
def test_nothing_that_would_refund_above_the_limit_is_offered(
    status: str, recommendation: str, expected: list[str]
) -> None:
    actions = allowed_actions(status, recommendation, has_draft=True, has_fee=True, over_limit=True)

    assert actions == expected
