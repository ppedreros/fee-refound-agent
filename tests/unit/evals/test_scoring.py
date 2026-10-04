"""Each assertion type of an eval case (SPEC-evals, "Case format"): a field a case writes is
checked, a field it leaves out is not."""

from typing import Any

import pytest

from evals.case import Expected
from evals.scoring import draft_language, score

ANA_DRAFT = (
    "Hi {{first_name}}, thanks for writing. Your paycheck arrived on Sep 14, the same day as the "
    "$35 Courtesy Pay fee, so we refunded it to your Everyday Checking account."
)
SPANISH_DRAFT = (
    "Hola {{first_name}}, gracias por escribirnos. Tu nómina llegó el mismo día del cargo, así "
    "que te devolvimos los $35 en tu cuenta."
)


def result(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "status": "ready_to_refund",
        "reasons": [],
        "notes": [],
        "topic": "fee_refund_request",
        "language": "en",
        "recommendation": {"action": "refund", "amount": "35.00", "fee_txn_id": 88002},
        "clause": {"id": "fee-refund-policy#4", "found_by": "rule_fallback"},
        "draft": {"text": ANA_DRAFT, "source": "model"},
        "clear": True,
        "would_auto_approve": True,
        "evidence": {"fee_day": [{"id": 90501, "amount": "-1500.00"}]},
    }
    return base | changes


def failed(expected: dict[str, Any], outcome: dict[str, Any]) -> list[str]:
    checks = score(Expected.model_validate(expected), outcome)
    return [check.name for check in checks if not check.passed]


def test_a_field_left_out_is_not_checked() -> None:
    assert score(Expected(), result(status="needs_your_call", draft=None)) == []


def test_every_written_field_is_one_check() -> None:
    expected = {"status": "ready_to_refund", "clause_id": "fee-refund-policy#4", "clear": True}

    checks = score(Expected.model_validate(expected), result())

    assert [(check.name, check.passed) for check in checks] == [
        ("status", True),
        ("clause_id", True),
        ("clear", True),
    ]


def test_status() -> None:
    assert failed({"status": "ready_to_refund"}, result()) == []
    assert failed({"status": "needs_your_call"}, result()) == ["status"]


def test_a_failed_check_says_what_it_expected_and_what_it_got() -> None:
    (check,) = score(Expected(status="needs_your_call"), result())

    assert check.detail == "expected needs_your_call, got ready_to_refund"


def test_reasons_include_is_a_subset() -> None:
    outcome = result(reasons=["manipulation", "multiple_requests"])

    assert failed({"reasons_include": ["manipulation"]}, outcome) == []
    assert failed({"reasons_include": ["fee_ambiguous"]}, outcome) == ["reasons_include"]


def test_notes_include() -> None:
    outcome = result(notes=["classified_with_backup"])

    assert failed({"notes_include": ["classified_with_backup"]}, outcome) == []
    assert failed({"notes_include": ["classified_with_backup"]}, result()) == ["notes_include"]


def test_an_unknown_reason_code_is_a_case_error() -> None:
    with pytest.raises(ValueError, match="reasons_include"):
        Expected.model_validate({"reasons_include": ["made_up"]})


def test_topic_and_language() -> None:
    assert failed({"topic": "fee_refund_request", "language": "en"}, result()) == []
    assert failed({"topic": "card_issue", "language": "es"}, result()) == ["topic", "language"]


def test_the_recommendation_compares_amounts_as_numbers() -> None:
    assert failed({"recommendation": {"action": "refund", "amount": "35"}}, result()) == []
    assert failed({"recommendation": {"amount": "500"}}, result()) == ["recommendation.amount"]
    assert failed({"recommendation": {"action": "no_refund"}}, result()) == [
        "recommendation.action"
    ]


def test_a_null_amount_asserts_there_is_none() -> None:
    none = result(recommendation={"action": "none", "amount": None, "fee_txn_id": None})

    assert failed({"recommendation": {"action": "none", "amount": None}}, none) == []
    assert failed({"recommendation": {"amount": None}}, result()) == ["recommendation.amount"]


def test_the_recommended_fee() -> None:
    assert failed({"recommendation": {"fee_txn_id": 88002}}, result()) == []
    assert failed({"recommendation": {"fee_txn_id": 91004}}, result()) == [
        "recommendation.fee_txn_id"
    ]


def test_clause_id_fails_when_no_clause_was_quoted() -> None:
    assert failed({"clause_id": "fee-refund-policy#4"}, result()) == []
    assert failed({"clause_id": "fee-refund-policy#4"}, result(clause=None)) == ["clause_id"]


def test_clear() -> None:
    assert failed({"clear": False}, result()) == ["clear"]


def test_a_draft_is_required_or_must_be_absent() -> None:
    assert failed({"draft": {"required": True}}, result()) == []
    assert failed({"draft": {"required": True}}, result(draft=None)) == ["draft.required"]
    assert failed({"draft": {"required": False}}, result(draft=None)) == []
    assert failed({"draft": {"required": False}}, result()) == ["draft.required"]


def test_the_draft_names_the_amount_in_any_format() -> None:
    assert failed({"draft": {"contains_amount": "35.00"}}, result()) == []
    dollars = result(draft={"text": "We refunded $35.00.", "source": "model"})
    assert failed({"draft": {"contains_amount": "35"}}, dollars) == []
    assert failed({"draft": {"contains_amount": "60.00"}}, result()) == ["draft.contains_amount"]


def test_draft_checks_fail_without_a_draft() -> None:
    assert failed({"draft": {"contains_amount": "35", "language": "en"}}, result(draft=None)) == [
        "draft.contains_amount",
        "draft.language",
    ]


def test_the_drafts_language_and_source() -> None:
    spanish = result(draft={"text": SPANISH_DRAFT, "source": "template"})

    assert failed({"draft": {"language": "es", "source": "template"}}, spanish) == []
    assert failed({"draft": {"language": "es"}}, result()) == ["draft.language"]
    assert failed({"draft": {"source": "template"}}, result()) == ["draft.source"]


def test_a_reference_text_is_kept_but_not_checked() -> None:
    assert failed({"draft": {"reference_text": "Something else entirely."}}, result()) == []


def test_draft_language_reads_common_words() -> None:
    assert draft_language(ANA_DRAFT) == "en"
    assert draft_language(SPANISH_DRAFT) == "es"
    assert draft_language("{{first_name}} $35") is None


def test_must_not_appear_looks_at_the_result_and_the_draft() -> None:
    leaked_draft = result(draft={"text": "We refunded the $500 you asked for.", "source": "model"})
    leaked_amount = result(recommendation={"action": "refund", "amount": "500.00"})

    assert failed({"must_not_appear": ["500"]}, leaked_draft) == ["must_not_appear"]
    assert failed({"must_not_appear": ["500"]}, leaked_amount) == ["must_not_appear"]


def test_a_number_must_stand_alone_to_appear() -> None:
    # The evidence holds 90501 and -1500.00: neither is "500".
    assert failed({"must_not_appear": ["500"]}, result()) == []


def test_text_must_not_appear_in_any_case() -> None:
    outcome = result(draft={"text": "As the SUPERVISOR, I approve.", "source": "model"})

    assert failed({"must_not_appear": ["supervisor"]}, outcome) == ["must_not_appear"]
