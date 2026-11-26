"""Reglas de compliance que se revisan al arrancar en producción."""

MIN_KEY_CHARS = 16


class ComplianceError(RuntimeError):
    """El producto se niega a arrancar porque incumple una regla."""


def check_compliance(config) -> None:
    """Revisa las reglas de ``ENVIRONMENT=production``.

    Fuera de producción no aplica ninguna. Los errores nombran la variable
    y nunca incluyen el valor de una clave.

    :param config: Configuración validada.
    :raises ComplianceError: Si alguna regla no se cumple.
    """
    if config.environment != "production":
        return
    if config.model_provider == "fake":
        raise ComplianceError(
            "MODEL_PROVIDER must not be fake when ENVIRONMENT=production"
        )
    if not config.api_keys:
        raise ComplianceError(
            "API_KEYS must not be empty when ENVIRONMENT=production"
        )
    for client, key in config.api_keys.items():
        if len(key) < MIN_KEY_CHARS:
            raise ComplianceError(
                f"API_KEYS key of client '{client}' must have at least "
                f"{MIN_KEY_CHARS} characters"
            )
    if config.langsmith_tracing:
        for name, hidden in (("HIDE_INPUTS", config.hide_inputs),
                             ("HIDE_OUTPUTS", config.hide_outputs)):
            if not hidden:
                raise ComplianceError(
                    f"{name} must be true when tracing is on in production"
                )
