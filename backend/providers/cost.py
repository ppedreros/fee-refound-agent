"""Cost of a model call from the price table in `core/config/pricing.yaml`."""

from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from pathlib import Path

import structlog
import yaml
from pydantic import BaseModel, ConfigDict, NonNegativeFloat

PRICING_FILE = Path(__file__).resolve().parents[1] / "core" / "config" / "pricing.yaml"
PER_MILLION = Decimal(1_000_000)
CENT_FRACTIONS = Decimal("0.000001")  # agent_steps.cost_usd is numeric(10,6)

log = structlog.get_logger()


@dataclass(frozen=True)
class Usage:
    """Token counts of one call. `tokens_in` includes the cached and cache-written tokens."""

    tokens_in: int
    tokens_out: int
    tokens_cached: int = 0
    tokens_cache_write: int = 0


class _Price(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    input: NonNegativeFloat
    output: NonNegativeFloat
    cache_read: NonNegativeFloat
    cache_write: NonNegativeFloat


@cache
def _prices() -> dict[str, _Price]:
    raw = yaml.safe_load(PRICING_FILE.read_text(encoding="utf-8"))
    return {model: _Price.model_validate(price) for model, price in raw.items()}


def compute_cost(model: str, usage: Usage) -> Decimal | None:
    """USD for one call, or None for a model the price table doesn't know (the UI then shows
    the cost as unavailable)."""
    price = _prices().get(model)
    if price is None:
        log.warning("price_unknown", model=model)
        return None
    plain_input = usage.tokens_in - usage.tokens_cached - usage.tokens_cache_write
    total = (
        _cost(plain_input, price.input)
        + _cost(usage.tokens_cached, price.cache_read)
        + _cost(usage.tokens_cache_write, price.cache_write)
        + _cost(usage.tokens_out, price.output)
    )
    return total.quantize(CENT_FRACTIONS)


def _cost(tokens: int, usd_per_million: float) -> Decimal:
    return Decimal(tokens) * Decimal(str(usd_per_million)) / PER_MILLION
