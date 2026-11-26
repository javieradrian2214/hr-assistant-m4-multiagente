"""Pruebas del supervisor determinístico (app.supervisor).

Supuesto de interfaz: ``decide(question, departments, config)`` devuelve
``Decision(agent, reason, model, route)`` sin recibir ni llamar a un modelo.
"""

import pytest
from conftest import DEPARTMENTS, LARGE, SMALL
from multiagent_support import ScriptedModel, build_client

from app.config import Config


def decide(question, departments, config):
    """Llama a ``app.supervisor.decide`` importándolo en el momento.

    Así, si el módulo todavía no existe, fallan las pruebas y no la
    recolección de toda la suite.
    """
    from app.supervisor import decide as real  # pylint: disable=import-outside-toplevel

    return real(question, departments, config)


def make_config(**overrides):
    """Configuración mínima con nombres de modelo de prueba."""
    return Config(
        model_provider="fake", agent_max_steps=3, max_question_chars=2000,
        employees_path="unused.json", model_small=SMALL, model_large=LARGE,
        **overrides,
    )


@pytest.mark.parametrize("question, agent, reason", [
    ("Compara EMP-0001 y EMP-0002", "AnalystAgent", "analysis keyword 'compara'"),
    ("ANALIZA Ventas", "AnalystAgent", "analysis keyword 'analiza'"),
    ("Datos de EMP-0001 y EMP-0002", "AnalystAgent", "multiple employee ids"),
    ("Gente de Ventas y Finanzas", "AnalystAgent", "multiple departments"),
    ("Quién es EMP-0004 de Tecnología", "EmployeeAgent", "one employee id"),
    ("EMP-0001 otra vez EMP-0001", "EmployeeAgent", "one employee id"),
    ("Quién trabaja en tecnologia", "DepartmentAgent", "department 'Tecnología'"),
    ("Hello there", "AnalystAgent", "no rule matched"),
])
def test_rules_pick_one_specialist_in_order_with_a_reason(question, agent, reason):
    decision = decide(question, DEPARTMENTS, make_config())

    assert decision.agent == agent
    assert decision.reason == reason


def test_analyst_uses_the_large_model_only_when_an_analysis_rule_matches():
    config = make_config()

    by_rule = decide("Datos de EMP-0001 y EMP-0002", DEPARTMENTS, config)
    fallback = decide("Hello there", DEPARTMENTS, config)

    assert (by_rule.model, by_rule.route) == (LARGE, "analyst uses MODEL_LARGE")
    assert (fallback.model, fallback.route) == (SMALL, "simple question")


def test_supervisor_adds_no_model_calls_in_multi_mode(
        employees_file, prices_file, directory):
    replies = [
        {"tool": "get_employee", "args": {"employee_id": "EMP-0004"}},
        {"answer": "Jorge Díaz"},
    ]
    models = {SMALL: ScriptedModel(SMALL, replies),
              LARGE: ScriptedModel(LARGE, replies)}
    client = build_client(employees_file, prices_file, directory,
                          models=models, orchestration="multi")

    body = client.post("/ask", json={"question": "¿Quién es EMP-0004?"}).json()

    calls = sum(len(model.seen) for model in models.values())
    assert body["steps"] == calls == 2
    assert body["input_tokens"] == 20
