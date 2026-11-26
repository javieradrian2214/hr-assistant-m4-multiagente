"""Pruebas de las reglas de compliance (app/compliance.py).

Supuesto de interfaz: ``check_compliance(config)`` no devuelve nada o
lanza ``ComplianceError`` con el nombre de la variable que incumple.
"""

import pytest

from app.compliance import ComplianceError, check_compliance
from app.config import Config

STRONG_KEY = "alice-key-0123456789abcdef"


def _config(**overrides):
    """Configuración de producción que cumple todas las reglas."""
    values = {
        "model_provider": "gateway",
        "agent_max_steps": 3,
        "max_question_chars": 2000,
        "employees_path": "data/employees.json",
        "environment": "production",
        "api_keys": {"alice": STRONG_KEY},
    }
    values.update(overrides)
    return Config(**values)


def test_valid_production_config_passes():
    """Una configuración correcta (con y sin trazas ocultas) arranca."""
    check_compliance(_config())
    check_compliance(_config(langsmith_tracing=True))


@pytest.mark.parametrize(
    ("overrides", "rule"),
    [
        ({"model_provider": "fake"}, "MODEL_PROVIDER"),
        ({"api_keys": {}}, "API_KEYS"),
        ({"api_keys": {"alice": "k" * 15}}, "API_KEYS"),
        ({"langsmith_tracing": True, "hide_inputs": False}, "HIDE_INPUTS"),
        ({"langsmith_tracing": True, "hide_outputs": False}, "HIDE_OUTPUTS"),
    ],
    ids=["fake-model", "no-keys", "short-key", "open-inputs", "open-outputs"],
)
def test_production_refuses_each_broken_rule(overrides, rule):
    """Cada regla, sola, impide arrancar y se nombra en el error."""
    with pytest.raises(ComplianceError) as caught:
        check_compliance(_config(**overrides))
    assert rule in str(caught.value)


def test_development_skips_every_rule():
    """Fuera de producción el modelo simulado y sin claves es válido."""
    config = _config(
        environment="development", model_provider="fake", api_keys={},
        langsmith_tracing=True, hide_inputs=False,
    )
    check_compliance(config)
