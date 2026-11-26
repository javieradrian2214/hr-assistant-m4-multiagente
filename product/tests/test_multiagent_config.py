"""Configuración nueva de la sesión 5 (app.config)."""

import httpx
import pytest
from conftest import SMALL

from app.config import ConfigError, load_config
from app.gateway import GatewayModel

GATEWAY_ENV = {
    "MODEL_PROVIDER": "gateway",
    "CF_ACCOUNT_ID": "acc",
    "CF_API_TOKEN": "token-for-tests",
}
BODY = {
    "choices": [{"message": {"content": "respuesta"}}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
}


def test_orchestration_and_answer_length_have_defaults_and_can_be_set():
    defaults = load_config({})
    custom = load_config({"ORCHESTRATION": "multi", "MAX_ANSWER_CHARS": "500"})

    assert (defaults.orchestration, defaults.max_answer_chars) == ("single", 2000)
    assert (custom.orchestration, custom.max_answer_chars) == ("multi", 500)


@pytest.mark.parametrize("env", [
    {},
    {"ORCHESTRATION": ""},
    {"ORCHESTRATION": "   "},
])
def test_missing_or_blank_orchestration_falls_back_to_single(env):
    assert load_config(env).orchestration == "single"


@pytest.mark.parametrize("env", [
    {"ORCHESTRATION": "other"},
    {"ORCHESTRATION": "parallel"},
    {"MAX_ANSWER_CHARS": "0"},
    {"MAX_ANSWER_CHARS": "many"},
])
def test_invalid_orchestration_or_answer_length_prevents_start(env):
    with pytest.raises(ConfigError):
        load_config(env)


@pytest.mark.parametrize("gateway_id", ["", "   "])
def test_blank_gateway_id_falls_back_to_default_in_the_url(gateway_id):
    config = load_config({**GATEWAY_ENV, "CF_GATEWAY_ID": gateway_id})
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json=BODY)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    GatewayModel(SMALL, config, client).complete(
        [{"role": "user", "content": "hola"}]
    )

    assert config.cf_gateway_id == "default"
    assert "/v1/acc/default/workers-ai/" in seen["url"]
    assert "//workers-ai" not in seen["url"]
