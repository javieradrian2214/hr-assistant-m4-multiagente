"""Pasos de los escenarios Gherkin de hr_assistant.feature."""

import os

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("features/hr_assistant.feature")


@pytest.fixture(name="context")
def context_fixture():
    """Guarda cliente y última respuesta entre pasos."""
    return {}


@given(parsers.parse("the assistant is running with a step cap of {cap:d}"))
def given_assistant(context, make_client, cap):
    """Arranca la API con el tope indicado."""
    context["client"] = make_client(max_steps=cap)


@when(parsers.parse('the user asks "{question}" with a one message history'))
def when_user_asks_with_history(context, question):
    """Pregunta enviando un historial de un mensaje."""
    history = [{"role": "user", "content": "Hola"}]
    context["response"] = context["client"].post(
        "/ask", json={"question": question, "history": history}
    )


@when(parsers.parse('the user asks "{question}"'))
def when_user_asks(context, question):
    """Pregunta sin historial."""
    context["response"] = context["client"].post(
        "/ask", json={"question": question}
    )


@when(parsers.parse("the user asks a question of {length:d} characters"))
def when_user_asks_length(context, length):
    """Pregunta con un largo exacto de caracteres."""
    context["response"] = context["client"].post(
        "/ask", json={"question": "a" * length}
    )


@when(parsers.parse('the client requests "{path}"'))
def when_client_requests(context, path):
    """Hace un GET a la ruta indicada."""
    context["response"] = context["client"].get(path)


@then(parsers.parse("the response status is {status:d}"))
def then_status(context, status):
    """Comprueba el código HTTP."""
    assert context["response"].status_code == status


@then(parsers.parse('the answer contains "{text}"'))
def then_answer_contains(context, text):
    """La respuesta incluye el texto."""
    assert text in context["response"].json()["answer"]


@then(parsers.parse('the answer is "{text}"'))
def then_answer_is(context, text):
    """La respuesta es exactamente el texto."""
    assert context["response"].json()["answer"] == text


@then(parsers.parse('the tools used are "{tool}"'))
def then_tools(context, tool):
    """Solo se usó la herramienta indicada."""
    assert context["response"].json()["tools_used"] == [tool]


@then("the tools used are empty")
def then_no_tools(context):
    """No se usó ninguna herramienta."""
    assert context["response"].json()["tools_used"] == []


@then(parsers.parse("the number of steps is {steps:d}"))
def then_steps(context, steps):
    """Número de vueltas del bucle."""
    assert context["response"].json()["steps"] == steps


@then("the health status is ok and has a pid")
def then_health(context):
    """El health informa el proceso actual."""
    body = context["response"].json()
    assert body["status"] == "ok"
    assert body["pid"] == os.getpid()


@then("the page has the test ids question, send and answer")
def then_page_ids(context):
    """La página trae los tres data-testid."""
    for test_id in ("question", "send", "answer"):
        assert f'data-testid="{test_id}"' in context["response"].text


@then("the page never uses innerHTML")
def then_no_inner_html(context):
    """La página pinta con textContent."""
    page = context["response"].text
    assert "innerHTML" not in page
    assert "textContent" in page
