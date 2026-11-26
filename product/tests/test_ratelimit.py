"""Pruebas del límite de peticiones (app/ratelimit.py).

Supuesto de interfaz: ``RateLimiter(limit, clock)`` y ``check(client)``,
que devuelve ``0`` si la petición pasa o los segundos que faltan (entero
positivo) para el encabezado ``Retry-After``.
"""

from app.ratelimit import RateLimiter


def test_request_at_the_limit_passes_and_the_next_is_blocked(clock):
    """Con límite 3 pasan exactamente 3 peticiones por minuto."""
    limiter = RateLimiter(3, clock)
    assert [limiter.check("alice") for _ in range(3)] == [0, 0, 0]
    assert limiter.check("alice") > 0


def test_retry_after_counts_the_seconds_left_in_the_window(clock):
    """Pasados 20 s de un minuto faltan 40 s; a los 61 s se vuelve a pasar."""
    limiter = RateLimiter(2, clock)
    assert limiter.check("alice") == 0
    clock.advance(10)
    assert limiter.check("alice") == 0
    clock.advance(10)
    assert limiter.check("alice") == 40
    assert limiter.check("bob") == 0
    clock.advance(41)
    assert limiter.check("alice") == 0
