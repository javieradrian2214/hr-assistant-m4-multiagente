"""Pruebas de la configuración nueva de la sesión 3."""

import pytest

from app.config import ConfigError, load_config

CF_VARIABLES = {
    "CF_ACCOUNT_ID": "acc", "CF_GATEWAY_ID": "gw", "CF_API_TOKEN": "token",
}


def test_cost_levers_have_the_documented_defaults():
    config = load_config({})

    assert config.model_small == "@cf/meta/llama-3.1-8b-instruct-fast"
    assert config.model_large == "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    assert config.routing is True
    assert config.router_max_chars == 80
    assert config.history_window == 6
    assert config.model_max_tokens == 300
    assert config.model_temperature == 0
    assert config.cache_ttl_seconds == 0
    assert config.prices_path == "data/model_prices.json"
    assert config.cf_gateway_id == "default"


@pytest.mark.parametrize("name, value", [
    ("ROUTING", "maybe"),
    ("HISTORY_WINDOW", "many"),
    ("MODEL_MAX_TOKENS", "0"),
    ("MODEL_TEMPERATURE", "hot"),
    ("CACHE_TTL_SECONDS", "-5"),
])
def test_invalid_lever_values_stop_the_service(name, value):
    with pytest.raises(ConfigError, match=name):
        load_config({name: value})


def test_safety_limits_have_the_documented_defaults():
    config = load_config({})

    assert config.model_timeout_seconds == 30.0
    assert config.max_history_messages == 100
    assert config.max_history_chars == 8000


@pytest.mark.parametrize("name, value", [
    ("MODEL_TIMEOUT_SECONDS", "0"),
    ("MODEL_TIMEOUT_SECONDS", "-1"),
    ("MODEL_TIMEOUT_SECONDS", "slow"),
    ("MAX_HISTORY_MESSAGES", "0"),
    ("MAX_HISTORY_MESSAGES", "1.5"),
    ("MAX_HISTORY_CHARS", "-10"),
    ("MAX_HISTORY_CHARS", "many"),
])
def test_invalid_safety_limits_stop_the_service(name, value):
    with pytest.raises(ConfigError, match=name):
        load_config({name: value})


@pytest.mark.parametrize("missing", ["CF_ACCOUNT_ID", "CF_API_TOKEN"])
def test_gateway_provider_requires_account_and_token(missing):
    env = {"MODEL_PROVIDER": "gateway", **CF_VARIABLES}
    del env[missing]

    with pytest.raises(ConfigError, match=missing):
        load_config(env)


def test_gateway_id_falls_back_to_default_when_missing():
    env = {"MODEL_PROVIDER": "gateway", **CF_VARIABLES}
    del env["CF_GATEWAY_ID"]

    config = load_config(env)

    assert config.cf_gateway_id == "default"
