"""Pruebas de la configuración nueva de la sesión 4."""

import pytest

from app.config import ConfigError, load_config

STRONG_A = "alice-key-0123456789abcdef"
STRONG_B = "bob-key-fedcba9876543210"


def test_new_settings_are_read_and_keys_stay_out_of_repr():
    """Hay valores por omisión seguros; las claves no salen en ``repr``."""
    config = load_config({})
    assert config.environment == "development"
    assert not config.api_keys
    assert config.rate_limit_per_minute == 30

    config = load_config({
        "ENVIRONMENT": "production",
        "RATE_LIMIT_PER_MINUTE": "5",
        "API_KEYS": f"alice:{STRONG_A},bob:{STRONG_B}",
        "MODEL_PROVIDER": "fake",
    })
    assert config.environment == "production"
    assert config.rate_limit_per_minute == 5
    assert config.api_keys == {"alice": STRONG_A, "bob": STRONG_B}
    assert STRONG_A not in repr(config)
    assert STRONG_B not in repr(config)


@pytest.mark.parametrize("bad_entry", ["topsecretvalue", ":onlysecret99"])
def test_malformed_api_keys_report_entry_and_length_not_value(bad_entry):
    """El error dice cuál entrada falla y su largo, nunca su contenido."""
    env = {"API_KEYS": f"alice:{STRONG_A},{bad_entry}"}
    with pytest.raises(ConfigError) as caught:
        load_config(env)
    message = str(caught.value)
    assert "API_KEYS" in message
    assert "2" in message
    assert str(len(bad_entry)) in message
    assert bad_entry not in message
    assert STRONG_A not in message
