"""Pruebas del reintento de /health y de la clave en scripts/smoke.py.

Complementan test_smoke.py (que cubre las tres comprobaciones y la clave
ausente). Supuesto de interfaz nuevo, tomado del plan: la espera se inyecta
como ``main(argv, env, client=None, sleep=time.sleep)``; ``sleep(segundos)``
se llama entre intentos de /health. Estas pruebas nunca duermen de verdad.
"""

import importlib.util
from pathlib import Path

import httpx

SMOKE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smoke.py"
URL = "https://hr.example.test"
KEY = "smoke-key-0123456789abcdef"
MAX_WAIT_SECONDS = 60


def _load_smoke():
    """Carga ``scripts/smoke.py`` por su ruta (no es un paquete)."""
    spec = importlib.util.spec_from_file_location("smoke", SMOKE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeService:
    """Servicio simulado: /health falla las primeras ``health_failures`` veces."""

    def __init__(self, health_failures=0, health_error=None):
        self.health_failures = health_failures
        self.health_error = health_error
        self.health_calls = 0
        self.requests = []

    def handler(self, request):
        self.requests.append(request)
        if request.url.path == "/health":
            self.health_calls += 1
            if self.health_calls <= self.health_failures:
                if self.health_error is not None:
                    raise self.health_error
                return httpx.Response(503, text="waking up")
            return httpx.Response(200, json={"status": "ok"})
        if request.headers.get("X-API-Key") == KEY:
            return httpx.Response(200, json={"answer": "ok"})
        return httpx.Response(401, json={"detail": "no"})

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def _run(service, env=None, argv=None):
    """Corre main con espera falsa; devuelve (código, esperas registradas)."""
    sleeps = []
    code = _load_smoke().main(
        argv if argv is not None else [URL],
        env if env is not None else {"SMOKE_API_KEY": KEY},
        service.client(),
        sleep=sleeps.append,
    )
    return code, sleeps


def test_health_is_retried_until_the_service_wakes_up(capsys):
    """Un servicio dormido que responde al tercer intento pasa el humo."""
    service = FakeService(health_failures=2)
    code, sleeps = _run(service)
    out = capsys.readouterr().out
    assert code == 0
    assert service.health_calls == 3
    assert len(sleeps) == 2
    assert out.count("[OK]") == 3


def test_health_is_retried_after_connection_errors():
    """Un error de conexión en /health también se reintenta."""
    service = FakeService(
        health_failures=1, health_error=httpx.ConnectError("sleeping")
    )
    code, sleeps = _run(service)
    assert code == 0
    assert service.health_calls == 2
    assert len(sleeps) == 1


def test_healthy_service_is_checked_once_without_waiting():
    """Si /health responde 200 al primer intento no hay espera ni repetición."""
    service = FakeService()
    code, sleeps = _run(service)
    assert code == 0
    assert service.health_calls == 1
    assert not sleeps


def test_health_retries_have_a_cap_and_a_bounded_wait():
    """Con /health caído el número de intentos y cada espera tienen tope."""
    service = FakeService(health_failures=10_000)
    _, sleeps = _run(service)
    assert 2 <= service.health_calls <= 20
    assert len(sleeps) == service.health_calls - 1
    assert all(0 < seconds <= MAX_WAIT_SECONDS for seconds in sleeps)


def test_smoke_prints_fail_and_exits_with_error_when_retries_run_out(capsys):
    """Agotados los reintentos se imprime [FAIL] y el código no es 0."""
    service = FakeService(health_failures=10_000)
    code, _ = _run(service)
    out = capsys.readouterr().out
    assert code != 0
    assert "[FAIL]" in out
    assert "/health" in out


def test_key_is_never_printed_when_checks_fail(capsys):
    """Ni con /health caído ni con un error que contiene la clave se imprime."""
    service = FakeService(
        health_failures=10_000, health_error=httpx.ConnectError(f"boom {KEY}")
    )
    code, _ = _run(service)
    captured = capsys.readouterr()
    assert code != 0
    assert KEY not in captured.out
    assert KEY not in captured.err


def test_key_is_never_printed_when_the_service_is_healthy(capsys):
    """Tampoco en el camino feliz, ni en la salida de error."""
    _run(FakeService())
    captured = capsys.readouterr()
    assert KEY not in captured.out
    assert KEY not in captured.err


def test_key_is_not_accepted_as_an_argument(capsys):
    """Pasar la clave como argumento se rechaza, no se usa y no se imprime."""
    service = FakeService()
    code, _ = _run(service, env={}, argv=[URL, KEY])
    captured = capsys.readouterr()
    assert code != 0
    assert not service.requests
    assert KEY not in captured.out
    assert KEY not in captured.err


def test_key_flag_is_not_accepted_even_with_the_environment_key(capsys):
    """Una opción --api-key tampoco funciona: la clave solo viene del entorno."""
    service = FakeService()
    code, _ = _run(service, argv=[URL, "--api-key", KEY])
    captured = capsys.readouterr()
    assert code != 0
    assert not service.requests
    assert KEY not in captured.out + captured.err
