"""Each provider runs in the mode the settings give it (D10): live with its key, replay from the
committed recordings without one, and recording only when the evals runner asks."""

from pathlib import Path

import pytest

from backend.core.settings import Settings
from backend.providers.chain import ClassifierChain
from backend.providers.factory import (
    UnavailableClassifier,
    UnavailableDrafter,
    build_providers,
)
from backend.providers.jev import JevClassifier
from backend.providers.openai_classifier import OpenAIClassifier
from backend.providers.openai_drafter import OpenAIDrafter
from backend.providers.replay import (
    RecordingClassifier,
    RecordingDrafter,
    ReplayClassifier,
    ReplayDrafter,
    ReplayStore,
)
from backend.providers.types import ProviderUnavailable


def settings(mode: str = "auto", *, jev: str | None = None, openai: str | None = None) -> Settings:
    return Settings(
        _env_file=None,
        app_database_url="postgresql+psycopg://app_writer:pw@127.0.0.1:5432/fees",
        agent_database_url="postgresql+psycopg://agent_reader:pw@127.0.0.1:5432/fees",
        masking_salt="salt",
        provider_mode=mode,
        jev_api_key=jev,
        openai_api_key=openai,
    )


def chain_of(classifier: object) -> ClassifierChain:
    assert isinstance(classifier, ClassifierChain)
    return classifier


async def test_with_both_keys_every_provider_is_live() -> None:
    providers = build_providers(settings(jev="jev-key", openai="openai-key"))

    chain = chain_of(providers.classifier)
    assert isinstance(chain.primary, JevClassifier)
    assert isinstance(chain.backup, OpenAIClassifier)
    assert isinstance(providers.drafter, OpenAIDrafter)
    assert providers.chooser is chain.primary  # the fee and clause choices ask Jev alone
    assert providers.modes == {"jev": "live", "openai": "live"}
    await providers.close()


async def test_without_keys_every_provider_replays_the_recordings(tmp_path: Path) -> None:
    providers = build_providers(settings(), store=ReplayStore(tmp_path))

    chain = chain_of(providers.classifier)
    assert isinstance(chain.primary, ReplayClassifier)
    assert isinstance(chain.backup, ReplayClassifier)
    assert isinstance(providers.drafter, ReplayDrafter)
    assert providers.modes == {"jev": "replay", "openai": "replay"}
    await providers.close()


async def test_each_provider_has_its_own_mode() -> None:
    providers = build_providers(settings(jev="jev-key"))

    chain = chain_of(providers.classifier)
    assert isinstance(chain.primary, JevClassifier)
    assert isinstance(chain.backup, ReplayClassifier)
    assert isinstance(providers.drafter, ReplayDrafter)
    assert providers.modes == {"jev": "live", "openai": "replay"}
    await providers.close()


async def test_recording_wraps_the_live_providers() -> None:
    providers = build_providers(settings(jev="jev-key", openai="openai-key"), record=True)

    chain = chain_of(providers.classifier)
    assert isinstance(chain.primary, RecordingClassifier)
    assert isinstance(chain.backup, RecordingClassifier)
    assert isinstance(providers.drafter, RecordingDrafter)
    await providers.close()


async def test_live_mode_without_a_key_is_unavailable_not_a_crash() -> None:
    providers = build_providers(settings("live"))

    chain = chain_of(providers.classifier)
    assert isinstance(chain.primary, UnavailableClassifier)
    assert isinstance(providers.drafter, UnavailableDrafter)
    with pytest.raises(ProviderUnavailable) as raised:
        await chain.primary.classify({}, [])
    assert raised.value.reason == "auth"
    await providers.close()
