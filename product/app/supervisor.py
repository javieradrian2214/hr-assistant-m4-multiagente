"""Supervisor determinístico del modo multi (ADR 0013).

Elige un especialista por pregunta con reglas en código, sin llamar a ningún
modelo (0 tokens), lo ejecuta y devuelve su resultado. No guarda estado entre
peticiones: cada ``run`` crea su propio ``Agent``.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional

from app.agent import AgentResult
from app.llm import EMPLOYEE_ID_PATTERN
from app.router import find_keyword
from app.specialists import SPECIALISTS, build_specialist, resolve_model

EMPLOYEE_AGENT = "EmployeeAgent"
DEPARTMENT_AGENT = "DepartmentAgent"
ANALYST_AGENT = "AnalystAgent"
UNKNOWN_TOOL = "unknown"


@dataclass(frozen=True)
class Decision:
    """Decisión del supervisor.

    :param agent: Especialista elegido.
    :param reason: Motivo, sin valores de la pregunta salvo la palabra clave o
        el nombre del departamento.
    :param model: Modelo que usará el especialista.
    :param route: Motivo del modelo (el del enrutador o
        ``analyst uses MODEL_LARGE``).
    """

    agent: str
    reason: str
    model: str
    route: str


@dataclass
class OrchestrationResult:
    """Resultado del modo multi.

    :param result: ``AgentResult`` sumado de los agentes que corrieron.
    :param agents: Nombres de los agentes que corrieron, en orden.
    :param decision: Decisión del supervisor.
    """

    result: AgentResult
    agents: List[str] = field(default_factory=list)
    decision: Optional[Decision] = None


def _fold(text: str) -> str:
    """Minúsculas y sin acentos.

    :param text: Texto original.
    :return: Texto normalizado.
    """
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _found_departments(question: str, departments) -> list:
    """Departamentos de los datos que aparecen en la pregunta.

    Compara sin mayúsculas ni acentos y por palabra completa.

    :param question: Pregunta de la persona.
    :param departments: Departamentos que existen en los datos.
    :return: Nombres tal como están en los datos, sin repetir y en orden.
    """
    folded = _fold(question)
    found = []
    for department in departments:
        pattern = r"\b" + re.escape(_fold(department)) + r"\b"
        if department not in found and re.search(pattern, folded):
            found.append(department)
    return found


def _choose_agent(question: str, departments):
    """Aplica las seis reglas en orden.

    :param question: Pregunta de la persona.
    :param departments: Departamentos que existen en los datos.
    :return: Tupla ``(agente, motivo, regla_de_analisis)``.
    """
    keyword = find_keyword(question)
    if keyword is not None:
        return ANALYST_AGENT, f"analysis keyword '{keyword}'", True
    ids = set(EMPLOYEE_ID_PATTERN.findall(question))
    if len(ids) > 1:
        return ANALYST_AGENT, "multiple employee ids", True
    found = _found_departments(question, departments)
    if len(found) > 1:
        return ANALYST_AGENT, "multiple departments", True
    if ids:
        return EMPLOYEE_AGENT, "one employee id", False
    if found:
        return DEPARTMENT_AGENT, f"department '{found[0]}'", False
    return ANALYST_AGENT, "no rule matched", False


def decide(question: str, departments, config) -> Decision:
    """Elige el especialista y su modelo sin llamar a ningún modelo.

    Reglas, en orden: 1) palabra de análisis, 2) más de un id, 3) más de un
    departamento -> ``AnalystAgent`` con ``MODEL_LARGE``; 4) un id ->
    ``EmployeeAgent``; 5) un departamento -> ``DepartmentAgent``; 6) ninguna
    -> ``AnalystAgent`` con el modelo del enrutador.

    :param question: Pregunta de la persona (no el historial).
    :param departments: Departamentos que existen en los datos.
    :param config: Configuración con los modelos y el enrutador.
    :return: ``Decision``.
    """
    agent, reason, analysis_rule = _choose_agent(question, departments)
    model, route = resolve_model(SPECIALISTS[agent], question, config,
                                 analysis_rule)
    return Decision(agent, reason, model, route)


def combine_results(results) -> AgentResult:
    """Suma los resultados de los agentes que corrieron, en orden.

    Suma pasos, tokens, costo y llamadas en caché; concatena herramientas e
    ids de gateway. La respuesta, el modelo y ``stopped`` son los del último.

    :param results: Lista no vacía de ``AgentResult``.
    :return: ``AgentResult`` combinado.
    """
    last = results[-1]
    return AgentResult(
        answer=last.answer,
        steps=sum(r.steps for r in results),
        tools_used=[tool for r in results for tool in r.tools_used],
        input_tokens=sum(r.input_tokens for r in results),
        output_tokens=sum(r.output_tokens for r in results),
        stopped=last.stopped,
        model=last.model,
        cost_usd=sum(r.cost_usd for r in results),
        cached_calls=sum(r.cached_calls for r in results),
        gateway_log_ids=[i for r in results for i in r.gateway_log_ids],
    )


def _no_trace(name, run_type="chain"):  # pylint: disable=unused-argument
    """Fábrica de trazas vacía: devuelve la función tal cual.

    :param name: Nombre de la traza (no se usa).
    :param run_type: Tipo de la traza (no se usa).
    :return: Decorador identidad.
    """
    return lambda func: func


class Supervisor:  # pylint: disable=too-many-instance-attributes
    """Decide, ejecuta un especialista y devuelve el resultado.

    Solo guarda dependencias de solo lectura; cada ``run`` crea su propio
    especialista, así dos peticiones nunca comparten un agente.

    :param config: Configuración validada.
    :param models: Diccionario ``{nombre: modelo}``.
    :param directory: Directorio de empleados (con ``departments``).
    :param events: Emisor con ``emit(evento, **campos)`` o ``None``; recibe
        ``supervisor_decision`` y ``tool_denied``.
    :param audit: Función ``audit(tool, args, agent)`` por cada herramienta
        ejecutada, o ``None``.
    :param traceable: Fábrica ``traceable(name, run_type)(func)``.
    :param prices: Precios para el costo, o ``None``.
    :param metrics: ``Metrics`` con ``record_agent``, o ``None``.
    """

    def __init__(  # pylint: disable=too-many-arguments
            self, config, models: dict, directory, *, events=None,
            audit=None, traceable=None, prices=None, metrics=None):
        self._config = config
        self._models = models
        self._directory = directory
        self._events = events
        self._audit = audit
        self._traceable = traceable or _no_trace
        self._prices = prices
        self._metrics = metrics

    def run(self, messages, question: str) -> OrchestrationResult:
        """Corre una pregunta dentro de la traza raíz ``supervisor``.

        :param messages: Conversación ya recortada (historial y pregunta).
        :param question: Pregunta de la persona, para decidir.
        :return: ``OrchestrationResult``.
        :raises ModelUnavailable: Si el modelo falla (se cuenta el error del
            especialista y se relanza).
        """
        traced = self._traceable("supervisor", "chain")(self._orchestrate)
        return traced(list(messages), question)

    def _orchestrate(self, messages, question: str) -> OrchestrationResult:
        """Decide, registra el motivo y ejecuta el especialista.

        :param messages: Conversación ya recortada.
        :param question: Pregunta de la persona.
        :return: ``OrchestrationResult``.
        """
        decision = decide(question, self._directory.departments, self._config)
        self._emit("supervisor_decision", agent=decision.agent,
                   reason=decision.reason)
        result = self._run_specialist(decision, messages)
        return OrchestrationResult(combine_results([result]), [decision.agent],
                                   decision)

    def _run_specialist(self, decision: Decision, messages) -> AgentResult:
        """Crea y ejecuta el especialista dentro de ``agent:<nombre>``.

        :param decision: Decisión del supervisor.
        :param messages: Conversación ya recortada.
        :return: ``AgentResult`` del especialista.
        """
        spec = SPECIALISTS[decision.agent]
        agent = build_specialist(
            spec, self._models[decision.model], self._directory,
            self._config.agent_max_steps, audit=self._audit_for(spec.name),
            on_denied=self._denied_for(spec.name), traceable=self._traceable,
            prices=self._prices, model_name=decision.model,
        )
        traced = self._traceable(f"agent:{spec.name}", "chain")(agent.run)
        try:
            result = traced(messages)
        except Exception:
            self._record(spec.name, True, 0.0)
            raise
        self._record(spec.name, False, result.cost_usd)
        return result

    def _audit_for(self, agent_name: str):
        """Crea la función de auditoría del especialista.

        :param agent_name: Nombre del especialista.
        :return: Función ``audit(tool, args)`` o ``None``.
        """
        if self._audit is None:
            return None
        return lambda tool, args: self._audit(tool, args, agent_name)

    def _denied_for(self, agent_name: str):
        """Crea la función ``on_denied`` del especialista.

        Registra ``tool_denied`` con el agente y la herramienta. Un nombre
        que no es una herramienta conocida se registra como ``unknown``, para
        no copiar al log texto arbitrario del modelo.

        :param agent_name: Nombre del especialista.
        :return: Función ``on_denied(tool)``.
        """
        known = {tool for spec in SPECIALISTS.values() for tool in spec.tools}

        def on_denied(tool: str) -> None:
            self._emit("tool_denied", agent=agent_name,
                       tool=tool if tool in known else UNKNOWN_TOOL)

        return on_denied

    def _emit(self, event: str, **fields) -> None:
        """Emite un evento si hay emisor.

        :param event: Nombre del evento.
        :param fields: Campos del evento.
        """
        if self._events is not None:
            self._events.emit(event, **fields)

    def _record(self, agent_name: str, error: bool, cost: float) -> None:
        """Registra la ejecución en las métricas si las hay.

        :param agent_name: Nombre del especialista.
        :param error: Si terminó con error.
        :param cost: Costo en USD.
        """
        if self._metrics is not None:
            self._metrics.record_agent(agent_name, error, cost)
