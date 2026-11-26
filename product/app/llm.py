"""Interfaz del modelo y modelo simulado determinista."""

import json
import re
import unicodedata

import httpx

from app.completion import Completion
from app.gateway import GatewayModel

TOOL_RESULT_PREFIX = "Resultado de la herramienta: "
HELP_ANSWER = "Pregúntame por un empleado (EMP-0001) o un departamento."
# Patrón público de los ids de empleado; el supervisor lo reutiliza.
EMPLOYEE_ID_PATTERN = re.compile(r"EMP-\d{4}")
_EMPLOYEE_ID = EMPLOYEE_ID_PATTERN


def _fold(text: str) -> str:
    """Minúsculas y sin acentos.

    :param text: Texto original.
    :return: Texto normalizado.
    """
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


class FakeModel:
    """Modelo simulado: reglas deterministas sobre el último mensaje.

    :param departments: Departamentos que existen en los datos.
    """

    def __init__(self, departments):
        self._departments = list(departments)

    def complete(self, messages) -> str:
        """Responde con un único objeto JSON.

        :param messages: Conversación como lista de ``{"role", "content"}``.
        :return: JSON con ``tool``/``args`` o con ``answer``.
        """
        last = messages[-1]["content"] if messages else ""
        if last.startswith(TOOL_RESULT_PREFIX):
            result = last[len(TOOL_RESULT_PREFIX):]
            return _dump({"answer": f"Según el directorio: {result}"})
        found = _EMPLOYEE_ID.search(last)
        if found:
            return _dump(
                {"tool": "get_employee", "args": {"employee_id": found.group()}}
            )
        folded = _fold(last)
        for department in self._departments:
            if _fold(department) in folded:
                return _dump(
                    {"tool": "search_by_department",
                     "args": {"department": department}}
                )
        return _dump({"answer": HELP_ANSWER})


def _dump(payload: dict) -> str:
    """Serializa a JSON conservando los acentos.

    :param payload: Objeto a serializar.
    :return: Texto JSON.
    """
    return json.dumps(payload, ensure_ascii=False)


def count_input_tokens(messages) -> int:
    """Cuenta de forma aproximada las palabras de todos los mensajes.

    :param messages: Lista de mensajes.
    :return: Número de palabras.
    """
    return sum(len(m["content"].split()) for m in messages)


def count_output_tokens(text: str) -> int:
    """Cuenta de forma aproximada las palabras de una respuesta.

    :param text: Texto de salida.
    :return: Número de palabras.
    """
    return len(text.split())


class NamedFakeModel:
    """Modelo simulado con nombre, para cobrarlo con el precio de su nombre.

    :param name: Nombre del modelo que se informa en cada llamada.
    :param departments: Departamentos que existen en los datos.
    """

    def __init__(self, name, departments):
        self._name = name
        self._model = FakeModel(departments)

    def complete(self, messages) -> Completion:
        """Responde como ``FakeModel`` y cuenta palabras como tokens.

        :param messages: Conversación como lista de ``{"role", "content"}``.
        :return: Resultado con el nombre de este modelo.
        """
        text = self._model.complete(messages)
        return Completion(
            text=text, model=self._name,
            input_tokens=count_input_tokens(messages),
            output_tokens=count_output_tokens(text),
        )

    def with_prompt(self, prompt):  # pylint: disable=unused-argument
        """Devuelve este mismo modelo: el simulado ignora el mensaje de sistema.

        :param prompt: Mensaje de sistema del especialista (no se usa).
        :return: Este mismo objeto.
        """
        return self


SYSTEM_PROMPT = (
    "Eres el HR Assistant: respondes preguntas sobre el directorio de "
    "empleados. Responde SIEMPRE con un unico objeto JSON, sin texto "
    "adicional ni bloques de codigo.\n"
    "Para usar una herramienta responde: "
    '{"tool": "<nombre>", "args": {...}}\n'
    "Herramientas:\n"
    '- get_employee(employee_id): datos de un empleado, p. ej. '
    '{"tool": "get_employee", "args": {"employee_id": "EMP-0005"}}\n'
    "- search_by_department(department): empleados de un departamento, "
    'p. ej. {"tool": "search_by_department", "args": '
    '{"department": "Finanzas"}}\n'
    f'El resultado llega en un mensaje que empieza con "{TOOL_RESULT_PREFIX}". '
    "Con ese resultado responde al usuario, en espanol y de forma breve, con: "
    '{"answer": "<texto>"}\n'
    "Si no necesitas una herramienta, responde directamente con "
    '{"answer": "<texto>"}. No inventes datos: usa solo el resultado de '
    "las herramientas."
)


class SystemPromptModel:
    """Envuelve un modelo real y antepone el mensaje de sistema.

    :param model: Modelo con ``complete(messages)``.
    :param prompt: Mensaje de sistema con el protocolo y las herramientas.
    """

    def __init__(self, model, prompt=SYSTEM_PROMPT):
        self._model = model
        self._prompt = prompt

    def complete(self, messages):
        """Llama al modelo con el mensaje de sistema al inicio.

        :param messages: Conversación como lista de ``{"role", "content"}``.
        :return: Lo que devuelva el modelo envuelto.
        """
        system = {"role": "system", "content": self._prompt}
        return self._model.complete([system, *messages])

    def with_prompt(self, prompt):
        """Crea otro envoltorio del mismo modelo con un mensaje de sistema nuevo.

        El envoltorio original no cambia.

        :param prompt: Mensaje de sistema del especialista.
        :return: Un ``SystemPromptModel`` nuevo sobre el mismo modelo.
        """
        return SystemPromptModel(self._model, prompt)


def build_model(provider: str, directory):
    """Fábrica del modelo simulado según el proveedor.

    :param provider: Valor de ``MODEL_PROVIDER``.
    :param directory: Directorio, para conocer los departamentos.
    :return: Objeto con ``complete(messages)``.
    :raises ValueError: Si el proveedor no existe.
    """
    if provider == "fake":
        return FakeModel(directory.departments)
    raise ValueError(f"Unknown model provider: {provider}")


def build_models(config, directory, http_client=None):
    """Crea los dos modelos (pequeño y capaz) según el proveedor.

    :param config: Configuración validada.
    :param directory: Directorio, para conocer los departamentos.
    :param http_client: Cliente ``httpx.Client`` para ``gateway``; si falta,
        se crea uno.
    :return: Diccionario ``{nombre_del_modelo: modelo}``.
    :raises ValueError: Si el proveedor no existe.
    """
    names = {config.model_small, config.model_large}
    if config.model_provider == "fake":
        return {
            name: NamedFakeModel(name, directory.departments) for name in names
        }
    if config.model_provider == "gateway":
        client = http_client or httpx.Client(timeout=config.model_timeout_seconds)
        return {
            name: SystemPromptModel(GatewayModel(name, config, client))
            for name in names
        }
    raise ValueError(f"Unknown model provider: {config.model_provider}")
