"""Pasos de los escenarios Gherkin de production.feature."""

import pytest
from conftest import ALICE_KEY, BOB_KEY, DEPARTMENTS
from pytest_bdd import given, parsers, scenarios, then, when

from app.compliance import ComplianceError
from app.config import Config
from app.llm import FakeModel
from app.main import create_app

scenarios("features/production.feature")

KEYS = {"alice": ALICE_KEY, "bob": BOB_KEY}
PUBLIC_PATHS = ("/", "/health", "/docs")


@pytest.fixture(name="context")
def context_fixture():
    """Guarda cliente, respuestas y errores entre pasos."""
    return {"responses": []}


def _remember(context, response):
    """Guarda la última respuesta y la agrega al historial."""
    context["response"] = response
    context["responses"].append(response)


@given(
    parsers.parse(
        "the secured assistant allowing {limit:d} requests per minute"
    )
)
def given_secured(context, make_secured_client, limit):
    """Arranca la API con dos clientes y el límite indicado."""
    context["client"] = make_secured_client(rate_limit=limit)


@given(
    parsers.parse(
        'production settings with a strong key and the provider "{provider}"'
    )
)
def given_production(context, employees_file, provider):
    """Configuración de producción válida salvo por el proveedor."""
    context["config"] = Config(
        model_provider=provider,
        agent_max_steps=3,
        max_question_chars=2000,
        employees_path=str(employees_file),
        environment="production",
        api_keys={"alice": ALICE_KEY},
    )


@when("the user asks without a key")
def when_asks_without_key(context):
    """Hace ``POST /ask`` sin el encabezado de clave."""
    _remember(context, context["client"].post("/ask", json={"question": "Hola"}))


@when(parsers.parse('the user asks with the key "{key}"'))
def when_asks_with_key(context, key):
    """Hace ``POST /ask`` con una clave literal."""
    _remember(
        context,
        context["client"].post(
            "/ask", json={"question": "Hola"}, headers={"X-API-Key": key}
        ),
    )


@when(parsers.parse('the user requests "{path}" with the key "{key}"'))
def when_requests_with_key(context, path, key):
    """Hace ``GET`` con una clave literal."""
    _remember(
        context, context["client"].get(path, headers={"X-API-Key": key})
    )


@when("the user requests the public paths without a key")
def when_requests_public(context):
    """Pide la página, el health check y los docs sin clave."""
    for path in PUBLIC_PATHS:
        _remember(context, context["client"].get(path))


@when(parsers.parse('the client "{name}" asks "{question}"'))
def when_client_asks(context, name, question):
    """El cliente pregunta con su propia clave."""
    _remember(
        context,
        context["client"].post(
            "/ask", json={"question": question},
            headers={"X-API-Key": KEYS[name]},
        ),
    )


@when(parsers.parse('the client "{name}" asks {times:d} times'))
def when_client_asks_many(context, name, times):
    """El cliente pregunta varias veces seguidas."""
    for _ in range(times):
        when_client_asks(context, name, "Hola")


@when(parsers.parse("the clock advances {seconds:d} seconds"))
def when_clock_advances(clock, seconds):
    """Adelanta el reloj inyectado."""
    clock.advance(seconds)


@when("the service starts")
def when_service_starts(context, directory):
    """Intenta crear la app y guarda el error de arranque, si hay."""
    try:
        create_app(context["config"], FakeModel(DEPARTMENTS), directory)
        context["startup_error"] = None
    except ComplianceError as error:
        context["startup_error"] = error


@then(parsers.parse("the response status is {status:d}"))
def then_status(context, status):
    """Comprueba el código HTTP de la última respuesta."""
    assert context["response"].status_code == status


@then(parsers.parse('the body detail is "{detail}"'))
def then_detail(context, detail):
    """El cuerpo trae el mensaje exacto."""
    assert context["response"].json()["detail"] == detail


@then("all the public responses have status 200")
def then_public_ok(context):
    """Las tres rutas públicas respondieron 200."""
    assert [r.status_code for r in context["responses"]] == [200] * 3


@then(parsers.parse("the first {count:d} responses were accepted"))
def then_first_accepted(context, count):
    """Las primeras peticiones dentro del límite dieron 200."""
    statuses = [r.status_code for r in context["responses"][:count]]
    assert statuses == [200] * count


@then(parsers.parse('the Retry-After header is "{seconds}"'))
def then_retry_after(context, seconds):
    """El encabezado dice cuántos segundos faltan."""
    assert context["response"].headers["Retry-After"] == seconds


@then(parsers.parse('startup is refused naming "{rule}"'))
def then_startup_refused(context, rule):
    """El arranque falló y el mensaje nombra la regla."""
    assert context["startup_error"] is not None
    assert rule in str(context["startup_error"])


@then(parsers.parse('the log marks the client "{name}"'))
def then_log_client(context, read_log, name):
    """Los eventos ``request`` y ``agent_run`` llevan el cliente."""
    context["events"] = read_log()
    marked = {
        e["event"] for e in context["events"] if e.get("client") == name
    }
    assert {"request", "agent_run"} <= marked


@then(
    parsers.parse(
        'nothing written contains the key of "{name}" nor "{other}"'
    )
)
def then_no_keys(context, name, other):
    """Ni el log ni las respuestas repiten una clave."""
    written = str(context["events"]) + "".join(
        r.text for r in context["responses"]
    )
    assert KEYS[name] not in written
    assert other not in written
