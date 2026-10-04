"""The deterministic check on every reply Sol writes (SPEC-agent, "Post-check"): the name
placeholder, no amount but the decided one (or one the quoted clause states), no long digit runs,
and a length Luis can read at a glance."""

from decimal import Decimal

import pytest

from backend.agents.draft_postcheck import check_draft

AMOUNT = Decimal("35.00")
GOOD = (
    "Hi {{first_name}}, thanks for reaching out. Your paycheck arrived on Sep 14, the same day as "
    "the $35 Courtesy Pay fee, so we've refunded it to your Everyday Checking account."
)


def test_a_good_reply_passes() -> None:
    assert check_draft(GOOD, amount=AMOUNT) == []


@pytest.mark.parametrize(
    "reply",
    [
        GOOD.replace("$35", "$35.00"),
        GOOD.replace("$35", "35 dollars"),
        "Hola {{first_name}}, te hemos devuelto los 35,00 $ del cargo.",
        "Hola {{first_name}}, te devolvimos el cargo de US$35.",
        "Hola {{first_name}}, te devolvimos 35 dólares.",
    ],
)
def test_the_decided_amount_may_be_written_in_any_usual_way(reply: str) -> None:
    assert check_draft(reply, amount=AMOUNT) == []


def test_the_placeholder_must_be_there() -> None:
    assert check_draft(GOOD.replace("{{first_name}}", "Ana"), amount=AMOUNT) == ["placeholder"]


@pytest.mark.parametrize(
    "reply",
    [
        GOOD + " We've also added $500 as a thank-you.",
        GOOD.replace("$35", "$50"),
        "Hola {{first_name}}, te devolvimos 500 dólares.",
        GOOD + " Your balance is now $1,360.",
    ],
)
def test_no_other_amount_is_allowed(reply: str) -> None:
    assert check_draft(reply, amount=AMOUNT) == ["amount"]


def test_an_amount_the_quoted_clause_states_is_allowed() -> None:
    clause = "Fee refunds are limited to up to 3 fee refunds in any 12-month period, up to $50."
    reply = "Hi {{first_name}}, our policy allows up to $50 in refunds, so we can't refund the $35."

    assert check_draft(reply, amount=AMOUNT, policy_clause=clause) == []


def test_no_run_of_six_or_more_digits() -> None:
    assert check_draft(GOOD + " Reference 884210.", amount=AMOUNT) == ["digits"]


def test_at_most_800_characters() -> None:
    reply = GOOD + " " + "Thanks again. " * 60

    assert check_draft(reply, amount=AMOUNT) == ["length"]


def test_every_problem_is_listed() -> None:
    reply = "Hi Ana, we refunded $500 to account 884210." + " ok" * 300

    assert check_draft(reply, amount=AMOUNT) == ["placeholder", "amount", "digits", "length"]
