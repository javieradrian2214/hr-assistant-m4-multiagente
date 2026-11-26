"""Log en JSON, una línea por evento, con el id de la petición."""

import json
import sys
from contextvars import ContextVar

NO_REQUEST_ID = "-"
_request_id = ContextVar("request_id", default=NO_REQUEST_ID)
_client = ContextVar("client", default="")


def set_request_id(value: str):
    """Fija el id de la petición en curso.

    :param value: Identificador de la petición.
    :return: Token para restaurar el valor anterior.
    """
    return _request_id.set(value)


def reset_request_id(token) -> None:
    """Restaura el id anterior.

    :param token: Token devuelto por ``set_request_id``.
    """
    _request_id.reset(token)


def current_request_id() -> str:
    """Devuelve el id de la petición en curso.

    :return: El id, o ``-`` fuera de una petición.
    """
    return _request_id.get()


def set_client(value: str):
    """Fija el nombre del cliente de la petición en curso.

    :param value: Nombre del cliente (nunca su clave).
    :return: Token para restaurar el valor anterior.
    """
    return _client.set(value)


def reset_client(token) -> None:
    """Restaura el cliente anterior.

    :param token: Token devuelto por ``set_client``.
    """
    _client.reset(token)


def current_client() -> str:
    """Devuelve el cliente de la petición en curso.

    :return: El nombre, o cadena vacía si no hay cliente identificado.
    """
    return _client.get()


class EventLogger:
    """Emite eventos como líneas JSON.

    :param service: Valor del campo ``service``.
    :param clock: Reloj con ``now()``.
    :param stream: Destino; por omisión la salida estándar actual.
    """

    def __init__(self, service: str, clock, stream=None):
        self._service = service
        self._clock = clock
        self._stream = stream

    def emit(self, event: str, **fields) -> None:
        """Escribe una línea JSON.

        :param event: Nombre del evento.
        :param fields: Campos adicionales, ya sin datos personales.
        """
        line = {
            "ts": self._clock.now().isoformat(),
            "service": self._service,
            "event": event,
            "request_id": current_request_id(),
        }
        if current_client():
            line["client"] = current_client()
        line.update(fields)
        stream = self._stream or sys.stdout
        stream.write(json.dumps(line, default=str) + "\n")
        stream.flush()
