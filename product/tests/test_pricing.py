"""Pruebas de app.pricing: costo por llamada desde el archivo de precios."""

import pytest
from conftest import LARGE, SMALL

from app.pricing import PricingError, load_prices


def test_cost_is_priced_per_million_tokens(prices_file):
    prices = load_prices(prices_file)

    assert prices.cost(SMALL, 1_000_000, 500_000) == pytest.approx(2.0)
    assert prices.cost(LARGE, 1000, 500) == pytest.approx(0.02)
    assert prices.cost("fake", 1000, 500) == 0


def test_cached_call_costs_nothing(prices_file):
    prices = load_prices(prices_file)

    assert prices.cost(LARGE, 1000, 500, cached=True) == 0


def test_model_without_a_price_is_reported(prices_file):
    prices = load_prices(prices_file)

    with pytest.raises(PricingError, match="unknown-model"):
        prices.cost("unknown-model", 1, 1)
