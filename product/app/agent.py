"""Agente con bucle acotado que usa herramientas de solo lectura."""

import json
from dataclasses import dataclass, field

from app.llm import (
    TOOL_RESULT_PREFIX, Completion, count_input_tokens, count_output_tokens,
)

CAP_MESSAGE = (
    "No pude completar la respuesta. Intenta con una pregunta más concreta."
)
# Resultado fijo tras una herramienta denegada: sin nombres de herramientas,
# sin la lista de permitidas y sin el nombre del especialista (ADR 0014).
TOOL_DENIED_MESSAGE = "la herramienta no está disponible"


def _parse_payload(text):
    """Extrae el objeto JSON de la respuesta, aunque venga envuelto en texto.

    :param text: Texto del modelo (puro, en bloque ```json o con texto alrededor).
    :return: Diccionario, o ``None`` si no hay un objeto JSON válido.
    """
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            payload, _ = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
            continue
        if isinstance(payload, dict):
            return payload
        start = text.find("{", start + 1)
    return None


@dataclass
class AgentResult:  # pylint: disable=too-many-instance-attributes
    """Resultado de una ejecución del agente.

    :param answer: Texto final.
    :param steps: Vueltas usadas.
    :param tools_used: Herramientas ejecutadas, en orden.
    :param input_tokens: Tokens de entrada aproximados.
    :param output_tokens: Tokens de salida aproximados.
    :param gateway_log_ids: Ids de AI Gateway de las llamadas, sin vacíos.
    """

    answer: str
    steps: int
    tools_used: list = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    stopped: bool = False
    model: str = ""
    cost_usd: float = 0.0
    cached_calls: int = 0
    gateway_log_ids: list = field(default_factory=list)


class _Usage:
    """Acumula tokens, costo, llamadas en caché e ids de gateway.

    :param prices: Precios (``cost(model, in, out, cached)``) o ``None``.
    :param model: Nombre del modelo por defecto.
    """

    def __init__(self, prices, model: str):
        self._prices = prices
        self.model = model
        self.input_tokens = 0
        self.output_tokens = 0
        self.cached_calls = 0
        self.cost = 0.0
        self.log_ids: list = []

    def add(self, completion: Completion) -> None:
        """Suma el consumo de una llamada al modelo.

        :param completion: Respuesta del modelo.
        """
        self.model = completion.model or self.model
        self.input_tokens += completion.input_tokens
        self.output_tokens += completion.output_tokens
        self.cached_calls += 1 if completion.cached else 0
        if completion.gateway_log_id:
            self.log_ids.append(completion.gateway_log_id)
        if self._prices is not None:
            self.cost += self._prices.cost(
                completion.model, completion.input_tokens,
                completion.output_tokens, completion.cached,
            )


class _Tools:
    """Herramientas de solo lectura, en un diccionario ``{nombre: función}``.

    :param directory: Directorio de empleados.
    """

    def __init__(self, directory):
        self._directory = directory
        self._by_name = {
            "get_employee": self._get_employee,
            "search_by_department": self._search_by_department,
        }

    def _get_employee(self, args):
        """Busca un empleado por id.

        :param args: Argumentos con ``employee_id``.
        :return: Texto del resultado.
        """
        employee_id = args["employee_id"]
        employee = self._directory.get_employee(employee_id)
        if employee is None:
            return f"El empleado {employee_id} no existe."
        return json.dumps(employee, ensure_ascii=False)

    def _search_by_department(self, args):
        """Lista los empleados de un departamento.

        :param args: Argumentos con ``department``.
        :return: Texto del resultado.
        """
        department = args["department"]
        found = self._directory.search_by_department(department)
        if not found:
            return f"No hay empleados en el departamento {department}."
        return json.dumps(found, ensure_ascii=False)

    @property
    def names(self):
        """Nombres de todas las herramientas, en orden.

        :return: Tupla de nombres.
        """
        return tuple(self._by_name)

    def runner(self, name):
        """Devuelve una función que ejecuta la herramienta indicada.

        La función devuelve ``None`` si los argumentos no son válidos.

        :param name: Nombre de una herramienta existente.
        :return: Función ``run(args)``.
        """
        tool = self._by_name[name]

        def run(args):
            try:
                return tool(args)
            except (KeyError, TypeError):
                return None

        return run


