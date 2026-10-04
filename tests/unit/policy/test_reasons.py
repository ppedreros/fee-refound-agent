"""The reason catalogue and the summaries (SPEC-policy, "Reason catalogue")."""

import datetime as dt
import re
from decimal import Decimal

import pytest

from backend.policy.facts import Fact
from backend.policy.reasons import (
    Language,
    ReasonCode,
    render_counterfactual,
    render_reason,
    render_summary,
)

FEE_DAY = dt.date(2026, 9, 14)
LANGUAGES: tuple[Language, ...] = ("en", "es")

# Facts a real run could carry for each code, so every placeholder is exercised.
SAMPLE_FACTS: dict[ReasonCode, dict[str, Fact]] = {
    ReasonCode.FEE_AMBIGUOUS: {"candidate_count": 2, "fee_date": FEE_DAY},
    ReasonCode.ALREADY_REFUNDED: {"refunded_on": dt.date(2026, 3, 3)},
    ReasonCode.YEARLY_LIMIT: {"refunds_in_window": 3, "max_refunds": 3},
    ReasonCode.NOT_GOOD_STANDING: {"overdue_types": ["LOAN"], "overdue_accounts": ["Auto Loan"]},
    ReasonCode.DEPOSIT_NOT_SAME_DAY: {
        "fee_date": FEE_DAY,
        "next_deposit_date": dt.date(2026, 9, 16),
        "next_deposit_kind": "payroll_deposit",
    },
    ReasonCode.OVER_LIMIT: {"amount": Decimal("60.00"), "staff_limit": Decimal("50")},
}

ANA_DAY: dict[str, Fact] = {
    "deposit_date": FEE_DAY,
    "deposit_amount": Decimal("1400.00"),
    "deposit_kind": "payroll_deposit",
    "cause_kind": "card_payment",
    "deposit_posted_after_fee": True,
    "balance_if_deposit_first": Decimal("1360.00"),
}

FORBIDDEN = re.compile(
    r"\b(id|jev|llm|model|modelo|confidence|confianza|null|nulo|error|code|código|transaction id"
    r"|undefined|none)\b",
    re.IGNORECASE,
)
GENDERED = re.compile(r"\b(he|she|him|her|his|hers|él|ella|ellos|ellas)\b", re.IGNORECASE)


def every_rendering() -> list[tuple[ReasonCode, Language, str]]:
    texts = []
    for code in ReasonCode:
        for lang in LANGUAGES:
            rendered = render_reason(code, SAMPLE_FACTS.get(code, {}), lang, first_name="Ana")
            texts.append((code, lang, rendered.message))
            if rendered.next_step is not None:
                texts.append((code, lang, rendered.next_step))
    return texts


@pytest.mark.parametrize("lang", ["en", "es"])
@pytest.mark.parametrize("code", list(ReasonCode))
def test_every_code_renders_with_a_next_step(code: ReasonCode, lang: Language) -> None:
    rendered = render_reason(code, SAMPLE_FACTS.get(code, {}), lang, first_name="Ana")

    assert rendered.message.strip()
    assert "{" not in rendered.message and "}" not in rendered.message
    if code is ReasonCode.NOT_FEE_REQUEST:
        assert rendered.next_step is None  # routing: no banner, nothing to do
    else:
        assert rendered.next_step


def test_no_template_uses_internal_terms() -> None:
    leaks = [(c, lang, t) for c, lang, t in every_rendering() if FORBIDDEN.search(t)]

    assert leaks == []


def test_no_template_assumes_a_gender() -> None:
    gendered = [(c, lang, t) for c, lang, t in every_rendering() if GENDERED.search(t)]

    assert gendered == []


