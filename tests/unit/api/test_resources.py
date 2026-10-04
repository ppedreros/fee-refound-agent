"""The API's resources come from the settings: live Jev only with a key, and a clean shutdown."""

from backend.api.resources import UnavailableClassifier, default_resources
from backend.core.settings import Settings
from backend.providers.jev import JevClassifier
from backend.providers.types import ProviderUnavailable


def settings(jev_api_key: str | None = None) -> Settings:
    return Settings(
        _env_file=None,
        app_database_url="postgresql+psycopg://app_writer:pw@127.0.0.1:5432/fees",
        agent_database_url="postgresql+psycopg://agent_reader:pw@127.0.0.1:5432/fees",
        masking_salt="salt",
        jev_api_key=jev_api_key,
    )


async def test_with_a_jev_key_the_classifier_is_live_jev_and_closes_cleanly() -> None:
    resources = default_resources(settings(jev_api_key="jev-test-key"))

    assert isinstance(resources.classifier, JevClassifier)
    assert resources.provider_modes == {"jev": "live", "openai": "replay"}
    await resources.close()


async def test_without_a_key_classification_is_unavailable_as_a_replay_miss() -> None:
    resources = default_resources(settings())

    assert isinstance(resources.classifier, UnavailableClassifier)
    try:
        await resources.classifier.classify({}, [])
    except ProviderUnavailable as error:
        assert error.reason == "replay_miss"
    else:
        raise AssertionError("expected ProviderUnavailable")
    await resources.close()
