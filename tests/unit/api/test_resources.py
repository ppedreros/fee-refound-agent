"""The API's resources: database sessions per role, and the providers in the mode each one has
(the modes themselves are tested in tests/unit/providers/test_factory.py)."""

from backend.api.resources import default_resources
from backend.core.settings import Settings
from backend.providers.chain import ClassifierChain
from backend.providers.jev import JevClassifier
from backend.providers.replay import ReplayDrafter


def settings(jev_api_key: str | None = None) -> Settings:
    return Settings(
        _env_file=None,
        app_database_url="postgresql+psycopg://app_writer:pw@127.0.0.1:5432/fees",
        agent_database_url="postgresql+psycopg://agent_reader:pw@127.0.0.1:5432/fees",
        masking_salt="salt",
        jev_api_key=jev_api_key,
    )


async def test_the_providers_follow_the_settings_and_close_cleanly() -> None:
    resources = default_resources(settings(jev_api_key="jev-key"))

    assert isinstance(resources.classifier, ClassifierChain)
    assert isinstance(resources.classifier.primary, JevClassifier)
    assert isinstance(resources.drafter, ReplayDrafter)
    assert resources.provider_modes == {"jev": "live", "openai": "replay"}
    await resources.close()
