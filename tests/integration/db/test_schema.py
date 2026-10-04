"""The schema from SPEC-data, checked against a real Postgres (fees_test)."""

from collections.abc import Iterator

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from psycopg.errors import CheckViolation, UniqueViolation
from sqlalchemy import Connection, Engine, inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from backend.db.models import Base
from tests.integration.migrations import migrate

BRIEF_COLUMNS = {
    "conversations": ["id", "member_id", "subject", "status", "created_at"],
    "messages": ["id", "conversation_id", "author_id", "body", "created_at"],
    "accounts": ["id", "member_id", "credit_union_id", "account_number", "is_primary"],
    "sub_accounts": ["id", "account_id", "type", "name", "balance", "available"],
    "transactions": [
        "id",
        "sub_account_id",
        "date",
        "description",
        "amount",
        "balance_after",
        "posting_ref",
    ],
}

ALL_TABLES = {
    *BRIEF_COLUMNS,
    "member_profiles",
    "staff",
    "policy_clauses",
    "cases",
    "agent_runs",
    "agent_steps",
    "decisions",
    "refunds",
    "audit_events",
    "eval_candidates",
}

MONEY_COLUMNS = [
    ("sub_accounts", "balance"),
    ("sub_accounts", "available"),
    ("transactions", "amount"),
    ("transactions", "balance_after"),
    ("refunds", "amount"),
]


@pytest.fixture
def connection(migrated_engine: Engine) -> Iterator[Connection]:
    """A connection whose changes are always rolled back."""
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        yield connection
        transaction.rollback()


def insert_ana_conversation(connection: Connection) -> None:
    connection.execute(
        text(
            "INSERT INTO conversations (id, member_id, subject, status, created_at) "
            "VALUES (5012, 301, 'Overdraft fee', 'waiting_for_bank', '2026-09-15 08:12:44+00')"
        )
    )


def test_upgrade_creates_every_table(migrated_engine: Engine) -> None:
    tables = set(inspect(migrated_engine).get_table_names())

    assert tables == ALL_TABLES | {"alembic_version"}


@pytest.mark.parametrize(("table", "columns"), BRIEF_COLUMNS.items())
def test_brief_tables_have_exactly_the_brief_columns(
    connection: Connection, table: str, columns: list[str]
) -> None:
    found = connection.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :table ORDER BY ordinal_position"
        ),
        {"table": table},
    ).scalars()

    assert list(found) == columns


