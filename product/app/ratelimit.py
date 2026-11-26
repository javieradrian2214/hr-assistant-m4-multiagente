"""Límite de peticiones por cliente con ventana de un minuto."""

import math
import threading

WINDOW_SECONDS = 60


class RateLimiter:
    """Cuenta peticiones por cliente dentro de una ventana fija.

    La ventana de un cliente empieza con su primera petición y dura un
    minuto. El estado vive en este proceso.

    :param limit: Peticiones permitidas por ventana.
    :param clock: Reloj con ``monotonic()``.
    """

    def __init__(self, limit: int, clock):
        self._limit = limit
        self._clock = clock
        self._windows = {}
        self._lock = threading.Lock()

    def check(self, client: str) -> int:
        """Registra una petición del cliente.

        :param client: Nombre del cliente.
        :return: ``0`` si pasa; si no, los segundos que faltan para que la
            ventana termine (para ``Retry-After``).
        """
        now = self._clock.monotonic()
        with self._lock:
            start, count = self._windows.get(client, (now, 0))
            if now - start >= WINDOW_SECONDS:
                start, count = now, 0
            if count < self._limit:
                self._windows[client] = (start, count + 1)
                return 0
            self._windows[client] = (start, count)
            return max(1, math.ceil(start + WINDOW_SECONDS - now))
