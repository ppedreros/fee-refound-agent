"""The API's resources come from the settings: Jev, then Luna, each live only with its key, and a
clean shutdown."""

import pytest

from backend.api.resources import UnavailableClassifier, default_resources
from backend.core.settings import Settings
from backend.providers.chain import ClassifierChain, ClassifierUnavailable
from backend.providers.jev import JevClassifier
from backend.providers.openai_classifier import OpenAIClassifier


def settings(jev_api_key: str | None = None, openai_api_key: str | None = None) -> Settings:
    return Settings(
        _env_file=None,
        app_database_url="postgresql+psycopg://app_writer:pw@127.0.0.1:5432/fees",
        agent_database_url="postgresql+psycopg://agent_reader:pw@127.0.0.1:5432/fees",
        masking_salt="salt",
        jev_api_key=jev_api_key,
        openai_api_key=openai_api_key,
    )


async def test_with_both_keys_jev_answers_first_and_luna_backs_it_up() -> None:
    resources = default_resources(settings(jev_api_key="jev-key", openai_api_key="openai-key"))

    chain = resources.classifier
    assert isinstance(chain, ClassifierChain)
    assert isinstance(chain.primary, JevClassifier)
    assert isinstance(chain.backup, OpenAIClassifier)
    assert resources.provider_modes == {"jev": "live", "openai": "live"}
    await resources.close()


async def test_a_provider_without_a_key_is_unavailable_and_the_chain_moves_on() -> None:
    resources = default_resources(settings(openai_api_key="openai-key"))

    chain = resources.classifier
    assert isinstance(chain, ClassifierChain)
    assert isinstance(chain.primary, UnavailableClassifier)
    assert isinstance(chain.backup, OpenAIClassifier)
    await resources.close()


async def test_without_any_key_classification_is_unavailable_as_a_replay_miss() -> None:
    resources = default_resources(settings())

    with pytest.raises(ClassifierUnavailable) as raised:
        await resources.classifier.classify({}, [])

    assert (raised.value.primary_reason, raised.value.reason) == ("replay_miss", "replay_miss")
    await resources.close()
