"""Ayudas compartidas por las pruebas multiagente de la sesión 5.

Supuestos de interfaz (el desarrollador debe respetarlos):

- ``Config`` acepta ``orchestration`` (``"single"`` por omisión o
  ``"multi"``) y ``max_answer_chars`` (2000 por omisión).
- ``POST /ask`` agrega ``mode`` y ``agents`` a la respuesta.
- ``GET /metrics`` agrega ``agents`` (``{nombre: {"runs", "errors",
  "cost_usd"}}``) y ``guards`` con al menos ``rejected`` y ``redacted``.
- Cada especialista obtiene su modelo con ``modelo.with_prompt(prompt)``
  (plan, ``app/llm.py``); por eso los modelos de prueba también lo tienen.
"""

import json

from conftest import DEPARTMENTS, LARGE, SMALL, TESTER_KEY
from fastapi.testclient import TestClient

from app.config import Config
from app.llm import Completion, NamedFakeModel
from app.main import create_app

TOOL_PREFIX = "Resultado de la herramienta: "
DENIED_RESULT = TOOL_PREFIX + "la herramienta no está disponible"


class ScriptedModel:
    """Modelo guionizado: devuelve las respuestas de una lista, en orden.

    Cuando se acaba la lista repite la última. Anota cada conversación que
    recibe en ``seen`` para revisar lo que le llegó al modelo.

    :param name: Nombre del modelo que se informa en cada llamada.
    :param replies: Diccionarios que se devuelven serializados como JSON.
    """

    def __init__(self, name, replies):
        self.name = name
        self._replies = list(replies)
        self.seen = []
        self.prompts = []

    def complete(self, messages):
        """Anota los mensajes y devuelve la siguiente respuesta del guion."""
        self.seen.append([dict(message) for message in messages])
        index = min(len(self.seen), len(self._replies)) - 1
        text = json.dumps(self._replies[index], ensure_ascii=False)
        return Completion(
            text=text, model=self.name, input_tokens=10, output_tokens=5,
        )

    def with_prompt(self, prompt):
        """Anota el mensaje de sistema del especialista y devuelve el mismo
        modelo, como ``NamedFakeModel.with_prompt``."""
        self.prompts.append(prompt)
        return self


class SpyDirectory:
    """Directorio espía: delega en el real y anota cada consulta.

    :param directory: Directorio real.
    """

    def __init__(self, directory):
        self._directory = directory
        self.calls = []

    @property
    def departments(self):
        """Departamentos del directorio real."""
        return self._directory.departments

    def get_employee(self, employee_id):
        """Anota y delega la búsqueda por id."""
        self.calls.append(("get_employee", employee_id))
        return self._directory.get_employee(employee_id)

    def search_by_department(self, department):
        """Anota y delega la búsqueda por departamento."""
        self.calls.append(("search_by_department", department))
        return self._directory.search_by_department(department)


def fake_models():
    """Modelos simulados con los nombres pequeño y grande de prueba."""
    return {
        SMALL: NamedFakeModel(SMALL, DEPARTMENTS),
        LARGE: NamedFakeModel(LARGE, DEPARTMENTS),
    }


def make_config(employees_file, prices_file, **overrides):
    """Configuración de prueba con modelos y precios de prueba."""
    values = {
        "model_provider": "fake",
        "agent_max_steps": 3,
        "max_question_chars": 2000,
        "employees_path": str(employees_file),
        "model_small": SMALL,
        "model_large": LARGE,
        "prices_path": str(prices_file),
        "api_keys": {"tester": TESTER_KEY},
    }
    values.update(overrides)
    return Config(**values)


def build_client(employees_file, prices_file, directory, models=None,
                 **overrides):
    """Crea un cliente HTTP con clave válida y errores como respuesta."""
    config = make_config(employees_file, prices_file, **overrides)
    app = create_app(config, models or fake_models(), directory)
    return TestClient(
        app, raise_server_exceptions=False, headers={"X-API-Key": TESTER_KEY},
    )
