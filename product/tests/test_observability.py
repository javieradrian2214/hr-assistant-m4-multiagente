"""Pruebas unitarias de la sesión 2 (observabilidad).

Supuestos de interfaz (el desarrollador debe respetarlos):

- ``app.config.Config`` gana ``service_name``, ``slo_p95_ms``,
  ``langsmith_tracing``, ``hide_inputs`` y ``hide_outputs``, todos con valor
  por omisión; ``load_config`` los lee de ``SERVICE_NAME``, ``SLO_P95_MS``,
  ``LANGSMITH_TRACING``, ``HIDE_INPUTS`` y ``HIDE_OUTPUTS``.
- ``app.metrics.Metrics(window)`` con ``record(latency_ms, is_error,
  input_tokens=0, output_tokens=0)`` y ``snapshot(slo_p95_ms)`` que devuelve
  ``requests``, ``error_rate``, ``latency_ms``, ``tokens`` y ``slo``.
- ``app.tracing.build_traceable(config, env)`` devuelve una fábrica de
  decoradores: ``build_traceable(config, env)("name")(func)``. Si las trazas
  están apagadas o falta ``LANGSMITH_API_KEY`` en ``env``, devuelve ``func``
  tal cual.
- ``app.agent.Agent(model, directory, max_steps, audit=None)``: llama
  ``audit(tool, args)`` una vez por herramienta ejecutada.
"""

import json
import re

import pytest

from app.agent import Agent
from app.config import ConfigError, load_config
from app.metrics import Metrics
from app.tracing import build_traceable

TOOL_CALL = json.dumps(
    {"tool": "get_employee", "args": {"employee_id": "EMP-0004"}}
)


class ScriptedModel:
    """Modelo de prueba que devuelve respuestas predefinidas en orden."""

    def __init__(self, replies):
        self.replies = list(replies)

    def complete(self, messages):
        """Devuelve la siguiente respuesta del guion."""
        del messages  # el guion no depende de la conversación
        return self.replies.pop(0)


# --- config ---------------------------------------------------------------


def test_observability_settings_have_safe_defaults():
    config = load_config({})

    assert config.service_name == "hr-assistant"
    assert config.slo_p95_ms == 2000
    assert config.langsmith_tracing is False
    assert config.hide_inputs is True
    assert config.hide_outputs is True


def test_invalid_boolean_setting_is_rejected():
    with pytest.raises(ConfigError, match="HIDE_INPUTS"):
        load_config({"HIDE_INPUTS": "maybe"})


def test_slo_target_must_be_positive():
    with pytest.raises(ConfigError, match="SLO_P95_MS"):
        load_config({"SLO_P95_MS": "0"})


# --- metrics --------------------------------------------------------------


def test_metrics_without_data_do_not_divide_by_zero():
    snapshot = Metrics(window=10).snapshot(slo_p95_ms=2000)

    assert snapshot["requests"] == 0
    assert snapshot["error_rate"] == 0
    assert snapshot["latency_ms"] == {"p50": 0, "p95": 0}


def test_metrics_compute_percentiles_error_rate_and_tokens():
    metrics = Metrics(window=200)
    for latency in range(1, 101):
        metrics.record(latency, is_error=latency > 75, input_tokens=2,
                       output_tokens=1)

    snapshot = metrics.snapshot(slo_p95_ms=2000)

    assert snapshot["requests"] == 100
    assert snapshot["error_rate"] == pytest.approx(0.25)
    assert 49 <= snapshot["latency_ms"]["p50"] <= 51
    assert 94 <= snapshot["latency_ms"]["p95"] <= 96
    assert snapshot["tokens"] == {"input": 200, "output": 100}


def test_metrics_latency_window_forgets_old_samples():
    metrics = Metrics(window=3)
    for latency in (9000, 9000, 1, 1, 1):
        metrics.record(latency, is_error=False)

    assert metrics.snapshot(slo_p95_ms=2000)["latency_ms"]["p95"] == 1


def test_slo_is_met_only_when_p95_is_below_the_target():
    at_limit, below = Metrics(window=5), Metrics(window=5)
    for _ in range(5):
        at_limit.record(2000, is_error=False)
        below.record(1999, is_error=False)

    assert at_limit.snapshot(slo_p95_ms=2000)["slo"] == {
        "p95_ms_target": 2000, "met": False,
    }
    assert below.snapshot(slo_p95_ms=2000)["slo"]["met"] is True


# --- tracing --------------------------------------------------------------


def test_tracing_without_api_key_returns_the_function_untouched():
    def work():
        return "ok"

    config = load_config({"LANGSMITH_TRACING": "true"})

    assert build_traceable(config, {})("agent_run")(work) is work


