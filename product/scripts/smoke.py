"""Prueba de humo del HR Assistant publicado.

Uso: ``SMOKE_API_KEY=<clave> python scripts/smoke.py <url>``

La clave se lee solo de la variable de entorno, nunca de un argumento, y nunca
se imprime.
"""

import os
import sys
import time

import httpx

QUESTION = {"question": "How many vacation days does Ana have?"}
TIMEOUT_SECONDS = 60
# Reintentos de /health: 12 intentos y 10 s entre ellos dan unos 2 minutos
# para que despierte el servicio (topes: 2 a 20 intentos, espera hasta 60 s).
HEALTH_ATTEMPTS = 12
HEALTH_WAIT_SECONDS = 10


def _report(ok, label):
    """Imprime el resultado de una comprobación y lo devuelve."""
    print(f"[{'OK' if ok else 'FAIL'}] {label}")
    return ok


def _status(call):
    """Ejecuta ``call`` y devuelve el código HTTP, o None si no hubo respuesta."""
    try:
        return call().status_code
    except httpx.HTTPError:
        return None


def _health_ok(http, base, sleep):
    """Consulta /health con reintentos acotados; el plan free duerme el servicio.

    Hace como máximo ``HEALTH_ATTEMPTS`` intentos y espera
    ``HEALTH_WAIT_SECONDS`` entre uno y otro (una espera menos que intentos).
    Un error de conexión cuenta como intento fallido. Nunca se imprime el
    texto de una excepción, porque podría contener la clave.
    """
    for attempt in range(1, HEALTH_ATTEMPTS + 1):
        if _status(lambda: http.get(f"{base}/health")) == 200:
            return _report(True, "/health responde 200")
        if attempt < HEALTH_ATTEMPTS:
            print(f"[WAIT] /health sin respuesta, intento {attempt} de "
                  f"{HEALTH_ATTEMPTS}; reintento en {HEALTH_WAIT_SECONDS} s")
            sleep(HEALTH_WAIT_SECONDS)
    return _report(False, f"/health responde 200 (tras {HEALTH_ATTEMPTS} intentos)")


def main(argv, env, client=None, sleep=time.sleep):
    """Corre las tres comprobaciones; devuelve 0 si todas pasan."""
    if len(argv) != 1:
        print("Uso: smoke.py <url>")
        return 2
    key = env.get("SMOKE_API_KEY", "")
    if not key:
        print("[FAIL] falta la variable SMOKE_API_KEY")
        return 1
    base = argv[0].rstrip("/")
    http = client or httpx.Client(timeout=TIMEOUT_SECONDS)
    results = [
        _health_ok(http, base, sleep),
        _report(_status(lambda: http.post(f"{base}/ask", json=QUESTION)) == 401,
                "/ask sin clave responde 401"),
        _report(
            _status(lambda: http.post(
                f"{base}/ask", json=QUESTION, headers={"X-API-Key": key}
            )) == 200,
            "/ask con clave responde 200",
        ),
    ]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], os.environ))
