"""Contadores en memoria de este proceso."""

import math
import os
import threading
from collections import deque


def _percentile(sorted_values, percent: int):
    """Percentil por rango más cercano.

    :param sorted_values: Muestras ordenadas.
    :param percent: Percentil entre 1 y 100.
    :return: El valor, o 0 si no hay muestras.
    """
    if not sorted_values:
        return 0
    rank = math.ceil(percent / 100 * len(sorted_values))
    return sorted_values[max(rank, 1) - 1]


GUARD_ACTIONS = ("allowed", "rejected", "redacted")


class Metrics:  # pylint: disable=too-many-instance-attributes
    """Peticiones, errores, latencias (ventana acotada), tokens, actividad por
    agente y eventos de las guardas.

    :param window: Número máximo de latencias que se recuerdan.
    """

    def __init__(self, window: int = 1000):
        self._latencies = deque(maxlen=window)
        self._requests = 0
        self._errors = 0
        self._input_tokens = 0
        self._output_tokens = 0
        self._cost_usd = 0.0
        self._agents = {}
        self._guards = dict.fromkeys(GUARD_ACTIONS, 0)
        self._lock = threading.Lock()

    def record_agent(self, name: str, error: bool, cost: float = 0.0) -> None:
        """Registra una ejecución de un agente o especialista.

        Toda ejecución suma en ``runs``; las fallidas también suman en
        ``errors``.

        :param name: Nombre del agente (``Agent`` en modo single).
        :param error: Si la ejecución terminó con error.
        :param cost: Costo de la ejecución en USD.
        """
        with self._lock:
            stats = self._agents.setdefault(
                name, {"runs": 0, "errors": 0, "cost_usd": 0.0}
            )
            stats["runs"] += 1
            stats["errors"] += 1 if error else 0
            stats["cost_usd"] += cost

    def record_guard(self, action: str) -> None:
        """Registra el resultado de una guarda.

        :param action: ``allowed``, ``rejected`` o ``redacted``.
        :raises ValueError: Si la acción no es conocida.
        """
        if action not in GUARD_ACTIONS:
            raise ValueError(f"Unknown guard action: {action}")
        with self._lock:
            self._guards[action] += 1

    def record(self, latency_ms, is_error, input_tokens=0, output_tokens=0,
               cost_usd=0.0):
        """Registra una petición terminada.

        :param latency_ms: Latencia en milisegundos.
        :param is_error: Si terminó con error del servidor.
        :param input_tokens: Tokens de entrada usados.
        :param output_tokens: Tokens de salida usados.
        :param cost_usd: Costo de la petición en USD.
        """
        with self._lock:
            self._cost_usd += cost_usd
            self._requests += 1
            self._errors += 1 if is_error else 0
            self._latencies.append(latency_ms)
            self._input_tokens += input_tokens
            self._output_tokens += output_tokens

    def snapshot(self, slo_p95_ms) -> dict:
        """Calcula el estado actual.

        :param slo_p95_ms: Meta de latencia p95.
        :return: Diccionario de ``GET /metrics``.
        """
        with self._lock:
            ordered = sorted(self._latencies)
            requests = self._requests
            p95 = _percentile(ordered, 95)
            return {
                "pid": os.getpid(),
                "requests": requests,
                "error_rate": self._errors / requests if requests else 0,
                "latency_ms": {"p50": _percentile(ordered, 50), "p95": p95},
                "tokens": {
                    "input": self._input_tokens,
                    "output": self._output_tokens,
                },
                "cost_usd": self._cost_usd,
                "slo": {"p95_ms_target": slo_p95_ms, "met": p95 < slo_p95_ms},
                "agents": {
                    name: dict(stats) for name, stats in self._agents.items()
                },
                "guards": dict(self._guards),
            }
