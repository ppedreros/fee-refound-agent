"""The policy documents: front-matter, clause splitting, params vs text (SPEC-policy)."""

import shutil
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from backend.policy.loader import (
    DOCS_DIR,
    PolicyError,
    consistency_problems,
    fee_schedule_clause,
    load_policy,
)
from backend.tools.descriptions import CONFIG_FILE as DESCRIPTIONS_FILE

SLUGS = {
    "fee-refund-policy",
    "courtesy-pay-rules",
    "fee-schedule",
    "staff-approval-limits",
    "member-communication",
    "account-standing",
}


def copy_docs(tmp_path: Path) -> Path:
    target = tmp_path / "docs"
    shutil.copytree(DOCS_DIR, target)
    return target


def test_all_six_documents_load() -> None:
    policy = load_policy()

    assert {document.slug for document in policy.documents} == SLUGS


def test_every_clause_has_an_id_a_title_a_section_and_text() -> None:
    clauses = load_policy().clauses

    assert len({clause.id for clause in clauses}) == len(clauses)
    for clause in clauses:
        assert clause.id == f"{clause.doc_slug}#{clause.number}"
        assert clause.doc_title
        assert clause.section.startswith(f"{clause.number}. ")
        assert clause.text.strip()


def test_the_refund_policy_states_the_rules_the_checks_implement() -> None:
    text = {clause.id: clause.text for clause in load_policy().clauses}

    assert "up to 3 fee refunds in any 12-month period" in text["fee-refund-policy#2"]
    assert "no unpaid balance on any account" in text["fee-refund-policy#3"]
    assert (
        "We refund a Courtesy Pay fee when a deposit that posted the same day would have "
        "covered the payment if it had posted first." in text["fee-refund-policy#4"]
    )
    assert "up to $50" in text["staff-approval-limits#1"]


def test_the_rules_read_their_numbers_from_the_documents() -> None:
    params = load_policy().params

    assert params.max_refunds_in_window == 3
    assert params.window_days == 365
    assert params.staff_limit_usd == Decimal("50")
    assert params.fees["Courtesy Pay"].amount == Decimal("35")


def test_the_text_and_the_params_agree() -> None:
    assert consistency_problems(load_policy()) == []


def test_changing_a_param_without_the_text_is_caught(tmp_path: Path) -> None:
    docs = copy_docs(tmp_path)
    refund_policy = docs / "fee-refund-policy.md"
    refund_policy.write_text(
        refund_policy.read_text(encoding="utf-8").replace(
            "max_refunds_in_window: 3", "max_refunds_in_window: 2"
        ),
        encoding="utf-8",
    )

    with pytest.raises(PolicyError, match="fee-refund-policy#2"):
        load_policy(docs)


def test_a_malformed_param_names_the_file_and_the_field(tmp_path: Path) -> None:
    docs = copy_docs(tmp_path)
    limits = docs / "staff-approval-limits.md"
    limits.write_text(
        limits.read_text(encoding="utf-8").replace("staff_limit_usd: 50", "staff_limit_usd: lots"),
        encoding="utf-8",
    )

    with pytest.raises(PolicyError) as error:
        load_policy(docs)

    assert "staff-approval-limits.md" in str(error.value)
    assert "staff_limit_usd" in str(error.value)


def test_a_document_without_front_matter_names_the_file(tmp_path: Path) -> None:
    docs = copy_docs(tmp_path)
    (docs / "notes.md").write_text("# Notes\n\n## 1. Something\nText.\n", encoding="utf-8")

    with pytest.raises(PolicyError, match=r"notes\.md"):
        load_policy(docs)


def test_clauses_must_be_numbered_in_order(tmp_path: Path) -> None:
    docs = copy_docs(tmp_path)
    standing = docs / "account-standing.md"
    standing.write_text(
        standing.read_text(encoding="utf-8").replace("## 1. ", "## 2. "), encoding="utf-8"
    )

    with pytest.raises(PolicyError, match=r"account-standing\.md"):
        load_policy(docs)


def test_every_fee_type_has_a_clause_in_the_fee_schedule() -> None:
    policy = load_policy()
    schedule_ids = {c.id for c in policy.clauses if c.doc_slug == "fee-schedule"}

    mapped = {fee_type: fee_schedule_clause(fee_type) for fee_type in policy.params.fees}

    assert set(mapped.values()) == schedule_ids
    assert fee_schedule_clause("Savings below minimum") == "fee-schedule#4"
    assert fee_schedule_clause("Not a fee") is None


def test_every_fee_type_the_core_descriptions_name_is_in_the_fee_schedule() -> None:
    named = {
        rule["fee_type"]
        for rule in yaml.safe_load(DESCRIPTIONS_FILE.read_text(encoding="utf-8"))["fee_types"]
    }

    assert named <= load_policy().params.fees.keys()


def test_the_policy_version_changes_only_when_a_document_changes(tmp_path: Path) -> None:
    docs = copy_docs(tmp_path)
    original = load_policy(docs).version
    assert load_policy(docs).version == original

    member = docs / "member-communication.md"
    member.write_text(member.read_text(encoding="utf-8") + "\nOne more line.\n", encoding="utf-8")

    assert load_policy(docs).version != original