class Agent:  # pylint: disable=too-many-instance-attributes
    """Agente de un solo modelo con herramientas de solo lectura.

    :param model: Objeto con ``complete(messages)``.
    :param directory: Directorio de empleados.
    :param max_steps: Tope de vueltas.
    :param audit: Función ``audit(tool, args)`` llamada por cada herramienta.
    :param traceable: Fábrica ``traceable(name, run_type)(func)`` para las
        trazas; cada herramienta se traza como ``tool:<nombre>``.
    :param prices: Precios (``cost(model, in, out, cached)``); sin ellos el
        costo es 0.
    :param model_name: Nombre del modelo, para respuestas que son solo texto.
    :param allowed_tools: Herramientas que puede ejecutar; por omisión
        todas (modo single). Los nombres que no existen se ignoran.
    :param on_denied: Función ``on_denied(tool)`` llamada con el nombre
        pedido cada vez que se deniega una herramienta (solo para el log).
    :param agent_name: Nombre del agente o especialista.
    """

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
            self, model, directory, max_steps: int, audit=None,
            traceable=None, prices=None, model_name: str = "",
            allowed_tools=None, on_denied=None, agent_name: str = "Agent"):
        self._prices = prices
        self._model_name = model_name
        self._max_steps = max_steps
        self._audit = audit
        self._on_denied = on_denied
        self.agent_name = agent_name
        self._complete = model.complete
        if traceable is not None:
            self._complete = traceable("model_call", "llm")(model.complete)
        tools = _Tools(directory)
        allowed = tools.names if allowed_tools is None else tuple(allowed_tools)
        self._runners = {}
        for name in tools.names:
            if name not in allowed:
                continue
            runner = tools.runner(name)
            if traceable is not None:
                runner = traceable(f"tool:{name}", "tool")(runner)
            self._runners[name] = runner

    def run(self, messages) -> AgentResult:
        """Ejecuta el bucle hasta responder o llegar al tope.

        :param messages: Conversación inicial.
        :return: Respuesta, pasos, herramientas y tokens.
        """
        conversation = list(messages)
        tools_used = []
        usage = _Usage(self._prices, self._model_name)

        def summary(answer, step, **extra):
            return AgentResult(
                answer, step, tools_used, usage.input_tokens,
                usage.output_tokens, model=usage.model, cost_usd=usage.cost,
                cached_calls=usage.cached_calls,
                gateway_log_ids=usage.log_ids, **extra,
            )

        for step in range(1, self._max_steps + 1):
            completion = self._normalize(self._complete(conversation),
                                         conversation)
            usage.add(completion)
            payload = _parse_payload(completion.text)
            if payload is None:
                continue
            if "answer" in payload:
                return summary(str(payload["answer"]), step)
            name = payload.get("tool")
            if name is None:
                continue
            runner = self._runners.get(name) if isinstance(name, str) else None
            if runner is None:
                self._deny(name, completion.text, conversation)
                continue
            args = payload.get("args")
            result = runner(args if isinstance(args, dict) else {})
            if result is not None:
                tools_used.append(name)
                if self._audit is not None:
                    self._audit(name, args)
                conversation.append(
                    {"role": "user", "content": TOOL_RESULT_PREFIX + result}
                )
        return summary(CAP_MESSAGE, self._max_steps, stopped=True)

    def _deny(self, name, reply_text, conversation) -> None:
        """Deniega una herramienta desconocida o fuera de ``allowed_tools``.

        No la ejecuta; avisa a ``on_denied`` y agrega a la conversación
        interna la respuesta del modelo y el resultado fijo, que no revela
        la herramienta pedida, las permitidas ni el nombre del agente.

        :param name: Nombre pedido por el modelo.
        :param reply_text: Texto de la respuesta del modelo.
        :param conversation: Conversación interna, se modifica en el lugar.
        """
        if self._on_denied is not None:
            self._on_denied(name if isinstance(name, str) else str(name))
        conversation.append({"role": "assistant", "content": reply_text})
        conversation.append(
            {"role": "user", "content": TOOL_RESULT_PREFIX + TOOL_DENIED_MESSAGE}
        )

    def _normalize(self, reply, conversation) -> Completion:
        """Convierte una respuesta de solo texto en ``Completion``.

        :param reply: ``Completion`` o texto.
        :param conversation: Conversación enviada, para contar palabras.
        :return: Un ``Completion``.
        """
        if isinstance(reply, Completion):
            return reply
        return Completion(
            text=reply, model=self._model_name,
            input_tokens=count_input_tokens(conversation),
            output_tokens=count_output_tokens(reply),
        )
