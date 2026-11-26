"""Pruebas de la validación de claves (app/auth.py).

Supuesto de interfaz: ``authenticate(api_keys, provided)`` recibe el dict
``{cliente: clave}`` y la clave del encabezado (o ``None``); devuelve el
nombre del cliente o ``None``. Compara con ``hmac.compare_digest``.
"""

import pytest

from app import auth

KEYS = {"alice": "alice-key-0123456789abcdef", "bob": "bob-key-fedcba9876543210"}


def test_valid_key_returns_the_client_name():
    """Cada clave identifica a su cliente."""
    assert auth.authenticate(KEYS, KEYS["alice"]) == "alice"
    assert auth.authenticate(KEYS, KEYS["bob"]) == "bob"


@pytest.mark.parametrize("provided", [None, "", "wrong-key", "alice-key"])
def test_missing_empty_or_unknown_key_is_rejected(provided):
    """Sin clave, vacía, desconocida o prefijo de una válida: no entra.

    Con una tabla vacía tampoco entra nadie, ni con clave vacía.
    """
    assert auth.authenticate(KEYS, provided) is None
    assert auth.authenticate({}, provided) is None


def test_key_comparison_is_constant_time(monkeypatch):
    """La comparación usa ``hmac.compare_digest``, no ``==``."""
    calls = []
    real = auth.hmac.compare_digest

    def spy(left, right):
        calls.append(1)
        return real(left, right)

    monkeypatch.setattr(auth.hmac, "compare_digest", spy)
    auth.authenticate(KEYS, "wrong-key")
    assert len(calls) >= 1
