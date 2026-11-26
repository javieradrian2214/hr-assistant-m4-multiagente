"""Concurrencia de los contadores de app.metrics (requisito 12 del plan).

Varios hilos registran a la vez y los totales deben cuadrar exactos.

Supuestos de interfaz (plan, ``app/metrics.py``):

- ``Metrics.record_agent(name, error, cost)`` y ``Metrics.record_guard(action)``
  usan el mismo candado que ``record``.
- ``snapshot`` agrega ``agents`` (``{nombre: {"runs", "errors",
  "cost_usd"}}``) y ``guards`` con al menos las claves ``rejected`` y
  ``redacted`` (puede traer otras).
"""

import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from app.metrics import Metrics

THREADS = 8
PER_THREAD = 500
TOTAL = THREADS * PER_THREAD
HALF = TOTAL // 2
# 0.25 es exacto en binario: la suma no acumula error de redondeo.
COST = 0.25


def run_in_threads(work):
    """Corre ``work(indice_del_hilo)`` ``PER_THREAD`` veces en cada hilo.

    Una barrera hace que todos los hilos empiecen a la vez, y un intervalo de
    cambio de hilo muy corto fuerza que se intercalen. Las excepciones de los
    hilos se relanzan aquí.
    """
    barrier = threading.Barrier(THREADS, timeout=10)

    def worker(index):
        barrier.wait()
        for _ in range(PER_THREAD):
            work(index)

    previous = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        with ThreadPoolExecutor(max_workers=THREADS) as pool:
            list(pool.map(worker, range(THREADS)))
    finally:
        sys.setswitchinterval(previous)


def test_concurrent_requests_are_all_counted_exactly():
    metrics = Metrics(window=TOTAL)

    run_in_threads(lambda index: metrics.record(
        1.0, is_error=index % 2 == 0, input_tokens=3, output_tokens=2,
        cost_usd=COST,
    ))
    snapshot = metrics.snapshot(slo_p95_ms=2000)

    assert snapshot["requests"] == TOTAL
    assert snapshot["error_rate"] == 0.5
    assert snapshot["tokens"] == {"input": 3 * TOTAL, "output": 2 * TOTAL}
    assert snapshot["cost_usd"] == COST * TOTAL


def test_concurrent_agent_and_guard_counters_add_up_exactly():
    metrics = Metrics()

    def work(index):
        if index % 2 == 0:
            metrics.record_agent("EmployeeAgent", False, COST)
            metrics.record_guard("redacted")
        else:
            metrics.record_agent("AnalystAgent", True, 0.0)
            metrics.record_guard("rejected")

    run_in_threads(work)
    snapshot = metrics.snapshot(slo_p95_ms=2000)

    employee = snapshot["agents"]["EmployeeAgent"]
    assert (employee["runs"], employee["errors"]) == (HALF, 0)
    assert employee["cost_usd"] == COST * HALF
    assert snapshot["agents"]["AnalystAgent"]["errors"] == HALF
    # Se exigen las dos claves, sin prohibir que el desarrollador agregue otras.
    guards = snapshot["guards"]
    assert (guards["rejected"], guards["redacted"]) == (HALF, HALF)
    assert snapshot["requests"] == 0