def test_tracing_turned_off_returns_the_function_untouched():
    def work():
        return "ok"

    config = load_config({})
    env = {"LANGSMITH_API_KEY": "fake-key-for-tests"}

    assert build_traceable(config, env)("agent_run")(work) is work


# --- agent audit ----------------------------------------------------------


def test_agent_audits_each_tool_it_runs(directory):
    audited = []
    model = ScriptedModel([TOOL_CALL, json.dumps({"answer": "listo"})])
    agent = Agent(model, directory, max_steps=3,
                  audit=lambda tool, args: audited.append((tool, args)))

    agent.run([{"role": "user", "content": "pregunta"}])

    assert audited == [("get_employee", {"employee_id": "EMP-0004"})]


def test_agent_does_not_audit_invalid_tools(directory):
    audited = []
    model = ScriptedModel([
        json.dumps({"tool": "delete_everything", "args": {}}),
        json.dumps({"tool": "get_employee", "args": {}}),
        json.dumps({"answer": "ok"}),
    ])
    agent = Agent(model, directory, max_steps=3,
                  audit=lambda tool, args: audited.append(tool))

    agent.run([{"role": "user", "content": "pregunta"}])

    assert not audited


# --- API ------------------------------------------------------------------


def test_hostile_request_id_is_replaced_by_a_uuid(make_observed_client):
    client = make_observed_client()

    response = client.get("/health", headers={"X-Request-ID": "x" * 300})

    returned = response.headers["X-Request-ID"]
    assert len(returned) < 100
    assert re.fullmatch(r"[0-9a-f-]{36}", returned)


def test_log_lines_have_the_required_fields_and_utc_timestamp(
    make_observed_client, read_log
):
    client = make_observed_client()

    client.get("/health", headers={"X-Request-ID": "abc"})
    events = read_log()

    assert len(events) == 1
    event = events[0]
    assert event["event"] == "request"
    assert event["service"] == "hr-test"
    assert event["request_id"] == "abc"
    assert (event["method"], event["path"], event["status"]) == (
        "GET", "/health", 200,
    )
    assert event["latency_ms"] >= 0
    assert event["ts"].startswith("2026-01-02T03:04:05")
    assert event["ts"].endswith(("+00:00", "Z"))


def test_agent_run_event_reports_sizes_but_no_text(
    make_observed_client, read_log
):
    client = make_observed_client()
    history = [{"role": "user", "content": "Hola"}]

    client.post("/ask", json={"question": "¿Quién es EMP-0004?",
                              "history": history})
    run = next(e for e in read_log() if e["event"] == "agent_run")

    assert run["question_chars"] == len("¿Quién es EMP-0004?")
    assert run["history_messages"] == 1
    assert run["steps"] == 2
    assert run["tools"] == ["get_employee"]
    assert run["input_tokens"] > 0 and run["output_tokens"] > 0
    assert "stopped" in run
    assert "question" not in run and "answer" not in run


def _audit_events_for(make_observed_client, read_log, args, tool="get_employee"):
    """Corre una pregunta donde el modelo llama ``tool`` con ``args``."""
    model = ScriptedModel([
        json.dumps({"tool": tool, "args": args}),
        json.dumps({"answer": "listo"}),
    ])
    client = make_observed_client(model=model)

    client.post("/ask", json={"question": "pregunta"})

    return [e for e in read_log() if e["event"] == "audit"]


def test_audit_event_drops_keys_the_model_invented(
    make_observed_client, read_log
):
    audits = _audit_events_for(
        make_observed_client, read_log,
        {"employee_id": "EMP-0004", "secret": "SECRETO-INVENTADO"},
    )

    assert len(audits) == 1
    assert audits[0]["args"] == {"employee_id": "EMP-0004"}
    assert "SECRETO-INVENTADO" not in json.dumps(audits)


def test_audit_event_drops_values_longer_than_64_characters(
    make_observed_client, read_log
):
    long_id = "EMP-" + "9" * 100
    audits = _audit_events_for(
        make_observed_client, read_log,
        {"employee_id": long_id, "department": "Ventas"},
    )

    assert len(audits) == 1
    assert audits[0]["args"] == {"department": "Ventas"}
    assert long_id not in json.dumps(audits)


def test_audit_event_drops_values_that_are_not_text(
    make_observed_client, read_log
):
    audits = _audit_events_for(
        make_observed_client, read_log,
        {"employee_id": {"nested": "EMP-0004"}, "department": "Ventas"},
    )

    assert len(audits) == 1
    assert audits[0]["args"] == {"department": "Ventas"}


def test_home_page_shows_the_request_id(make_observed_client):
    page = make_observed_client().get("/").text

    assert "request_id" in page
    assert "innerHTML" not in page
