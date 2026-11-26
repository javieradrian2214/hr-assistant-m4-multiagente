"""Pasos de los escenarios Gherkin de observability.feature."""

import uuid

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("features/observability.feature")


class BrokenModel:
    """Modelo que truena con un mensaje que no debe filtrarse."""

    def complete(self, messages):
        """Siempre lanza ``RuntimeError``."""
        raise RuntimeError("boom-secret")


@pytest.fixture(name="context")
def context_fixture():
    """Guarda cliente, pregunta y última respuesta entre pasos."""
    return {}


@given(
    parsers.parse(
        "the observed assistant with a clock that advances {ms:d} "
        "milliseconds per reading"
    )
)
def given_observed(context, make_observed_client, ms):
    """Arranca la API con un reloj falso que avanza ``ms`` por lectura."""
    context["client"] = make_observed_client(step_ms=ms)


@given("the observed assistant with a broken model")
def given_broken(context, make_observed_client):
    """Arranca la API con un modelo que siempre truena."""
    context["client"] = make_observed_client(model=BrokenModel())


def _ask(context, question, headers=None):
    """Hace ``POST /ask`` y guarda pregunta y respuesta."""
    context["question"] = question
    context["response"] = context["client"].post(
        "/ask", json={"question": question}, headers=headers or {}
    )


@when(
    parsers.parse('the user sends "{question}" with the request id "{rid}"')
)
def when_asks_with_id(context, question, rid):
    """Pregunta mandando ``X-Request-ID``."""
    _ask(context, question, {"X-Request-ID": rid})


@when(parsers.parse('the user asks "{question}"'))
def when_asks(context, question):
    """Pregunta sin encabezado de id."""
    _ask(context, question)


@when("the user sends an empty question")
def when_empty_question(context):
    """Manda una pregunta vacía, que debe dar 422."""
    _ask(context, "")


@then(parsers.parse("the response status is {status:d}"))
def then_status(context, status):
    """Comprueba el código HTTP."""
    assert context["response"].status_code == status


@then("the X-Request-ID header is a UUID")
def then_header_uuid(context):
    """El encabezado trae un UUID válido."""
    assert uuid.UUID(context["response"].headers["X-Request-ID"])


@then(parsers.parse('the X-Request-ID header is "{rid}"'))
def then_header_is(context, rid):
    """El encabezado repite el id del cliente."""
    assert context["response"].headers["X-Request-ID"] == rid


@then("the X-Request-ID header is present")
def then_header_present(context):
    """El encabezado existe y no está vacío."""
    assert context["response"].headers["X-Request-ID"]


@then("the body request_id equals the header")
def then_body_matches_header(context):
    """El cuerpo y el encabezado llevan el mismo id."""
    response = context["response"]
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


@then(parsers.parse("the log has a request event with status {status:d}"))
def then_request_event_status(read_log, status):
    """Existe un evento ``request`` con ese status."""
    events = [e for e in read_log() if e["event"] == "request"]
    assert [e["status"] for e in events] == [status]


@then("the log has the events request, agent_run and audit")
def then_log_has_events(context, read_log):
    """El log trae los tres eventos de una pregunta."""
    context["events"] = read_log()
    names = {e["event"] for e in context["events"]}
    assert {"request", "agent_run", "audit"} <= names


@then("every log line has the request id of the response")
def then_same_request_id(context):
    """Todas las líneas comparten el id de la respuesta."""
    expected = context["response"].headers["X-Request-ID"]
    assert {e["request_id"] for e in context["events"]} == {expected}


@then(parsers.parse('the audit event names the tool "{tool}"'))
def then_audit_tool(context, tool):
    """El evento ``audit`` registra la herramienta llamada."""
    audits = [e for e in context["events"] if e["event"] == "audit"]
    assert [(a["action"], a["tool"]) for a in audits] == [("tool_call", tool)]


@then("the log does not contain the question nor the answer")
def then_no_texts_in_log(context, capsys):
    """Ni la pregunta ni la respuesta aparecen en la salida."""
    out = capsys.readouterr().out
    assert out.strip()
    assert context["question"] not in out
    assert context["response"].json()["answer"] not in out


@then(parsers.parse('the body detail is "{detail}" with a request id'))
def then_internal_error_body(context, detail):
    """El 500 trae el detalle genérico y el ``request_id``."""
    response = context["response"]
    body = response.json()
    assert body["detail"] == detail
    assert body["request_id"] == response.headers["X-Request-ID"]


@then(parsers.parse('the log has an error event of type "{error_type}"'))
def then_error_event(context, read_log, error_type):
    """El log trae un evento ``error`` con el tipo de excepción."""
    context["events"] = read_log()
    errors = [e for e in context["events"] if e["event"] == "error"]
    assert [e["error_type"] for e in errors] == [error_type]


@then(parsers.parse('neither the response nor the log contain "{secret}"'))
def then_no_secret(context, secret):
    """El mensaje de la excepción no sale por ningún lado."""
    assert secret not in context["response"].text
    assert secret not in str(context["events"])


@then("the metrics show at least 2 requests and positive input tokens")
def then_metrics_counts(context):
    """``/metrics`` cuenta peticiones y tokens."""
    metrics = context["client"].get("/metrics").json()
    assert metrics["requests"] >= 2
    assert metrics["tokens"]["input"] > 0


@then("the metrics say the SLO is met")
def then_slo_met(context):
    """El p95 está por debajo de la meta."""
    assert context["client"].get("/metrics").json()["slo"]["met"] is True


@then("the metrics say the SLO is not met")
def then_slo_not_met(context):
    """El p95 supera la meta."""
    assert context["client"].get("/metrics").json()["slo"]["met"] is False
