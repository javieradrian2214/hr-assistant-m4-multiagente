"""Pruebas de la prueba de humo (scripts/smoke.py).

Supuesto de interfaz: ``main(argv, env, client=None) -> int``. ``argv`` trae
la URL; ``env`` trae ``SMOKE_API_KEY``; ``client`` es un ``httpx.Client``
(por omisión crea uno). Devuelve 0 si las tres comprobaciones pasan.
"""

import importlib.util
from pathlib import Path

import httpx

SMOKE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smoke.py"
URL = "https://hr.example.test"
KEY = "smoke-key-0123456789abcdef"


def _load_smoke():
    """Carga ``scripts/smoke.py`` por su ruta (no es un paquete)."""
    spec = importlib.util.spec_from_file_location("smoke", SMOKE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _client(ask_without_key=401, ask_with_key=200):
    """Cliente httpx que simula el servicio con los códigos indicados."""

    def handler(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.headers.get("X-API-Key") == KEY:
            return httpx.Response(ask_with_key, json={"answer": "ok"})
        return httpx.Response(ask_without_key, json={"detail": "no"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_smoke_reports_ok_for_each_of_the_three_checks(capsys):
    """Con un servicio sano salen tres [OK] y el código es 0."""
    code = _load_smoke().main([URL], {"SMOKE_API_KEY": KEY}, _client())
    out = capsys.readouterr().out
    assert code == 0
    assert out.count("[OK]") == 3
    assert "[FAIL]" not in out
    assert KEY not in out


def test_smoke_fails_when_the_service_is_open_or_the_key_is_missing(capsys):
    """Un /ask abierto, o sin SMOKE_API_KEY, no pasa y no filtra la clave."""
    smoke = _load_smoke()
    open_service = _client(ask_without_key=200)
    code = smoke.main([URL], {"SMOKE_API_KEY": KEY}, open_service)
    out = capsys.readouterr().out
    assert code != 0
    assert out.count("[OK]") == 2
    assert out.count("[FAIL]") == 1

    code = smoke.main([URL], {}, _client())
    out = capsys.readouterr().out
    assert code != 0
    assert "SMOKE_API_KEY" in out
