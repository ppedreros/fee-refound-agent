"""Settings and fixtures shared by every test.

Database fixtures are lazy: unit tests never request them, so they never touch Postgres.
Integration and API tests run against a real Postgres, never SQLite (SPEC.md, "Testing
strategy"). TEST_DATABASE_URL is an owner URL on that server; by default the compose `db`,
published on 127.0.0.1 (D-platform-2). The session creates a fresh `fees_test` database there.
"""

import asyncio
import os
from collections.abc import Iterator, Mapping

import pytest
from pytest_asyncio.plugin import LoopFactory
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import OperationalError

from backend.db.roles import LoginRole, ensure_login_roles, grant_privileges
from backend.db.seed import reset, seed
from backend.policy.loader import load_clauses
from tests.integration.migrations import migrate
from tests.integration.roles import (
    TEST_AGENT_ROLE,
    TEST_APP_ROLE,
    TEST_ROLE_PASSWORD,
    owner_secret,
)


def pytest_asyncio_loop_factories(
    config: pytest.Config, item: pytest.Item
) -> Mapping[str, LoopFactory]:
    # psycopg's async mode can't run on Windows' default (Proactor) loop. A selector loop is the
    # default on Linux, so every async test runs the same everywhere.
    return {"selector": asyncio.SelectorEventLoop}


DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg://fees:change-me@127.0.0.1:5432/fees"
TEST_DATABASE_NAME = "fees_test"


@pytest.fixture(scope="session")
def test_database_url() -> URL:
    server = make_url(os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL))
    admin = create_engine(server, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DATABASE_NAME}" WITH (FORCE)'))
            connection.execute(text(f'CREATE DATABASE "{TEST_DATABASE_NAME}"'))
    except OperationalError:
        pytest.fail(
            "Integration tests need Postgres: run `docker compose up -d db`, "
            "or point TEST_DATABASE_URL at a server where you can create databases.",
            pytrace=False,
        )
    finally:
        admin.dispose()
    return server.set(database=TEST_DATABASE_NAME)


@pytest.fixture(scope="session")
def migrated_engine(test_database_url: URL) -> Iterator[Engine]:
    """An engine on `fees_test`, migrated to head once per session."""
    engine = create_engine(test_database_url)
    migrate(engine, "head")
    yield engine
    engine.dispose()


# --- Roles (see tests/integration/roles.py) ---


@pytest.fixture(scope="session")
def test_roles(migrated_engine: Engine, test_database_url: URL) -> Iterator[None]:
    """The two test login roles, created once and dropped at the end of the session."""
    ensure_login_roles(
        owner_secret(test_database_url),
        [
            LoginRole(TEST_APP_ROLE, TEST_ROLE_PASSWORD),
            LoginRole(TEST_AGENT_ROLE, TEST_ROLE_PASSWORD),
        ],
    )
    yield
    with migrated_engine.begin() as connection:
        connection.execute(text(f"DROP OWNED BY {TEST_APP_ROLE}, {TEST_AGENT_ROLE}"))
        connection.execute(text(f"DROP ROLE {TEST_APP_ROLE}, {TEST_AGENT_ROLE}"))


@pytest.fixture
def granted_roles(test_roles: None, test_database_url: URL) -> None:
    """Grant the SPEC-data privileges to the test roles. Per test, because a downgrade test drops
    the tables, and their grants with them."""
    grant_privileges(
        owner_secret(test_database_url), app_role=TEST_APP_ROLE, agent_role=TEST_AGENT_ROLE
    )


# --- Data ---


@pytest.fixture
def seeded(migrated_engine: Engine) -> Iterator[Engine]:
    """A freshly reset and seeded fees_test, emptied again afterwards."""
    with migrated_engine.begin() as connection:
        reset(connection)
        seed(connection)
    yield migrated_engine
    with migrated_engine.begin() as connection:
        reset(connection)


@pytest.fixture
def with_clauses(seeded: Engine, granted_roles: None) -> Iterator[Engine]:
    with seeded.begin() as connection:
        load_clauses(connection)
    yield seeded
