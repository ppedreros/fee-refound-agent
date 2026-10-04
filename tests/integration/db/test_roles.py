"""Database roles: agents only read (SPEC-data, "Database roles").

Roles are server-wide, so these tests use their own role names. The dev stack's app_writer and
agent_reader, and their passwords, are never touched.
"""

from collections.abc import Iterator
from typing import Literal

import pytest
import sqlalchemy as sa
from psycopg.errors import InsufficientPrivilege, QueryCanceled, ReadOnlySqlTransaction
from pydantic import SecretStr
from sqlalchemy import Connection, Engine, Executable, create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError

from backend.db.models import Base
from backend.db.roles import LoginRole, ensure_login_roles, grant_privileges

APP = "test_app_writer"
AGENT = "test_agent_reader"
PASSWORD = "test-role-password"

READER_CAN_READ = [
    "conversations",
    "messages",
    "accounts",
    "sub_accounts",
    "transactions",
    "member_profiles",
    "policy_clauses",
    "cases",
    "agent_runs",
    "refunds",
]
READER_CANNOT_READ = ["staff", "agent_steps", "decisions", "audit_events", "eval_candidates"]
ALL_TABLES = READER_CAN_READ + READER_CANNOT_READ


type Write = Literal["insert", "update", "delete", "truncate"]
WRITES: list[Write] = ["insert", "update", "delete", "truncate"]


def write(table: str, kind: Write) -> Executable:
    """A write on `table` that touches no row, so only a privilege check can stop it."""
    column = next(iter(Base.metadata.tables[table].columns)).name
    target = sa.table(table, sa.column(column))
    match kind:
        case "insert":
            return sa.insert(target)  # INSERT ... DEFAULT VALUES
        case "update":
            return sa.update(target).values({column: target.c[column]}).where(sa.false())
        case "delete":
            return sa.delete(target).where(sa.false())
        case "truncate":
            return text(f"TRUNCATE {table}")


def count_rows(table: str) -> Executable:
    return sa.select(sa.func.count()).select_from(sa.table(table))


@pytest.fixture(scope="module")
def roles(migrated_engine: Engine, test_database_url: URL) -> Iterator[None]:
    owner = SecretStr(test_database_url.render_as_string(hide_password=False))
    for _ in range(2):  # bootstrap runs on every start, so twice in a row must work
        ensure_login_roles(owner, [LoginRole(APP, PASSWORD), LoginRole(AGENT, PASSWORD)])
        grant_privileges(owner, app_role=APP, agent_role=AGENT)
    yield
    with migrated_engine.begin() as connection:
        connection.execute(text(f"DROP OWNED BY {APP}, {AGENT}"))
        connection.execute(text(f"DROP ROLE {APP}, {AGENT}"))


def engine_as(test_database_url: URL, role: str) -> Engine:
    url = test_database_url.set(username=role, password=PASSWORD)
    return create_engine(url, isolation_level="AUTOCOMMIT")


@pytest.fixture
def reader(roles: None, test_database_url: URL) -> Iterator[Connection]:
    engine = engine_as(test_database_url, AGENT)
    with engine.connect() as connection:
        yield connection
    engine.dispose()


@pytest.fixture
def writer(roles: None, test_database_url: URL) -> Iterator[Connection]:
    engine = engine_as(test_database_url, APP)
    with engine.connect() as connection:
        yield connection
    engine.dispose()


@pytest.fixture
def ana_conversation(migrated_engine: Engine) -> Iterator[None]:
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO conversations (id, member_id, subject, status, created_at) "
                "VALUES (5012, 301, 'Overdraft fee', 'waiting_for_bank', now())"
            )
        )
    yield
    with migrated_engine.begin() as connection:
        connection.execute(text("DELETE FROM messages WHERE conversation_id = 5012"))
        connection.execute(text("DELETE FROM conversations WHERE id = 5012"))


