"""Cost per call from the price table (SPEC-providers, "Cost")."""

from decimal import Decimal

from backend.providers.config import providers_config
from backend.providers.cost import Usage, compute_cost


def test_a_sol_call_with_cache_reads() -> None:
    # 400 uncached input tokens at $2.00, 600 cache reads at $0.10, 200 output at $10.00 (per 1M).
    usage = Usage(tokens_in=1000, tokens_out=200, tokens_cached=600)

    assert compute_cost("gpt-6.1-sol", usage) == Decimal("0.002860")


def test_cache_writes_have_their_own_price() -> None:
    usage = Usage(tokens_in=1000, tokens_out=0, tokens_cache_write=1000)

    assert compute_cost("gpt-6.1-sol", usage) == Decimal("0.002500")


def test_jev_charges_input_only() -> None:
    assert compute_cost("jev-1.13.0", Usage(tokens_in=644, tokens_out=180)) == Decimal("0.000027")


def test_an_unknown_model_has_no_cost() -> None:
    assert compute_cost("gpt-unknown", Usage(tokens_in=10, tokens_out=10)) is None


def test_every_configured_model_has_a_price() -> None:
    config = providers_config()

    for model in (config.jev.model, config.luna.model, config.sol.model):
        assert compute_cost(model, Usage(tokens_in=1, tokens_out=1)) is not None
