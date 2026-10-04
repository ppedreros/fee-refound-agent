"""Loading the policy clauses into policy_clauses (SPEC-policy, "Clause store")."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text

from backend.db.seed import reset
from backend.policy.loader import load_clauses, load_policy


@pytest.fixture
def empty(migrated_engine: Engine) -> Iterator[Engine]:
    with migrated_engine.begin() as connection:
        reset(connection)
    yield migrated_engine
    with migrated_engine.begin() as connection:
        reset(connection)


def clause_rows(engine: Engine) -> dict[str, tuple[str, str]]:
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT id, policy_version, section FROM policy_clauses"))
        return {row.id: (row.policy_version, row.section) for row in rows}


def test_loading_stores_every_clause_with_the_policy_version(empty: Engine) -> None:
    policy = load_policy()

    with empty.begin() as connection:
        load_clauses(connection)

    rows = clause_rows(empty)
    assert rows.keys() == {clause.id for clause in policy.clauses}
    assert {version for version, _ in rows.values()} == {policy.version}
    assert rows["fee-refund-policy#4"][1] == "4. Same-day deposits"


def test_loading_twice_changes_nothing(empty: Engine) -> None:
    with empty.begin() as connection:
        load_clauses(connection)
    before = clause_rows(empty)

    with empty.begin() as connection:
        load_clauses(connection)

    assert clause_rows(empty) == before


def test_a_clause_that_left_the_documents_is_removed(empty: Engine) -> None:
    with empty.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO policy_clauses (id, doc_slug, doc_title, section, text, params, "
                "policy_version) VALUES ('old-policy#1', 'old-policy', 'Old', '1. Old', 'Gone.', "
                "'{}', 'v0')"
            )
        )

    with empty.begin() as connection:
        load_clauses(connection)

    assert "old-policy#1" not in clause_rows(empty)
