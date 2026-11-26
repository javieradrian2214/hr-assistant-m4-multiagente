"""Validación de la clave de cada cliente (encabezado ``X-API-Key``)."""

import hmac
from typing import Mapping, Optional

API_KEY_HEADER = "X-API-Key"
INVALID_KEY_DETAIL = "invalid or missing API key"


def authenticate(api_keys: Mapping[str, str], provided: Optional[str]):
    """Busca el cliente dueño de la clave recibida.

    La comparación usa ``hmac.compare_digest`` y recorre todos los clientes
    sin cortar al primer acierto, para no revelar nada por el tiempo.

    :param api_keys: Diccionario ``{cliente: clave}``.
    :param provided: Valor del encabezado, o ``None`` si no llegó.
    :return: Nombre del cliente, o ``None`` si la clave falta o no existe.
    """
    if not provided:
        return None
    candidate = provided.encode("utf-8")
    found = None
    for client, key in api_keys.items():
        if not key:
            continue
        if hmac.compare_digest(candidate, key.encode("utf-8")):
            found = client
    return found
