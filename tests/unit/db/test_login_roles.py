import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend.core.settings import load_settings
from backend.db.roles import LoginRole, login_roles

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def database_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "APP_DATABASE_URL", "postgresql+psycopg://app_writer:writer-pass@db:5432/fees"
    )
    monkeypatch.setenv(
        "AGENT_DATABASE_URL", "postgresql+psycopg://agent_reader:reader%40pass@db:5432/fees"
    )
    monkeypatch.setenv("MASKING_SALT", "test-salt")


def test_each_role_takes_its_password_from_its_own_url() -> None:
    roles = login_roles(load_settings(env_file=None))

    assert roles == [
        LoginRole(name="app_writer", password="writer-pass"),
        LoginRole(name="agent_reader", password="reader@pass"),
    ]


def test_a_login_role_never_shows_its_password() -> None:
    role = LoginRole(name="app_writer", password="writer-pass")

    assert "writer-pass" not in repr(role)
    assert "writer-pass" not in str(role)


def test_bootstrap_without_the_owner_url_exits_with_one_plain_line() -> None:
    env = {name: value for name, value in os.environ.items() if name != "OWNER_DATABASE_URL"}

    result = subprocess.run(
        [sys.executable, "-m", "backend.bootstrap"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    lines = result.stderr.strip().splitlines()
    assert result.returncode == 1
    assert len(lines) == 1
    assert "OWNER_DATABASE_URL" in lines[0]
    assert "writer-pass" not in lines[0]
