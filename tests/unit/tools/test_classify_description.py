"""Transaction kinds from the core system's free-text descriptions (SPEC-data AC9)."""

import pytest
from backend.tools.descriptions import TransactionKind, classify_description

from backend.db.seed.scenarios import SCENARIOS

# Every description in the seed, and what it must be classified as.
SEEDED = {
    "Withdrawal Debit Card CITY POWER & LIGHT": TransactionKind(kind="card_payment"),
    "Fee Withdrawal ; Courtesy Pay fee": TransactionKind(kind="fee", fee_type="Courtesy Pay"),
    "Deposit ACH ACME LOGISTICS*PAYROLL": TransactionKind(kind="payroll_deposit"),
    "Deposit Fee Refund Courtesy Pay Fee": TransactionKind(
        kind="fee_refund", fee_type="Courtesy Pay"
    ),
    "Deposit Fee Refund Out of Network Fee": TransactionKind(
        kind="fee_refund", fee_type="Out of Network"
    ),
}


def seeded_descriptions() -> set[str]:
    return {
        row["description"]
        for scenario in SCENARIOS
        for row in scenario.rows.get("transactions", [])
    }


def test_every_seeded_description_has_an_expected_kind() -> None:
    assert seeded_descriptions() <= SEEDED.keys()


@pytest.mark.parametrize(("description", "expected"), SEEDED.items())
def test_every_seeded_description_is_classified_correctly(
    description: str, expected: TransactionKind
) -> None:
    assert classify_description(description) == expected


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("fee withdrawal ; courtesy pay fee", TransactionKind(kind="fee", fee_type="Courtesy Pay")),
        ("Deposit ACH ACME LOGISTICS*PAYROLL ", TransactionKind(kind="payroll_deposit")),
        ("Deposit Mobile Check", TransactionKind(kind="deposit")),
        ("Withdrawal ATM 5TH AVE", TransactionKind(kind="withdrawal")),
        ("Fee Withdrawal ; Monthly service", TransactionKind(kind="fee")),
        ("Interest Payment", TransactionKind(kind="other")),
        ("", TransactionKind(kind="other")),
    ],
)
def test_other_descriptions(description: str, expected: TransactionKind) -> None:
    assert classify_description(description) == expected


def test_a_fee_refund_is_never_mistaken_for_a_fee_or_a_plain_deposit() -> None:
    kind = classify_description("Deposit Fee Refund Courtesy Pay Fee").kind

    assert kind == "fee_refund"


def test_only_fees_and_fee_refunds_carry_a_fee_type() -> None:
    assert classify_description("Withdrawal Debit Card Courtesy Pay Store").fee_type is None
