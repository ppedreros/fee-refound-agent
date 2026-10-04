"""Application settings, read from the environment (and `.env` in local development)."""

from typing import Literal

from pydantic import BaseModel, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderMode = Literal["live", "replay"]


class ConfigError(Exception):
    """An invalid environment. The message names the variables, never their values."""


class ProviderModes(BaseModel, frozen=True):
    jev: ProviderMode
    openai: ProviderMode


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    provider_mode: Literal["auto", "live", "replay"] = "auto"
    jev_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    host: str = "127.0.0.1"
    port: int = 8000

    @field_validator("jev_api_key", "openai_api_key", mode="before")
    @classmethod
    def _blank_key_is_missing(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def provider_modes(self) -> ProviderModes:
        return ProviderModes(
            jev=self._mode_for(self.jev_api_key),
            openai=self._mode_for(self.openai_api_key),
        )

    def _mode_for(self, key: SecretStr | None) -> ProviderMode:
        if self.provider_mode == "auto":
            return "live" if key is not None else "replay"
        return self.provider_mode


def load_settings(env_file: str | None = ".env") -> Settings:
    """Load and check settings, failing fast with a message that is safe to print."""
    try:
        settings = Settings(_env_file=env_file)
    except ValidationError as error:
        names = sorted({str(detail["loc"][0]).upper() for detail in error.errors()})
        raise ConfigError(", ".join(names)) from None

    if settings.provider_mode == "live":
        missing = [
            name
            for name, key in (
                ("JEV_API_KEY", settings.jev_api_key),
                ("OPENAI_API_KEY", settings.openai_api_key),
            )
            if key is None
        ]
        if missing:
            raise ConfigError(f"PROVIDER_MODE=live needs {' and '.join(missing)}")

    return settings
