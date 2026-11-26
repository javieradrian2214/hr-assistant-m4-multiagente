"""Jerarquía de trazas de LangSmith (requisito 9 del plan).

No hay red ni LangSmith real: se reemplaza el módulo ``langsmith`` en
``sys.modules`` por uno falso, en la frontera. El código de la app
(``app.tracing.build_traceable``, ``Agent``, el supervisor) es el que decide
qué funciones se trazan, con qué nombre y quién llama a quién. El
``traceable`` falso solo anota cada ejecución y toma como padre la traza que
estaba abierta en ese momento, igual que el contexto de ``@traceable``.

Supuestos de interfaz:

- ``app.tracing`` sigue haciendo ``from langsmith import Client, traceable``
  y crea un único ``Client(api_key=..., hide_inputs=..., hide_outputs=...)``.
- Los metadatos llegan por ``langsmith_extra={"metadata": {...}}`` al llamar a
  la función trazada o por ``traceable(metadata=...)``; se aceptan los dos.
- Nombres del plan: ``single``: ``agent_run`` > ``model_call`` (llm) y
  ``tool:<nombre>`` (tool). ``multi``: ``supervisor`` (chain) >
  ``agent:<Especialista>`` (chain) > ``model_call`` y ``tool:<nombre>``.
  Metadatos ``request_id``, ``client``, ``mode`` y, bajo el supervisor,
  ``agent``.
"""

import contextvars
import functools
import sys
import types

import pytest
from conftest import LARGE, SMALL
from multiagent_support import ScriptedModel, build_client

REQUEST_ID = "trace-req-0001"
QUESTION = {"question": "¿Quién es EMP-0004?"}


class FakeClient:
    """Cliente falso de LangSmith: guarda sus argumentos y no abre conexiones."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeLangSmith:
    """Módulo ``langsmith`` falso que registra las trazas y su anidación."""

    def __init__(self):
        self.runs = []
        self.clients = []
        self._current = contextvars.ContextVar("fake_run", default=None)

    def module(self):
        """Devuelve el módulo que se instala en ``sys.modules``."""
        module = types.ModuleType("langsmith")
        module.Client = self._make_client
        module.traceable = self._traceable
        return module

    def _make_client(self, **kwargs):
        client = FakeClient(**kwargs)
        self.clients.append(client)
        return client

    def _traceable(self, *args, name=None, run_type="chain", client=None,
                   metadata=None, **_ignored):
        """Imita ``traceable(func)`` y ``traceable(name=..., run_type=...)``."""
        func = args[0] if args and callable(args[0]) else None
        if args and isinstance(args[0], str):
            run_type = args[0]

        def decorate(inner):
            @functools.wraps(inner)
            def traced(*call_args, langsmith_extra=None, **kwargs):
                extra = langsmith_extra or {}
                run = {
                    "id": len(self.runs),
                    "name": name or inner.__name__,
                    "run_type": run_type,
                    "parent": self._current.get(),
                    "metadata": {**(metadata or {}),
                                 **extra.get("metadata", {})},
                    "client": client,
                }
                self.runs.append(run)
                token = self._current.set(run["id"])
                try:
                    return inner(*call_args, **kwargs)
                finally:
                    self._current.reset(token)

            return traced

        return decorate(func) if func is not None else decorate

    def roots(self):
        """Trazas sin padre."""
        return [run for run in self.runs if run["parent"] is None]

    def children(self, run):
        """Hijos directos de una traza, en orden de ejecución."""
        return [(child["name"], child["run_type"]) for child in self.runs
                if child["parent"] == run["id"]]

    def named(self, name):
        """Trazas con el nombre indicado."""
        return [run for run in self.runs if run["name"] == name]


@pytest.fixture(name="fake_langsmith")
def fake_langsmith_fixture(monkeypatch):
    """Instala el ``langsmith`` falso y una clave de prueba en el entorno."""
    fake = FakeLangSmith()
    monkeypatch.setitem(sys.modules, "langsmith", fake.module())
    monkeypatch.setenv("LANGSMITH_API_KEY", "fake-key-for-tests")
    return fake


def _ask(client):
    """Pregunta por EMP-0004 con un id de petición fijo."""
    return client.post("/ask", json=QUESTION,
                       headers={"X-Request-ID": REQUEST_ID})


EMPLOYEE_RUN = [("model_call", "llm"), ("tool:get_employee", "tool"),
                ("model_call", "llm")]


def test_single_mode_traces_model_and_tool_calls_under_agent_run(
        fake_langsmith, employees_file, prices_file, directory):
    client = build_client(employees_file, prices_file, directory,
                          langsmith_tracing=True, orchestration="single")

    assert _ask(client).status_code == 200

    (root,) = fake_langsmith.roots()
    assert (root["name"], root["run_type"]) == ("agent_run", "chain")
    assert fake_langsmith.children(root) == EMPLOYEE_RUN
    (ls_client,) = fake_langsmith.clients
    assert ls_client.kwargs["hide_inputs"] is True
    assert ls_client.kwargs["hide_outputs"] is True
    for run in fake_langsmith.runs:
        assert run["client"] is ls_client
        assert run["metadata"]["request_id"] == REQUEST_ID
        assert run["metadata"]["client"] == "tester"
        assert run["metadata"]["mode"] == "single"


def test_multi_mode_nests_specialist_model_and_tool_runs_under_supervisor(
        fake_langsmith, employees_file, prices_file, directory):
    client = build_client(employees_file, prices_file, directory,
                          langsmith_tracing=True, orchestration="multi")

    assert _ask(client).status_code == 200

    (root,) = fake_langsmith.roots()
    assert (root["name"], root["run_type"]) == ("supervisor", "chain")
    assert fake_langsmith.children(root) == [("agent:EmployeeAgent", "chain")]
    (specialist,) = fake_langsmith.named("agent:EmployeeAgent")
    assert fake_langsmith.children(specialist) == EMPLOYEE_RUN
    for run in fake_langsmith.runs:
        assert run["metadata"]["request_id"] == REQUEST_ID
        assert run["metadata"]["client"] == "tester"
        assert run["metadata"]["mode"] == "multi"
        if run is not root:
            assert run["metadata"]["agent"] == "EmployeeAgent"


def test_denied_tool_opens_no_tool_run(
        fake_langsmith, employees_file, prices_file, directory):
    replies = [
        {"tool": "search_by_department", "args": {"department": "Ventas"}},
        {"answer": "No tengo ese dato."},
    ]
    models = {SMALL: ScriptedModel(SMALL, replies),
              LARGE: ScriptedModel(LARGE, replies)}
    client = build_client(employees_file, prices_file, directory,
                          models=models, langsmith_tracing=True,
                          orchestration="multi")

    assert _ask(client).status_code == 200

    (specialist,) = fake_langsmith.named("agent:EmployeeAgent")
    assert fake_langsmith.children(specialist) == [("model_call", "llm")] * 2
    assert not [run for run in fake_langsmith.runs
                if run["name"].startswith("tool")]
