"""Application settings, read from the environment (and `.env` in local development)."""

from typing import Literal

from pydantic import BaseModel, Field, SecretStr, ValidationError, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

ProviderMode = Literal["live", "replay"]

# The role each database URL must log in as (SPEC-data, "Database roles").
ROLE_FOR_URL = {"app_database_url": "app_writer", "agent_database_url": "agent_reader"}


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
    app_database_url: SecretStr
    agent_database_url: SecretStr
    owner_database_url: SecretStr | None = None  # bootstrap only; compose gives it to migrate
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    masking_salt: SecretStr  # HMAC key for member ids in logs
    staff_id: str = Field(default="S07", pattern=r"^[A-Z][A-Z0-9]{1,15}$")  # who uses the UI
    host: str = "127.0.0.1"
    port: int = 8000

    @field_validator(
        "jev_api_key", "openai_api_key", "owner_database_url", "masking_salt", mode="before"
    )
    @classmethod
    def _blank_is_missing(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("app_database_url", "agent_database_url", "owner_database_url")
    @classmethod
    def _check_database_url(cls, value: SecretStr | None, info: ValidationInfo) -> SecretStr | None:
        # Error messages here are never shown (load_settings keeps only the names), but they
        # must not echo the URL anyway: it holds a password.
        if value is None:
            return None
        try:
            url = make_url(value.get_secret_value())
        except ArgumentError:
            raise ValueError("not a database URL") from None
        if url.get_backend_name() != "postgresql":
            raise ValueError("not a PostgreSQL URL")
        role = ROLE_FOR_URL.get(str(info.field_name))
        if role is not None and (url.username != role or not url.password):
            raise ValueError(f"must log in as {role}, with a password")
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
