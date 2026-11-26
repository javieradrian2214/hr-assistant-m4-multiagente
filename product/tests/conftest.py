"""Fixtures compartidas por las pruebas del HR Assistant.

Supuestos de interfaz (el desarrollador debe respetarlos):

- ``app.config``: ``Config`` (dataclass con ``model_provider``,
  ``agent_max_steps``, ``max_question_chars``, ``employees_path``),
  ``load_config(env: Mapping[str, str]) -> Config`` y ``ConfigError``.
- ``app.directory``: ``Directory(path)``, ``get_employee(id) -> dict | None``,
  ``search_by_department(name) -> list[dict]`` y ``DirectoryError``.
- ``app.llm``: ``FakeModel(departments)`` con ``complete(messages) -> str``,
  ``build_model(provider, directory)``, ``count_input_tokens(messages)`` y
  ``count_output_tokens(text)``.
- ``app.agent``: ``Agent(model, directory, max_steps)`` y ``run(messages)``
  que devuelve un objeto con ``answer``, ``steps``, ``tools_used``,
  ``input_tokens`` y ``output_tokens``.
- ``app.main``: ``create_app(config, model, directory)``.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PRODUCT_DIR = Path(__file__).resolve().parent.parent
if str(PRODUCT_DIR) not in sys.path:
    sys.path.insert(0, str(PRODUCT_DIR))

# pylint: disable=wrong-import-position
from app.config import Config  # noqa: E402
from app.directory import Directory  # noqa: E402
from app.llm import Completion, FakeModel  # noqa: E402
from app.main import create_app  # noqa: E402

EMPLOYEES = [
    {"id": "EMP-0001", "name": "Ana López", "department": "Tecnología",
     "role": "Analista de datos", "start_date": "2019-03-04",
     "status": "activo"},
    {"id": "EMP-0002", "name": "Luis Pérez", "department": "Ventas",
     "role": "Ejecutivo de cuenta", "start_date": "2021-07-19",
     "status": "activo"},
    {"id": "EMP-0003", "name": "Marta Ruiz", "department": "Tecnología",
     "role": "Desarrolladora", "start_date": "2016-11-02",
     "status": "baja"},
    {"id": "EMP-0004", "name": "Jorge Díaz", "department": "Tecnología",
     "role": "Líder técnico", "start_date": "2022-01-10",
     "status": "activo"},
    {"id": "EMP-0005", "name": "Sofía Gómez", "department": "Finanzas",
     "role": "Contadora", "start_date": "2020-05-25", "status": "activo"},
]
DEPARTMENTS = ["Tecnología", "Ventas", "Finanzas"]
TESTER_KEY = "tester-key-0123456789abcdef"


@pytest.fixture(name="employees_file")
def employees_file_fixture(tmp_path):
    """Escribe un employees.json válido en un directorio temporal."""
    path = tmp_path / "employees.json"
    path.write_text(json.dumps(EMPLOYEES, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture(name="directory")
def directory_fixture(employees_file):
    """Directorio real sobre los datos de prueba."""
    return Directory(employees_file)


@pytest.fixture(name="make_client")
def make_client_fixture(employees_file, directory):
    """Fábrica de clientes HTTP con el tope de pasos indicado."""

    def _make(max_steps=3, max_chars=2000):
        config = Config(
            model_provider="fake",
            agent_max_steps=max_steps,
            max_question_chars=max_chars,
            employees_path=str(employees_file),
            api_keys={"tester": TESTER_KEY},
        )
        app = create_app(config, FakeModel(DEPARTMENTS), directory)
        return TestClient(app, headers={"X-API-Key": TESTER_KEY})

    return _make


class FakeClock:
    """Reloj falso: ``now()`` fijo y ``monotonic()`` que avanza solo.

    Cada lectura de ``monotonic()`` suma ``step_seconds``, así la latencia
    medida por la API es predecible sin dormir.
    """

    def __init__(self, step_seconds=0.001):
        self._step = step_seconds
        self._ticks = 0.0

    def now(self):
        """Hora fija en UTC."""
        return datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    def monotonic(self):
        """Segundos monótonos; avanza en cada lectura."""
        self._ticks += self._step
        return self._ticks


@pytest.fixture(name="make_observed_client")
def make_observed_client_fixture(employees_file, directory, capsys):
    """Cliente con reloj falso inyectado y errores 500 como respuesta.

    Depende de ``capsys`` para que la captura ya esté activa cuando la app
    escribe su log, así ``read_log`` lo encuentra después. Se vacía lo
    capturado hasta ahora para que el log empiece limpio.

    Supuestos de la sesión 2: ``Config`` acepta ``service_name``,
    ``slo_p95_ms``, ``langsmith_tracing``, ``hide_inputs`` y ``hide_outputs``
    con valores por omisión, y ``create_app`` acepta ``clock=``.
    """
    capsys.readouterr()

    def _make(model=None, step_ms=1, slo_ms=2000):
        config = Config(
            model_provider="fake",
            agent_max_steps=3,
            max_question_chars=2000,
            employees_path=str(employees_file),
            service_name="hr-test",
            slo_p95_ms=slo_ms,
            api_keys={"tester": TESTER_KEY},
        )
        app = create_app(
            config,
            model or FakeModel(DEPARTMENTS),
            directory,
            clock=FakeClock(step_ms / 1000),
        )
        return TestClient(
            app, raise_server_exceptions=False,
            headers={"X-API-Key": TESTER_KEY},
        )

    return _make


SMALL = "small-model"
LARGE = "large-model"
PRICES = {
    "models": {
        "fake": {"input": 0.0, "output": 0.0},
        SMALL: {"input": 1.0, "output": 2.0},
        LARGE: {"input": 10.0, "output": 20.0},
    }
}


class RecordingModel:
    """Modelo de prueba de la sesión 3: anota lo que recibe.

    Cada llamada informa 1000 tokens de entrada y 500 de salida, así el costo
    es fácil de calcular a mano con los precios de ``PRICES``.

    Supuestos de la sesión 3 (el desarrollador debe respetarlos):

    - ``app.llm.Completion(text, model, input_tokens, output_tokens, cached)``.
    - ``app.gateway.ModelUnavailable`` es la excepción de un modelo caído.
    - ``app.pricing.load_prices(path)`` devuelve un objeto con
      ``cost(model, input_tokens, output_tokens, cached=False)`` y lanza
      ``PricingError`` si el modelo no tiene precio.
    - ``Config`` acepta ``model_small``, ``model_large``, ``routing``,
      ``router_max_chars``, ``history_window``, ``model_max_tokens``,
      ``model_temperature``, ``cache_ttl_seconds``, ``prices_path``,
      ``cf_account_id``, ``cf_gateway_id`` y ``cf_api_token``.
    - ``create_app(config, models, directory)`` recibe un dict
      ``{nombre_del_modelo: modelo}``.
    - ``Agent(model, directory, max_steps, prices=...)`` y su resultado trae
      ``model``, ``cost_usd`` y ``cached_calls``.
    """

    def __init__(self, name, cached=False, error=None):
        self.name = name
        self.cached = cached
        self.error = error
        self.seen = []

    def complete(self, messages):
        """Anota los mensajes y devuelve una respuesta fija."""
        self.seen.append(list(messages))
        if self.error is not None:
            raise self.error
        return Completion(
            text=json.dumps({"answer": "listo"}), model=self.name,
            input_tokens=1000, output_tokens=500, cached=self.cached,
        )

    def with_prompt(self, prompt):
        """Igual que ``NamedFakeModel.with_prompt`` (sesión 5): ignora el
        mensaje de sistema y devuelve el mismo modelo."""
        del prompt  # el modelo de prueba no usa el mensaje de sistema
        return self


@pytest.fixture(name="prices_file")
def prices_file_fixture(tmp_path):
    """Archivo de precios con números redondos."""
    path = tmp_path / "model_prices.json"
    path.write_text(json.dumps(PRICES), encoding="utf-8")
    return path


@pytest.fixture(name="make_costs_client")
def make_costs_client_fixture(employees_file, directory, prices_file):
    """Fábrica de ``(cliente, modelos)`` con modelos que anotan las llamadas."""

    def _make(error=None, cached=False, **overrides):
        config = Config(
            model_provider="fake",
            agent_max_steps=3,
            max_question_chars=2000,
            employees_path=str(employees_file),
            model_small=SMALL,
            model_large=LARGE,
            prices_path=str(prices_file),
            api_keys={"tester": TESTER_KEY},
            **overrides,
        )
        models = {
            SMALL: RecordingModel(SMALL, cached, error),
            LARGE: RecordingModel(LARGE, cached, error),
        }
        app = create_app(config, models, directory)
        client = TestClient(
            app, raise_server_exceptions=False,
            headers={"X-API-Key": TESTER_KEY},
        )
        return client, models

    return _make


ALICE_KEY = "alice-key-0123456789abcdef"
BOB_KEY = "bob-key-fedcba9876543210"


class ManualClock:
    """Reloj de la sesión 4: el tiempo solo avanza cuando la prueba lo pide."""

    def __init__(self):
        self.seconds = 0.0

    def now(self):
        """Hora fija en UTC."""
        return datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    def monotonic(self):
        """Segundos monótonos actuales."""
        return self.seconds

    def advance(self, seconds):
        """Mueve el reloj hacia adelante."""
        self.seconds += seconds


@pytest.fixture(name="clock")
def clock_fixture():
    """Reloj manual compartido por la API y el limitador."""
    return ManualClock()


@pytest.fixture(name="make_secured_client")
def make_secured_client_fixture(employees_file, directory, clock, capsys):
    """Fábrica de clientes HTTP sin clave por omisión, con dos clientes.

    Supuestos de la sesión 4 (el desarrollador debe respetarlos):

    - ``Config`` acepta ``environment`` (por omisión ``"development"``),
      ``api_keys`` (dict ``{cliente: clave}``, fuera de ``repr``) y
      ``rate_limit_per_minute`` (por omisión 30).
    - ``load_config`` lee ``ENVIRONMENT``, ``API_KEYS`` y
      ``RATE_LIMIT_PER_MINUTE``; ``ConfigError`` si ``API_KEYS`` está mal.
    - ``create_app`` usa ``clock.monotonic()`` para el límite y llama a
      ``app.compliance.check_compliance(config)``, que lanza
      ``ComplianceError``.
    """
    capsys.readouterr()

    def _make(rate_limit=30):
        config = Config(
            model_provider="fake",
            agent_max_steps=3,
            max_question_chars=2000,
            employees_path=str(employees_file),
            api_keys={"alice": ALICE_KEY, "bob": BOB_KEY},
            rate_limit_per_minute=rate_limit,
        )
        app = create_app(
            config, FakeModel(DEPARTMENTS), directory, clock=clock
        )
        return TestClient(app, raise_server_exceptions=False)

    return _make


@pytest.fixture(name="read_log")
def read_log_fixture(capsys):
    """Devuelve los eventos de log (dicts) escritos en stdout hasta ahora.

    Falla si alguna línea de stdout no es un JSON válido.
    """

    def _read():
        out = capsys.readouterr().out
        return [json.loads(line) for line in out.splitlines() if line.strip()]

    return _read
