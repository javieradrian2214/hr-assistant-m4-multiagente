"""Reloj inyectable: único lugar donde se toca la hora real."""

import time
from datetime import datetime, timezone


class SystemClock:
    """Reloj real del sistema."""

    def now(self) -> datetime:
        """Devuelve la hora actual en UTC.

        :return: Fecha y hora con zona UTC.
        """
        return datetime.fromtimestamp(time.time(), tz=timezone.utc)

    def monotonic(self) -> float:
        """Devuelve segundos monótonos para medir duraciones.

        :return: Segundos desde un punto arbitrario.
        """
        return time.monotonic()
