"""Especialistas del modo multi con mínimo privilegio (ADR 0014).

Cada especialista es un ``Agent`` con su propio mensaje de sistema y solo sus
herramientas. No agrega herramientas ni permisos: la lista de
``allowed_tools`` es la única fuente de privilegios.
"""

from dataclasses import dataclass
from typing import Tuple

from app.agent import Agent
from app.llm import TOOL_RESULT_PREFIX
from app.router import choose_model

# Políticas de modelo.
ROUTER_POLICY = "router"
LARGE_ON_ANALYSIS_RULE_POLICY = "large_on_analysis_rule"
ANALYST_ROUTE = "analyst uses MODEL_LARGE"

_TOOL_LINES = {
    "get_employee": (
        "- get_employee(employee_id): datos de un empleado, p. ej. "
        '{"tool": "get_employee", "args": {"employee_id": "EMP-0005"}}'
    ),
    "search_by_department": (
        "- search_by_department(department): empleados de un departamento, "
        'p. ej. {"tool": "search_by_department", "args": '
        '{"department": "Finanzas"}}'
    ),
}


def _prompt(role: str, tools: Tuple[str, ...]) -> str:
    """Arma el mensaje de sistema de un especialista.

    Solo menciona las herramientas del especialista.

    :param role: Descripción de la tarea del especialista.
    :param tools: Herramientas permitidas.
    :return: Mensaje de sistema.
    """
    tool_lines = "\n".join(_TOOL_LINES[name] for name in tools)
    return (
        f"Eres un especialista del HR Assistant: {role} "
        "Responde SIEMPRE con un unico objeto JSON, sin texto adicional ni "
        "bloques de codigo.\n"
        "Para usar una herramienta responde: "
        '{"tool": "<nombre>", "args": {...}}\n'
        f"Herramientas:\n{tool_lines}\n"
        f'El resultado llega en un mensaje que empieza con "{TOOL_RESULT_PREFIX}". '
        "Con ese resultado responde al usuario, en espanol y de forma breve, "
        'con: {"answer": "<texto>"}\n'
        "Si la herramienta no esta disponible o no necesitas una, responde "
        'directamente con {"answer": "<texto>"}. No inventes datos: usa solo '
        "el resultado de las herramientas."
    )


@dataclass(frozen=True)
class SpecialistSpec:
    """Especificación de un especialista.

    :param name: Nombre del especialista.
    :param prompt: Mensaje de sistema propio.
    :param tools: Herramientas permitidas (``allowed_tools`` de ``Agent``).
    :param model_policy: ``router`` o ``large_on_analysis_rule``.
    """

    name: str
    prompt: str
    tools: Tuple[str, ...]
    model_policy: str


def _spec(name: str, role: str, tools: Tuple[str, ...],
          policy: str) -> SpecialistSpec:
    """Crea una especificación con su mensaje de sistema.

    :param name: Nombre del especialista.
    :param role: Descripción de la tarea.
    :param tools: Herramientas permitidas.
    :param policy: Política de modelo.
    :return: ``SpecialistSpec``.
    """
    return SpecialistSpec(name, _prompt(role, tools), tools, policy)


SPECIALISTS = {
    spec.name: spec for spec in (
        _spec(
            "EmployeeAgent",
            "respondes preguntas sobre un empleado concreto, identificado por "
            "su id EMP-NNNN.",
            ("get_employee",), ROUTER_POLICY,
        ),
        _spec(
            "DepartmentAgent",
            "respondes preguntas sobre las personas de un departamento.",
            ("search_by_department",), ROUTER_POLICY,
        ),
        _spec(
            "AnalystAgent",
            "comparas, resumes y analizas datos de varios empleados o "
            "departamentos, y atiendes las preguntas generales.",
            ("get_employee", "search_by_department"),
            LARGE_ON_ANALYSIS_RULE_POLICY,
        ),
    )
}


def resolve_model(spec: SpecialistSpec, question: str, config,
                  analysis_rule: bool) -> Tuple[str, str]:
    """Elige el modelo de un especialista según su política.

    :param spec: Especificación del especialista.
    :param question: Pregunta de la persona.
    :param config: Configuración con los modelos y el enrutador.
    :param analysis_rule: Si lo eligió una regla explícita de análisis.
    :return: Tupla ``(modelo, motivo)``.
    """
    if spec.model_policy == LARGE_ON_ANALYSIS_RULE_POLICY and analysis_rule:
        return config.model_large, ANALYST_ROUTE
    return choose_model(question, config)


def build_specialist(spec: SpecialistSpec, model, directory, max_steps: int,
                     **options) -> Agent:
    """Crea un ``Agent`` nuevo configurado como el especialista.

    El modelo recibe el mensaje de sistema con ``model.with_prompt``.

    :param spec: Especificación del especialista.
    :param model: Modelo elegido, con ``complete`` y ``with_prompt``.
    :param directory: Directorio de empleados.
    :param max_steps: Tope de vueltas (``AGENT_MAX_STEPS``).
    :param options: ``audit``, ``on_denied``, ``traceable``, ``prices`` y
        ``model_name``, que se pasan tal cual a ``Agent``.
    :return: ``Agent`` con solo las herramientas del especialista.
    """
    return Agent(
        model.with_prompt(spec.prompt), directory, max_steps,
        allowed_tools=spec.tools, agent_name=spec.name, **options,
    )