def assert_fails_with(
    connection: Connection, statement: Executable | str, error: type[Exception]
) -> None:
    with pytest.raises(DBAPIError) as raised:
        connection.execute(text(statement) if isinstance(statement, str) else statement)
    assert isinstance(raised.value.orig, error), raised.value.orig


# --- Both roles can log in, after bootstrap ran twice ---


@pytest.mark.parametrize("role", [APP, AGENT])
def test_each_role_logs_in_with_its_password(
    roles: None, test_database_url: URL, role: str
) -> None:
    engine = engine_as(test_database_url, role)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT current_user")).scalar_one() == role
    engine.dispose()


# --- agent_reader ---


@pytest.mark.parametrize("table", READER_CAN_READ)
def test_reader_can_read_what_the_agent_needs(reader: Connection, table: str) -> None:
    reader.execute(count_rows(table))


@pytest.mark.parametrize("table", READER_CANNOT_READ)
def test_reader_cannot_read_anything_else(reader: Connection, table: str) -> None:
    assert_fails_with(reader, count_rows(table), InsufficientPrivilege)


def test_reader_sessions_are_read_only_with_a_3_second_timeout(reader: Connection) -> None:
    assert reader.execute(text("SHOW default_transaction_read_only")).scalar_one() == "on"
    assert reader.execute(text("SHOW statement_timeout")).scalar_one() == "3s"


def test_a_reader_session_refuses_writes_by_default(reader: Connection) -> None:
    assert_fails_with(
        reader,
        "UPDATE cases SET status = 'done' WHERE false",
        ReadOnlySqlTransaction,
    )


@pytest.mark.parametrize("kind", WRITES)
@pytest.mark.parametrize("table", ALL_TABLES)
def test_reader_cannot_write_even_after_turning_read_only_off(
    reader: Connection, table: str, kind: Write
) -> None:
    # A session can switch the read-only default off; the missing grants are the real boundary.
    reader.execute(text("SET default_transaction_read_only = off"))

    assert_fails_with(reader, write(table, kind), InsufficientPrivilege)


def test_a_slow_reader_query_is_cancelled_after_3_seconds(reader: Connection) -> None:
    assert_fails_with(reader, "SELECT pg_sleep(4)", QueryCanceled)


# --- app_writer ---


def test_writer_can_post_a_reply_and_close_the_conversation(
    writer: Connection, ana_conversation: None
) -> None:
    writer.execute(
        text(
            "INSERT INTO messages (conversation_id, author_id, body, created_at) "
            "VALUES (5012, 'S07', 'Done!', now())"
        )
    )
    writer.execute(text("UPDATE conversations SET status = 'closed' WHERE id = 5012"))

    new_id = writer.execute(
        text("SELECT id FROM messages WHERE conversation_id = 5012")
    ).scalar_one()
    assert new_id >= 1_000_000


def test_writer_can_only_change_a_conversation_status(writer: Connection) -> None:
    assert_fails_with(
        writer, "UPDATE conversations SET subject = 'x' WHERE false", InsufficientPrivilege
    )


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE transactions SET amount = 0 WHERE false",
        "UPDATE sub_accounts SET name = 'x' WHERE false",
        "UPDATE decisions SET action = 'approve' WHERE false",
        "UPDATE audit_events SET action = 'x' WHERE false",
        "UPDATE refunds SET amount = 1 WHERE false",
        "INSERT INTO staff (id, display_name) VALUES ('S99', 'x')",
        "INSERT INTO policy_clauses DEFAULT VALUES",
    ],
)
def test_writer_cannot_rewrite_history_or_reference_data(
    writer: Connection, statement: str
) -> None:
    assert_fails_with(writer, statement, InsufficientPrivilege)


@pytest.mark.parametrize("table", ALL_TABLES)
def test_writer_cannot_delete_or_truncate_anything(writer: Connection, table: str) -> None:
    assert_fails_with(writer, write(table, "delete"), InsufficientPrivilege)
    assert_fails_with(writer, write(table, "truncate"), InsufficientPrivilege)