@pytest.mark.parametrize(("table", "column"), MONEY_COLUMNS)
def test_money_is_numeric_12_2(connection: Connection, table: str, column: str) -> None:
    precision, scale = connection.execute(
        text(
            "SELECT numeric_precision, numeric_scale FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    ).one()

    assert (precision, scale) == (12, 2)


def test_the_models_match_the_migration(connection: Connection) -> None:
    differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)

    assert differences == []


def test_downgrade_removes_everything_and_upgrade_restores_it(migrated_engine: Engine) -> None:
    try:
        migrate(migrated_engine, "base")
        assert set(inspect(migrated_engine).get_table_names()) == {"alembic_version"}
        with migrated_engine.connect() as connection:
            functions = connection.execute(
                text("SELECT count(*) FROM pg_proc WHERE proname = 'reject_audit_change'")
            ).scalar_one()
        assert functions == 0
    finally:
        migrate(migrated_engine, "head")

    assert set(inspect(migrated_engine).get_table_names()) == ALL_TABLES | {"alembic_version"}


def test_audit_events_accept_inserts(connection: Connection) -> None:
    connection.execute(
        text("INSERT INTO audit_events (actor, action) VALUES ('S07', 'decision_made')")
    )

    assert connection.execute(text("SELECT count(*) FROM audit_events")).scalar_one() == 1


@pytest.mark.parametrize(
    "statement",
    ["UPDATE audit_events SET action = 'changed'", "DELETE FROM audit_events"],
)
def test_audit_events_reject_update_and_delete(connection: Connection, statement: str) -> None:
    connection.execute(
        text("INSERT INTO audit_events (actor, action) VALUES ('S07', 'decision_made')")
    )

    with pytest.raises(DBAPIError, match="append-only"):
        connection.execute(text(statement))


def test_a_case_has_at_most_one_running_run(connection: Connection) -> None:
    insert_ana_conversation(connection)
    connection.execute(
        text("INSERT INTO cases (conversation_id, status) VALUES (5012, 'checking')")
    )
    connection.execute(text("INSERT INTO agent_runs (case_id, status) VALUES (5012, 'completed')"))
    connection.execute(text("INSERT INTO agent_runs (case_id, status) VALUES (5012, 'running')"))

    with pytest.raises(IntegrityError) as error:
        connection.execute(
            text("INSERT INTO agent_runs (case_id, status) VALUES (5012, 'running')")
        )

    assert isinstance(error.value.orig, UniqueViolation)


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO conversations (id, member_id, subject, status, created_at) "
        "VALUES (1, 1, 's', 'banana', now())",
        "UPDATE cases SET status = 'banana' WHERE conversation_id = 5012",
        "INSERT INTO agent_runs (case_id, status) VALUES (5012, 'banana')",
        "INSERT INTO sub_accounts (id, account_id, type, name, balance, available) "
        "VALUES (1, 1, 'BITCOIN', 'x', 0, 0)",
    ],
)
def test_enumerations_reject_unknown_values(connection: Connection, statement: str) -> None:
    insert_ana_conversation(connection)
    connection.execute(
        text("INSERT INTO cases (conversation_id, status) VALUES (5012, 'checking')")
    )

    with pytest.raises(IntegrityError) as error:
        connection.execute(text(statement))

    assert isinstance(error.value.orig, CheckViolation)


def test_posting_ref_must_be_date_dash_sequence_and_unique_per_sub_account(
    connection: Connection,
) -> None:
    connection.execute(
        text(
            "INSERT INTO accounts (id, member_id, credit_union_id, account_number, is_primary) "
            "VALUES (710, 301, 7, '884210', true);"
            "INSERT INTO sub_accounts (id, account_id, type, name, balance, available) "
            "VALUES (1302, 710, 'CHECKING', 'Everyday Checking', 1325.00, 1325.00);"
            "INSERT INTO transactions "
            "(id, sub_account_id, date, description, amount, balance_after, posting_ref) "
            "VALUES (88002, 1302, '2026-09-14', 'Fee', -35.00, -75.00, '20260914-0005')"
        )
    )
    insert = (
        "INSERT INTO transactions "
        "(sub_account_id, date, description, amount, balance_after, posting_ref) "
        "VALUES (1302, '2026-09-14', 'x', 1.00, 1.00, :ref)"
    )

    with pytest.raises(IntegrityError) as bad_format, connection.begin_nested():
        connection.execute(text(insert), {"ref": "2026-09-14"})
    with pytest.raises(IntegrityError) as duplicate, connection.begin_nested():
        connection.execute(text(insert), {"ref": "20260914-0005"})

    assert isinstance(bad_format.value.orig, CheckViolation)
    assert isinstance(duplicate.value.orig, UniqueViolation)


def test_policy_clauses_are_searchable_without_extra_work(connection: Connection) -> None:
    connection.execute(
        text(
            "INSERT INTO policy_clauses (id, doc_slug, doc_title, section, text, params, "
            "policy_version) VALUES ('fee-refund-policy#4', 'fee-refund-policy', "
            "'Fee refund policy', 'Same-day deposits', 'We refund an overdraft fee when the "
            "deposit that would have covered it posted the same day.', '{}', 'v1')"
        )
    )

    found = connection.execute(
        text(
            "SELECT id FROM policy_clauses "
            "WHERE search @@ websearch_to_tsquery('english', 'same day deposit refund')"
        )
    ).scalars()

    assert list(found) == ["fee-refund-policy#4"]
