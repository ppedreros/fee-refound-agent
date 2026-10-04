import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend.core.settings import ConfigError, load_settings

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("PROVIDER_MODE", "JEV_API_KEY", "OPENAI_API_KEY", "OWNER_DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(
        "APP_DATABASE_URL", "postgresql+psycopg://app_writer:writer-secret@db:5432/fees"
    )
    monkeypatch.setenv(
        "AGENT_DATABASE_URL", "postgresql+psycopg://agent_reader:reader-secret@db:5432/fees"
    )
    monkeypatch.setenv("MASKING_SALT", "salt-secret")
    monkeypatch.delenv("LOG_LEVEL", raising=False)


def test_auto_mode_is_live_for_providers_with_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JEV_API_KEY", "jev-test-key")

    modes = load_settings(env_file=None).provider_modes

    assert modes.jev == "live"
    assert modes.openai == "replay"


def test_auto_mode_is_replay_when_no_keys_are_set() -> None:
    modes = load_settings(env_file=None).provider_modes

    assert modes.jev == "replay"
    assert modes.openai == "replay"


def test_blank_key_counts_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JEV_API_KEY", "   ")

    assert load_settings(env_file=None).provider_modes.jev == "replay"


def test_replay_mode_ignores_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVIDER_MODE", "replay")
    monkeypatch.setenv("JEV_API_KEY", "jev-test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")

    modes = load_settings(env_file=None).provider_modes

    assert modes.jev == "replay"
    assert modes.openai == "replay"


def test_live_mode_with_both_keys_is_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVIDER_MODE", "live")
    monkeypatch.setenv("JEV_API_KEY", "jev-test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")

    modes = load_settings(env_file=None).provider_modes

    assert modes.jev == "live"
    assert modes.openai == "live"


def test_live_mode_without_keys_names_the_missing_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROVIDER_MODE", "live")

    with pytest.raises(ConfigError) as error:
        load_settings(env_file=None)

    assert "JEV_API_KEY" in str(error.value)
    assert "OPENAI_API_KEY" in str(error.value)


def test_invalid_provider_mode_names_the_variable_but_not_the_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROVIDER_MODE", "banana")

    with pytest.raises(ConfigError) as error:
        load_settings(env_file=None)

    assert "PROVIDER_MODE" in str(error.value)
    assert "banana" not in str(error.value)


def test_keys_never_appear_in_the_settings_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JEV_API_KEY", "jev-secret-value")

    assert "jev-secret-value" not in repr(load_settings(env_file=None))


def test_database_passwords_never_appear_in_the_settings_repr() -> None:
    settings_repr = repr(load_settings(env_file=None))

    assert "writer-secret" not in settings_repr
    assert "reader-secret" not in settings_repr


def test_missing_database_url_names_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_DATABASE_URL")

    with pytest.raises(ConfigError) as error:
        load_settings(env_file=None)

    assert "APP_DATABASE_URL" in str(error.value)


def test_malformed_database_url_names_the_variable_but_not_the_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_DATABASE_URL", "not-a-url-reader-secret")

    with pytest.raises(ConfigError) as error:
        load_settings(env_file=None)

    assert "AGENT_DATABASE_URL" in str(error.value)
    assert "reader-secret" not in str(error.value)


def test_database_url_must_use_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_DATABASE_URL", "sqlite:///fees.db")

    with pytest.raises(ConfigError) as error:
        load_settings(env_file=None)

    assert "APP_DATABASE_URL" in str(error.value)


@pytest.mark.parametrize(
    ("variable", "url"),
    [
        ("APP_DATABASE_URL", "postgresql+psycopg://fees:writer-secret@db:5432/fees"),
        ("AGENT_DATABASE_URL", "postgresql+psycopg://app_writer:reader-secret@db:5432/fees"),
    ],
)
def test_database_url_must_log_in_as_its_role(
    monkeypatch: pytest.MonkeyPatch, variable: str, url: str
) -> None:
    monkeypatch.setenv(variable, url)

    with pytest.raises(ConfigError) as error:
        load_settings(env_file=None)

    assert variable in str(error.value)


def test_role_database_url_needs_a_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_DATABASE_URL", "postgresql+psycopg://app_writer@db:5432/fees")

    with pytest.raises(ConfigError) as error:
        load_settings(env_file=None)

    assert "APP_DATABASE_URL" in str(error.value)


def test_masking_salt_is_required_and_blank_counts_as_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MASKING_SALT", "  ")

    with pytest.raises(ConfigError) as error:
        load_settings(env_file=None)

    assert "MASKING_SALT" in str(error.value)


def test_masking_salt_never_appears_in_the_settings_repr() -> None:
    assert "salt-secret" not in repr(load_settings(env_file=None))


def test_log_level_defaults_to_info() -> None:
    assert load_settings(env_file=None).log_level == "INFO"


def test_unknown_log_level_names_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "LOUD")

    with pytest.raises(ConfigError) as error:
        load_settings(env_file=None)

    assert "LOG_LEVEL" in str(error.value)


def test_owner_database_url_is_optional_and_blank_counts_as_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OWNER_DATABASE_URL", "  ")

    assert load_settings(env_file=None).owner_database_url is None


def test_startup_with_invalid_mode_exits_with_one_plain_line() -> None:
    env = {**os.environ, "PROVIDER_MODE": "banana"}

    result = subprocess.run(
        [sys.executable, "-m", "backend.api"],
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
    assert "PROVIDER_MODE" in lines[0]
    assert "banana" not in lines[0]
