"""Pruebas de app.agent con un modelo guion inyectado."""

import json

from app.agent import Agent


class ScriptedModel:
    """Modelo de prueba que devuelve respuestas predefinidas en orden."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    def complete(self, messages):
        """Devuelve la siguiente respuesta del guion."""
        self.seen.append(list(messages))
        return self.replies.pop(0)


def question(text="pregunta"):
    """Mensajes iniciales de una consulta."""
    return [{"role": "user", "content": text}]


def test_tool_result_is_sent_back_to_the_model_as_a_user_message(directory):
    model = ScriptedModel([
        json.dumps({"tool": "get_employee", "args": {"employee_id": "EMP-0004"}}),
        json.dumps({"answer": "listo"}),
    ])

    result = Agent(model, directory, max_steps=3).run(question())

    last = model.seen[1][-1]
    assert last["role"] == "user"
    assert last["content"].startswith("Resultado de la herramienta: ")
    assert "Jorge Díaz" in last["content"]
    assert (result.answer, result.steps) == ("listo", 2)
    assert result.tools_used == ["get_employee"]
    assert result.input_tokens > 0 and result.output_tokens > 0


def test_invalid_model_output_or_unknown_tool_costs_a_step_without_failing(
    directory,
):
    model = ScriptedModel([
        "this is not json",
        json.dumps({"tool": "delete_everything", "args": {}}),
        json.dumps({"answer": "ok"}),
    ])

    result = Agent(model, directory, max_steps=3).run(question())

    assert result.answer == "ok"
    assert result.steps == 3
    assert not result.tools_used


def test_model_that_never_answers_hits_the_cap(directory):
    call = {"tool": "get_employee", "args": {"employee_id": "EMP-0001"}}
    model = ScriptedModel([json.dumps(call)] * 5)

    result = Agent(model, directory, max_steps=2).run(question())

    assert result.steps == 2
    assert result.answer == (
        "No pude completar la respuesta. Intenta con una pregunta más concreta."
    )
