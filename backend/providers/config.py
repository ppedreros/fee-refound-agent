"""Timeouts, retries and models for each provider, from `core/config/providers.yaml`."""

from functools import cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, NonNegativeInt, PositiveFloat

CONFIG_FILE = Path(__file__).resolve().parents[1] / "core" / "config" / "providers.yaml"


class CallPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    timeout_s: PositiveFloat
    retries: NonNegativeInt
    backoff_base_s: PositiveFloat
    backoff_cap_s: PositiveFloat


class ProviderConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: str
    policy: CallPolicy


class ProvidersConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    jev: ProviderConfig
    luna: ProviderConfig
    sol: ProviderConfig


class _Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    timeout_s: PositiveFloat
    retries: NonNegativeInt


class _Backoff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_s: PositiveFloat
    cap_s: PositiveFloat


class _File(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backoff: _Backoff
    jev: _Entry
    luna: _Entry
    sol: _Entry


@cache
def providers_config() -> ProvidersConfig:
    raw = _File.model_validate(yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")))

    def provider(entry: _Entry) -> ProviderConfig:
        return ProviderConfig(
            model=entry.model,
            policy=CallPolicy(
                timeout_s=entry.timeout_s,
                retries=entry.retries,
                backoff_base_s=raw.backoff.base_s,
                backoff_cap_s=raw.backoff.cap_s,
            ),
        )

    return ProvidersConfig(jev=provider(raw.jev), luna=provider(raw.luna), sol=provider(raw.sol))
