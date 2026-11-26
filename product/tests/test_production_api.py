"""Pruebas de la API segura que completan production.feature.

Supuestos de interfaz: el evento de auditoria se llama ``audit``, el rechazo
por clave ``auth_rejected`` y el rechazo por limite ``rate_limited``; todos
los eventos de una peticion autenticada llevan ``client``.
"""

import pytest
from conftest import ALICE_KEY, DEPARTMENTS

from app.compliance import ComplianceError
from app.config import ConfigError, load_config
from app.llm import FakeModel
from app.main import create_app

QUESTION = {"question": "¿Quién es EMP-0004?"}


def _headers(key):
    """Encabezado de clave de un cliente."""
    return {"X-API-Key": key}


def test_valid_key_can_read_metrics(make_secured_client):
    """``GET /metrics`` responde 200 con una clave valida."""
    client = make_secured_client()
    assert client.get("/metrics", headers=_headers(ALICE_KEY)).status_code == 200


def test_missing_key_on_metrics_is_rejected(make_secured_client):
    """``GET /metrics`` sin clave responde 401 con el mensaje acordado."""
    response = make_secured_client().get("/metrics")
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid or missing API key"}


def test_audit_event_names_the_client_but_not_the_key(
    make_secured_client, read_log
):
    """La auditoria de una herramienta lleva ``client`` y nunca la clave."""
    client = make_secured_client()
    client.post("/ask", json=QUESTION, headers=_headers(ALICE_KEY))
    audits = [e for e in read_log() if e["event"] == "audit"]
    assert audits
    assert all(e.get("client") == "alice" for e in audits)
    assert ALICE_KEY not in str(audits)


def test_rejected_key_is_logged_without_its_value(
    make_secured_client, read_log
):
    """Un rechazo deja el evento ``auth_rejected`` sin la clave probada."""
    client = make_secured_client()
    client.post("/ask", json=QUESTION, headers=_headers("guessed-key-000000"))
    events = read_log()
    assert any(e["event"] == "auth_rejected" for e in events)
    assert "guessed-key-000000" not in str(events)


def test_retry_after_shrinks_as_the_clock_advances(make_secured_client, clock):
    """Tras 20 s del minuto, ``Retry-After`` pasa de 60 a 40."""
    client = make_secured_client(rate_limit=1)
    client.post("/ask", json=QUESTION, headers=_headers(ALICE_KEY))
    first = client.post("/ask", json=QUESTION, headers=_headers(ALICE_KEY))
    clock.advance(20)
    second = client.post("/ask", json=QUESTION, headers=_headers(ALICE_KEY))
    assert first.status_code == second.status_code == 429
    assert (first.headers["Retry-After"], second.headers["Retry-After"]) == (
        "60", "40",
    )


def test_rate_limit_hit_is_logged_with_the_client(make_secured_client, read_log):
    """Superar el limite deja el evento ``rate_limited`` con el cliente."""
    client = make_secured_client(rate_limit=1)
    for _ in range(2):
        client.post("/ask", json=QUESTION, headers=_headers(ALICE_KEY))
    limited = [e for e in read_log() if e["event"] == "rate_limited"]
    assert [e["client"] for e in limited] == ["alice"]


def test_production_with_a_short_key_refuses_to_start(employees_file, directory):
    """``create_app`` en produccion rechaza una clave corta sin mostrarla."""
    config = load_config({
        "ENVIRONMENT": "production",
        "MODEL_PROVIDER": "gateway",
        "CF_ACCOUNT_ID": "account-id",
        "CF_API_TOKEN": "cloudflare-token",
        "EMPLOYEES_PATH": str(employees_file),
        "API_KEYS": "alice:short-secret",
    })
    with pytest.raises(ComplianceError) as caught:
        create_app(config, FakeModel(DEPARTMENTS), directory)
    assert "API_KEYS" in str(caught.value)
    assert "short-secret" not in str(caught.value)


def test_duplicate_client_in_api_keys_is_a_config_error():
    """Repetir un cliente falla al leer la configuracion, sin mostrar claves."""
    with pytest.raises(ConfigError) as caught:
        load_config({"API_KEYS": "alice:first-secret-key,alice:other-secret"})
    assert "API_KEYS" in str(caught.value)
    assert "first-secret-key" not in str(caught.value)
    assert "other-secret" not in str(caught.value)
