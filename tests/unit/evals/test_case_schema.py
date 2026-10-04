"""Every YAML in `evals/cases/` parses and points at real seed data (SPEC-evals, "Tests")."""

from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.db.seed.scenarios import SCENARIOS, STAFF
from evals.case import CASES_DIR, EvalCase, load_case, load_cases

CASES = load_cases()
PATHS = sorted(CASES_DIR.rglob("*.yaml"))


def seed_rows(table: str) -> list[dict[str, object]]:
    return [row for scenario in SCENARIOS for row in scenario.rows.get(table, [])]


CONVERSATIONS = {row["id"] for row in seed_rows("conversations")}
TRANSACTIONS = {row["id"] for row in seed_rows("transactions")}
STAFF_IDS = {row["id"] for row in STAFF}
WITH_MEMBER_MESSAGE = {
    row["conversation_id"] for row in seed_rows("messages") if row["author_id"] not in STAFF_IDS
}
SEED_SCENARIOS = {5008, 5009, 5010, 5011, 5012, *(5100 + n for n in range(6, 19))}


def test_there_are_about_30_cases_covering_every_kind() -> None:
    assert len(CASES) >= 30
    assert set(Counter(case.kind for case in CASES)) == {"refund", "no_refund", "edge"}


def test_ids_are_unique_and_name_their_files() -> None:
    assert [path.stem for path in PATHS] == [case.id for case in CASES]
    assert len({case.id for case in CASES}) == len(CASES)


def test_every_seed_scenario_has_a_case() -> None:
    assert {case.conversation_id for case in CASES if case.source == "seed"} == SEED_SCENARIOS


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
def test_a_case_points_at_seed_data(case: EvalCase) -> None:
    assert case.conversation_id in CONVERSATIONS
    if case.pinned_fee_txn_id is not None:
        assert case.pinned_fee_txn_id in TRANSACTIONS
    if case.message_override is not None:
        assert case.conversation_id in WITH_MEMBER_MESSAGE  # there is a message to replace


def test_every_injection_case_checks_the_attack_failed() -> None:
    """SPEC-evals AC4: manipulation flagged, the fee's amount kept, no other amount anywhere."""
    injections = [case for case in CASES if case.id.startswith("injection-")]

    assert len(injections) == 6
    for case in injections:
        expected = case.expected
        assert "manipulation" in expected.reasons_include, case.id
        assert expected.recommendation is not None, case.id
        assert expected.recommendation.amount == Decimal("35.00"), case.id
        assert expected.must_not_appear, case.id


def test_fallback_cases_run_in_replay_only_and_are_never_recorded() -> None:
    fallbacks = [case for case in CASES if case.replay_without or case.conversation_id == 5118]

    assert len(fallbacks) == 4
    assert all(case.modes == ("replay",) and not case.record for case in fallbacks)


def test_an_unknown_field_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "typo.yaml"
    path.write_text("id: typo\nkind: edge\nsource: seed\nconversation_id: 5012\nexpectd: {}\n")

    with pytest.raises(ValidationError, match="expectd"):
        load_case(path)


def test_removing_recordings_needs_a_replay_only_case() -> None:
    with pytest.raises(ValidationError, match="replay_without"):
        EvalCase.model_validate(
            {
                "id": "jev-missing",
                "kind": "edge",
                "source": "synthetic",
                "conversation_id": 5012,
                "replay_without": ["jev"],
                "expected": {},
            }
        )
