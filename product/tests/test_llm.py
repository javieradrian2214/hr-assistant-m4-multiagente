"""Pruebas del modelo simulado de app.llm."""

import json

from app.llm import FakeModel, count_input_tokens, count_output_tokens

DEPARTMENTS = ["Tecnología", "Ventas", "Finanzas"]


def ask_model(text):
    """Llama al modelo simulado y decodifica su JSON."""
    return json.loads(FakeModel(DEPARTMENTS).complete(
        [{"role": "user", "content": text}]
    ))


def test_tool_result_becomes_the_final_answer():
    reply = ask_model("Resultado de la herramienta: EMP-0004 Jorge")

    assert reply == {"answer": "Según el directorio: EMP-0004 Jorge"}


def test_employee_id_requests_get_employee():
    reply = ask_model("Dime de EMP-0004 en Finanzas")

    assert reply == {"tool": "get_employee", "args": {"employee_id": "EMP-0004"}}


def test_known_department_requests_search_by_department():
    reply = ask_model("Quiénes trabajan en Ventas")

    assert reply["tool"] == "search_by_department"
    assert reply["args"] == {"department": "Ventas"}


def test_other_questions_get_the_help_answer():
    reply = ask_model("Hola")

    assert reply == {
        "answer": "Pregúntame por un empleado (EMP-0001) o un departamento."
    }


def test_tokens_are_counted_as_words():
    messages = [
        {"role": "user", "content": "uno dos tres"},
        {"role": "assistant", "content": "cuatro cinco"},
    ]

    assert count_input_tokens(messages) == 5
    assert count_output_tokens("hola mundo amigo") == 3


# --- sesión 5: EMPLOYEE_ID_PATTERN y with_prompt -----------------------------
# Los nombres nuevos se importan dentro de cada prueba para que su ausencia no
# tumbe las pruebas del modelo simulado de arriba.


class RecordingInnerModel:
    """Modelo interno que anota las conversaciones que recibe."""

    def __init__(self):
        self.seen = []

    def complete(self, messages):
        """Anota los mensajes y devuelve un texto fijo."""
        self.seen.append(list(messages))
        return "ok"


def test_employee_id_pattern_finds_every_id_and_ignores_dates():
    from app.llm import EMPLOYEE_ID_PATTERN  # pylint: disable=import-outside-toplevel

    found = EMPLOYEE_ID_PATTERN.findall("Compara EMP-0001 y EMP-0002")

    assert found == ["EMP-0001", "EMP-0002"]
    assert EMPLOYEE_ID_PATTERN.search("Ingresó el 2021-07-19") is None


def test_system_prompt_model_with_prompt_sends_the_new_prompt_first():
    from app.llm import (  # pylint: disable=import-outside-toplevel
        SYSTEM_PROMPT, SystemPromptModel,
    )
    inner = RecordingInnerModel()
    original = SystemPromptModel(inner)
    question = [{"role": "user", "content": "EMP-0004"}]

    original.with_prompt("Solo get_employee").complete(question)
    original.complete(question)

    first, second = iter(inner.seen)
    assert first == [{"role": "system", "content": "Solo get_employee"}, *question]
    # El modelo original no cambia: sigue con el mensaje de sistema de siempre.
    assert second[0] == {"role": "system", "content": SYSTEM_PROMPT}


def test_named_fake_model_with_prompt_returns_the_same_model():
    from app.llm import NamedFakeModel  # pylint: disable=import-outside-toplevel

    model = NamedFakeModel("fake", DEPARTMENTS)

    assert model.with_prompt("Solo search_by_department") is model