@pytest.mark.parametrize(
    ("code", "facts", "expected"),
    [
        (
            ReasonCode.FEE_AMBIGUOUS,
            SAMPLE_FACTS[ReasonCode.FEE_AMBIGUOUS],
            "Ana has 2 fees on Sep 14 and the message doesn't say which one.",
        ),
        (
            ReasonCode.ALREADY_REFUNDED,
            SAMPLE_FACTS[ReasonCode.ALREADY_REFUNDED],
            "This fee was already refunded on Mar 3.",
        ),
        (
            ReasonCode.YEARLY_LIMIT,
            SAMPLE_FACTS[ReasonCode.YEARLY_LIMIT],
            "Ana already had 3 refunds in the last 12 months.",
        ),
        (
            ReasonCode.NOT_GOOD_STANDING,
            SAMPLE_FACTS[ReasonCode.NOT_GOOD_STANDING],
            "Ana has an overdue loan balance.",
        ),
        (
            ReasonCode.NOT_GOOD_STANDING,
            {"overdue_types": ["CHECKING"], "overdue_accounts": ["Everyday Checking"]},
            "Ana has a balance below zero on Everyday Checking.",
        ),
        (
            ReasonCode.DEPOSIT_NOT_SAME_DAY,
            SAMPLE_FACTS[ReasonCode.DEPOSIT_NOT_SAME_DAY],
            "The paycheck arrived on Sep 16, two days after the fee.",
        ),
        (
            ReasonCode.DEPOSIT_NOT_SAME_DAY,
            {"fee_date": FEE_DAY, "deposit_date": FEE_DAY, "deposit_kind": "deposit"},
            "The deposit that day wouldn't have covered the payment.",
        ),
        (
            ReasonCode.DEPOSIT_NOT_SAME_DAY,
            {"fee_date": FEE_DAY},
            "No deposit arrived on the day of the fee.",
        ),
        (
            ReasonCode.MANIPULATION,
            {},
            "The message includes instructions aimed at us. I ignored them; the numbers below "
            "come from Ana's account only.",
        ),
    ],
)
def test_messages_fill_in_the_facts(
    code: ReasonCode, facts: dict[str, Fact], expected: str
) -> None:
    assert render_reason(code, facts, "en", first_name="Ana").message == expected


def test_the_next_step_for_a_policy_decline_offers_both_ways() -> None:
    rendered = render_reason(
        ReasonCode.YEARLY_LIMIT, SAMPLE_FACTS[ReasonCode.YEARLY_LIMIT], "en", first_name="Ana"
    )

    assert rendered.next_step == "Send the reply, or refund anyway"


def test_spanish_messages_are_spanish() -> None:
    rendered = render_reason(
        ReasonCode.YEARLY_LIMIT, SAMPLE_FACTS[ReasonCode.YEARLY_LIMIT], "es", first_name="Ana"
    )

    assert rendered.message == "Ana ya tuvo 3 reembolsos en los últimos 12 meses."


# --- Summaries ---


def test_anas_summary_explains_why_in_one_sentence() -> None:
    summary = render_summary("ready_to_refund", ANA_DAY, "en", first_name="Ana")

    assert summary == "The paycheck arrived the same day and the bill posted before it."


def test_anas_counterfactual() -> None:
    sentence = render_counterfactual(ANA_DAY, "en")

    assert sentence == "If the paycheck had posted first, the balance would have stayed at $1,360."


def test_the_summary_and_counterfactual_in_spanish() -> None:
    assert (
        render_summary("ready_to_refund", ANA_DAY, "es", first_name="Ana")
        == "La nómina llegó el mismo día y la factura se cobró antes."
    )
    assert (
        render_counterfactual(ANA_DAY, "es")
        == "Si la nómina se hubiera registrado primero, el saldo se habría quedado en $1,360."
    )


def test_a_plain_deposit_and_a_payment_are_named_as_such() -> None:
    facts = {**ANA_DAY, "deposit_kind": "deposit", "cause_kind": "withdrawal"}

    assert (
        render_summary("ready_to_refund", facts, "en", first_name="Ana")
        == "The deposit arrived the same day and the payment posted before it."
    )


def test_a_decline_summary_is_its_reason() -> None:
    summary = render_summary(
        "recommend_no_refund",
        SAMPLE_FACTS[ReasonCode.YEARLY_LIMIT],
        "en",
        first_name="Ana",
        reason=ReasonCode.YEARLY_LIMIT,
    )

    assert summary == "Ana already had 3 refunds in the last 12 months."


def test_a_supervisor_summary_says_the_refund_is_allowed_but_too_large() -> None:
    summary = render_summary(
        "needs_supervisor", SAMPLE_FACTS[ReasonCode.OVER_LIMIT], "en", first_name="Ana"
    )

    assert summary == "The policy allows this $60 refund, but it is above your $50 limit."


@pytest.mark.parametrize("status", ["needs_your_call", "not_about_fee", "checking", "done"])
def test_other_statuses_have_no_summary(status: str) -> None:
    assert render_summary(status, {}, "en", first_name="Ana") is None


def test_no_counterfactual_without_a_same_day_deposit() -> None:
    assert render_counterfactual({"fee_date": FEE_DAY}, "en") is None


@pytest.mark.parametrize(
    ("lang", "expected"),
    [
        ("en", "Ben has 2 recent fees and the message doesn't say which one."),
        ("es", "Ben tiene 2 cargos recientes y el mensaje no dice cuál."),
    ],
)
def test_fees_on_different_days_are_named_without_a_date(lang: Language, expected: str) -> None:
    rendered = render_reason(
        ReasonCode.FEE_AMBIGUOUS, {"candidate_count": 2}, lang, first_name="Ben"
    )

    assert rendered.message == expected
    assert rendered.next_step in ("Pick the fee", "Elige el cargo")
