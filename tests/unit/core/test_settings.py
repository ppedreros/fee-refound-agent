import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend.core.settings import ConfigError, load_settings

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def clean_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("PROVIDER_MODE", "JEV_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)


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
