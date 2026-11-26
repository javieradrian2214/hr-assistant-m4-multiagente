"""Pasos de los escenarios Gherkin de costs.feature."""

import pytest
from conftest import LARGE, SMALL
from pytest_bdd import given, parsers, scenarios, then, when

from app.gateway import ModelUnavailable

scenarios("features/costs.feature")

QUESTION_COST = 0.002  # 1000 tokens de entrada y 500 de salida con SMALL


@pytest.fixture(name="context")
def context_fixture():
    """Guarda cliente, modelos y respuestas entre pasos."""
    return {"responses": []}


def _start(context, make_costs_client, **options):
    """Arranca la API y guarda cliente y modelos."""
    context["client"], context["models"] = make_costs_client(**options)


@given("the assistant is running with default levers")
def given_default(context, make_costs_client):
    """Configuración por omisión de las palancas."""
    _start(context, make_costs_client)


@given("the assistant is running with routing off")
def given_routing_off(context, make_costs_client):
    """Enrutamiento apagado."""
    _start(context, make_costs_client, routing=False)


@given(parsers.parse("the assistant is running with a history window of {size:d}"))
def given_window(context, make_costs_client, size):
    """Ventana de historial del tamaño indicado."""
    _start(context, make_costs_client, history_window=size)


@given("the assistant is running with a cache that always hits")
def given_cache_hit(context, make_costs_client):
    """Modelos que informan cada llamada como cacheada."""
    _start(context, make_costs_client, cached=True)


@given("the assistant is running with a model that is down")
def given_model_down(context, make_costs_client):
    """Modelos que fallan con ``ModelUnavailable``."""
    _start(context, make_costs_client, error=ModelUnavailable("down"))


@when(parsers.parse('the user asks "{question}" with a history of {size:d} messages'))
def when_ask_with_history(context, question, size):
    """Pregunta con un historial numerado m1, m2, ..."""
    history = [
        {"role": "user" if i % 2 else "assistant", "content": f"m{i}"}
        for i in range(1, size + 1)
    ]
    context["responses"].append(context["client"].post(
        "/ask", json={"question": question, "history": history}
    ))


@when(parsers.parse('the user asks "{question}"'))
def when_ask(context, question):
    """Pregunta sin historial."""
    context["responses"].append(
        context["client"].post("/ask", json={"question": question})
    )


@then(parsers.parse("the response status is {status:d}"))
def then_status(context, status):
    """Código HTTP de la última respuesta."""
    assert context["responses"][-1].status_code == status


@then("the model used is the small model")
def then_small(context):
    """La respuesta dice que respondió el modelo pequeño."""
    assert context["responses"][-1].json()["model"] == SMALL


@then("the model used is the large model")
def then_large(context):
    """La respuesta dice que respondió el modelo grande."""
    assert context["responses"][-1].json()["model"] == LARGE


@then("the route reason is not empty")
def then_route(context):
    """El enrutador explica su decisión."""
    assert context["responses"][-1].json()["route"]


@then(parsers.parse(
    "the model received the last {size:d} history messages and the question"
))
def then_window(context, size):
    """El primer mensaje enviado son los últimos del historial."""
    received = [m for model in context["models"].values() for m in model.seen]
    contents = [m["content"] for m in received[0]]
    assert contents == ["m3", "m4", "Quien es EMP-0004?"][-(size + 1):]


@then(parsers.parse("the cached calls are {count:d}"))
def then_cached(context, count):
    """Número de llamadas cacheadas."""
    assert context["responses"][-1].json()["cached_calls"] == count


@then(parsers.parse("the cost is {amount:d} dollars"))
def then_cost_zero(context, amount):
    """Costo de la respuesta."""
    assert context["responses"][-1].json()["cost_usd"] == amount


@then('the detail is "model unavailable" and the request id is present')
def then_502_body(context):
    """El 502 trae el detalle y el id de la petición."""
    response = context["responses"][-1]
    body = response.json()
    assert body["detail"] == "model unavailable"
    assert body["request_id"] == response.headers["X-Request-ID"]


@then("the metrics cost is twice the cost of one answer")
def then_metrics_cost(context):
    """``/metrics`` acumula el costo de las dos respuestas."""
    one = context["responses"][0].json()["cost_usd"]
    assert one == pytest.approx(QUESTION_COST)
    total = context["client"].get("/metrics").json()["cost_usd"]
    assert total == pytest.approx(2 * one)
