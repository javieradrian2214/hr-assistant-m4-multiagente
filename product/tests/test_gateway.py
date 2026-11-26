"""Pruebas de app.gateway con httpx.MockTransport (sin red)."""

import json

import httpx
import pytest
from conftest import SMALL

from app.config import Config
from app.gateway import GatewayModel, ModelUnavailable

TOKEN = "super-secret-token"
URL = (
    "https://gateway.ai.cloudflare.com/v1/acc/gw/workers-ai/v1/chat/completions"
)
MESSAGES = [{"role": "user", "content": "hola"}]
BODY = {
    "choices": [{"message": {"content": "respuesta"}}],
    "usage": {"prompt_tokens": 12, "completion_tokens": 5},
}


def make_model(handler, **overrides):
    """GatewayModel sobre un transporte simulado."""
    config = Config(
        model_provider="gateway", agent_max_steps=3, max_question_chars=2000,
        employees_path="unused.json", cf_account_id="acc", cf_gateway_id="gw",
        cf_api_token=TOKEN, model_max_tokens=300, model_temperature=0.0,
        **overrides,
    )
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return GatewayModel(SMALL, config, client)


def test_request_has_the_url_token_and_body_from_the_spec():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=BODY)

    make_model(handler).complete(MESSAGES)

    assert seen["url"] == URL
    assert seen["auth"] == f"Bearer {TOKEN}"
    assert seen["body"] == {
        "model": SMALL, "messages": MESSAGES, "max_tokens": 300,
        "temperature": 0.0,
    }


def test_text_and_tokens_are_read_from_the_response():
    model = make_model(lambda request: httpx.Response(200, json=BODY))

    completion = model.complete(MESSAGES)

    assert completion.text == "respuesta"
    assert completion.model == SMALL
    assert (completion.input_tokens, completion.output_tokens) == (12, 5)
    assert completion.cached is False


@pytest.mark.parametrize("ttl, expected", [(0, None), (60, "60")])
def test_cache_ttl_header_is_sent_only_when_ttl_is_positive(ttl, expected):
    seen = {}

    def handler(request):
        seen["ttl"] = request.headers.get("cf-aig-cache-ttl")
        return httpx.Response(200, json=BODY)

    make_model(handler, cache_ttl_seconds=ttl).complete(MESSAGES)

    assert seen["ttl"] == expected


@pytest.mark.parametrize("status, cached", [("HIT", True), ("MISS", False)])
def test_cache_status_header_decides_if_the_call_is_cached(status, cached):
    model = make_model(lambda request: httpx.Response(
        200, json=BODY, headers={"cf-aig-cache-status": status}
    ))

    assert model.complete(MESSAGES).cached is cached


def test_http_and_network_failures_become_model_unavailable_without_the_token():
    def network_down(request):
        raise httpx.ConnectError("no route", request=request)

    handlers = [
        lambda request: httpx.Response(500, json={"error": "boom"}),
        network_down,
    ]
    for handler in handlers:
        with pytest.raises(ModelUnavailable) as raised:
            make_model(handler).complete(MESSAGES)
        assert TOKEN not in str(raised.value)
