"""Pruebas de los límites de seguridad: historial acotado y timeout."""

import httpx

from app.config import load_config
from app.llm import build_models


def ask(client, history):
    """Envía una pregunta con el historial dado."""
    return client.post("/ask", json={"question": "Hola", "history": history})


def test_history_with_exactly_the_maximum_messages_is_accepted(make_costs_client):
    client, _ = make_costs_client(max_history_messages=3)
    history = [{"role": "user", "content": "x"}] * 3

    assert ask(client, history).status_code == 200


def test_history_with_one_message_too_many_is_rejected(make_costs_client):
    client, _ = make_costs_client(max_history_messages=3)
    history = [{"role": "user", "content": "x"}] * 4

    assert ask(client, history).status_code == 422


def test_history_message_with_exactly_the_maximum_chars_is_accepted(
    make_costs_client,
):
    client, _ = make_costs_client(max_history_chars=10)

    assert ask(client, [{"role": "user", "content": "a" * 10}]).status_code == 200


def test_history_message_with_one_char_too_many_is_rejected(make_costs_client):
    client, _ = make_costs_client(max_history_chars=10)

    assert ask(client, [{"role": "user", "content": "a" * 11}]).status_code == 422


def test_gateway_client_uses_the_configured_timeout(monkeypatch, directory):
    created = []
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: created.append(kwargs) or object()
    )
    config = load_config({
        "MODEL_PROVIDER": "gateway", "MODEL_TIMEOUT_SECONDS": "7.5",
        "CF_ACCOUNT_ID": "acc", "CF_API_TOKEN": "token",
    })

    build_models(config, directory)

    assert created == [{"timeout": 7.5}]
