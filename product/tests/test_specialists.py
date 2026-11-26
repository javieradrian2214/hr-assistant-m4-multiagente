"""Especificaciones de los especialistas (app.specialists, requisito 3).

Supuestos de interfaz (plan, ``app/specialists.py``):

- ``SPECIALISTS`` es un diccionario ``{nombre: SpecialistSpec}`` con los tres
  especialistas; cada ``SpecialistSpec`` tiene ``name``, ``prompt``, ``tools``
  y ``model_policy``.
- ``model_policy`` es igual en ``EmployeeAgent`` y ``DepartmentAgent`` (modelo
  del enrutador) y distinta en ``AnalystAgent`` (``MODEL_LARGE`` solo por una
  regla de análisis). No se fija el valor concreto.
- Cada especialista recibe su modelo con ``modelo.with_prompt(spec.prompt)``.
- Una herramienta que no existe se deniega igual que una ajena.

``app.specialists`` se importa dentro de cada prueba: si todavía no existe,
fallan estas pruebas y no la recolección del resto de la suite.

Tamaño de la fase: el total de pruebas nuevas de esta fase de qa-unit quedó en
26 casos parametrizados, uno por encima del tope original de 25. La persona
autorizó expresamente ese exceso.
"""

import pytest
from conftest import LARGE, SMALL
from multiagent_support import DENIED_RESULT, ScriptedModel, SpyDirectory, build_client

ALL_TOOLS = {"get_employee", "search_by_department"}
EXPECTED_TOOLS = {
    "EmployeeAgent": {"get_employee"},
    "DepartmentAgent": {"search_by_department"},
    "AnalystAgent": {"get_employee", "search_by_department"},
}
UNKNOWN_TOOL = {"tool": "delete_employee", "args": {"employee_id": "EMP-0004"}}
FINAL_ANSWER = {"answer": "listo"}


def specialists():
    """Devuelve ``SPECIALISTS`` importado en el momento de la prueba."""
    from app.specialists import SPECIALISTS  # pylint: disable=import-outside-toplevel

    return SPECIALISTS


def scripted_models(replies):
    """Dos modelos guionizados (pequeño y grande) con las mismas respuestas."""
    return {SMALL: ScriptedModel(SMALL, replies),
            LARGE: ScriptedModel(LARGE, replies)}


@pytest.fixture
def client_inputs(employees_file, prices_file, directory):
    """Agrupa, en orden, los tres primeros argumentos de ``build_client``."""
    return employees_file, prices_file, directory


def test_there_are_exactly_three_specialists_registered_by_name():
    registry = specialists()

    assert set(registry) == set(EXPECTED_TOOLS)
    for name, spec in registry.items():
        assert spec.name == name


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_each_specialist_prompt_only_mentions_its_own_tools(name):
    spec = specialists()[name]

    assert set(spec.tools) == EXPECTED_TOOLS[name]
    for tool in EXPECTED_TOOLS[name]:
        assert tool in spec.prompt
    for tool in ALL_TOOLS - EXPECTED_TOOLS[name]:
        assert tool not in spec.prompt


def test_only_the_analyst_has_its_own_model_policy():
    registry = specialists()

    employee = registry["EmployeeAgent"].model_policy
    department = registry["DepartmentAgent"].model_policy

    assert employee == department
    assert registry["AnalystAgent"].model_policy != employee


def test_every_specialist_has_a_different_prompt_from_the_single_agent():
    from app.llm import SYSTEM_PROMPT  # pylint: disable=import-outside-toplevel

    prompts = [spec.prompt for spec in specialists().values()]

    assert len(set(prompts)) == len(prompts)
    assert SYSTEM_PROMPT not in prompts


@pytest.mark.parametrize("question, agent, model_name", [
    ("¿Quién es EMP-0004?", "EmployeeAgent", SMALL),
    ("¿Quién trabaja en Finanzas?", "DepartmentAgent", SMALL),
    ("Compara EMP-0001 y EMP-0002", "AnalystAgent", LARGE),
    ("Hello there", "AnalystAgent", SMALL),
])
def test_multi_mode_runs_the_specialist_with_its_prompt_and_model(
        client_inputs, question, agent, model_name):
    models = scripted_models([FINAL_ANSWER])
    client = build_client(*client_inputs, models=models, orchestration="multi")

    body = client.post("/ask", json={"question": question}).json()

    other = LARGE if model_name == SMALL else SMALL
    assert body["agents"] == [agent]
    assert len(models[model_name].seen) == 1
    assert not models[other].seen
    assert specialists()[agent].prompt in models[model_name].prompts


def test_department_specialist_cannot_look_up_an_employee(
        employees_file, prices_file, directory):
    spy = SpyDirectory(directory)
    ask_employee = {"tool": "get_employee", "args": {"employee_id": "EMP-0005"}}
    models = scripted_models([ask_employee, FINAL_ANSWER])
    client = build_client(employees_file, prices_file, spy,
                          models=models, orchestration="multi")

    response = client.post("/ask", json={"question": "¿Quién trabaja en Finanzas?"})

    body = response.json()
    assert response.status_code == 200
    assert body["agents"] == ["DepartmentAgent"]
    assert body["tools_used"] == []
    assert not spy.calls
    assert models[SMALL].seen[1][-1]["content"] == DENIED_RESULT


@pytest.mark.parametrize("question", [
    "¿Quién es EMP-0004?",
    "¿Quién trabaja en Finanzas?",
    "Hello there",
])
def test_unknown_tool_is_denied_for_every_specialist(
        employees_file, prices_file, directory, question):
    spy = SpyDirectory(directory)
    models = scripted_models([UNKNOWN_TOOL, FINAL_ANSWER])
    client = build_client(employees_file, prices_file, spy,
                          models=models, orchestration="multi")

    body = client.post("/ask", json={"question": question}).json()

    assert body["tools_used"] == []
    assert body["steps"] == 2
    assert not spy.calls
    sent_back = models[SMALL].seen[1][-1]["content"]
    assert sent_back == DENIED_RESULT
    assert "delete_employee" not in sent_back
