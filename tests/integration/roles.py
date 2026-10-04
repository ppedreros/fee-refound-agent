"""Test login roles. Roles are server-wide, so the tests use their own names: the dev stack's
app_writer and agent_reader, and their passwords, are never touched."""

from pydantic import SecretStr
from sqlalchemy.engine import URL

TEST_APP_ROLE = "test_app_writer"
TEST_AGENT_ROLE = "test_agent_reader"
TEST_ROLE_PASSWORD = "test-role-password"


def owner_secret(test_database_url: URL) -> SecretStr:
    return SecretStr(test_database_url.render_as_string(hide_password=False))


def role_url(test_database_url: URL, role: str) -> URL:
    return test_database_url.set(username=role, password=TEST_ROLE_PASSWORD)
