"""Pruebas de app.config."""

import pytest

from app.config import ConfigError, load_config


def test_defaults_are_used_when_env_is_empty():
    config = load_config({})

    assert config.model_provider == "fake"
    assert config.agent_max_steps == 3
    assert config.max_question_chars == 2000
    assert config.employees_path == "data/employees.json"


@pytest.mark.parametrize(
    "env",
    [
        {"AGENT_MAX_STEPS": "0"},
        {"AGENT_MAX_STEPS": "many"},
        {"MODEL_PROVIDER": "gpt"},
    ],
)
def test_invalid_values_stop_startup_with_a_clear_message(env):
    with pytest.raises(ConfigError) as error:
        load_config(env)

    assert list(env)[0] in str(error.value)
