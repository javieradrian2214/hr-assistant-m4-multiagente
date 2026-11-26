"""Pruebas de costo en el agente, las métricas y los modelos simulados."""

import json

import pytest
from conftest import LARGE, SMALL

from app.agent import Agent
from app.config import Config
from app.llm import Completion, build_models
from app.metrics import Metrics
from app.pricing import load_prices


class ScriptedCompletions:
    """Modelo que devuelve ``Completion`` predefinidos en orden."""

    def __init__(self, replies):
        self.replies = list(replies)

    def complete(self, messages):  # pylint: disable=unused-argument
        """Devuelve la siguiente respuesta del guion."""
        return self.replies.pop(0)


def completion(payload, cached=False):
    """Completion de SMALL con 1000 tokens de entrada y 500 de salida."""
    return Completion(
        text=json.dumps(payload), model=SMALL, input_tokens=1000,
        output_tokens=500, cached=cached,
    )


def test_agent_adds_up_tokens_cost_and_cached_calls_across_steps(
    directory, prices_file,
):
    model = ScriptedCompletions([
        completion({"tool": "get_employee", "args": {"employee_id": "EMP-0004"}}),
        completion({"answer": "listo"}, cached=True),
    ])
    agent = Agent(model, directory, max_steps=3, prices=load_prices(prices_file))

    result = agent.run([{"role": "user", "content": "EMP-0004"}])

    assert result.steps == 2
    assert (result.input_tokens, result.output_tokens) == (2000, 1000)
    assert result.cached_calls == 1
    assert result.cost_usd == pytest.approx(0.002)
    assert result.model == SMALL


def test_metrics_accumulate_cost():
    metrics = Metrics()

    metrics.record(10, False, 100, 50, 0.002)
    metrics.record(12, False, 100, 50, 0.003)

    assert metrics.snapshot(2000)["cost_usd"] == pytest.approx(0.005)


def test_fake_models_are_named_like_the_configured_models(directory):
    config = Config(
        model_provider="fake", agent_max_steps=3, max_question_chars=2000,
        employees_path="unused.json", model_small=SMALL, model_large=LARGE,
    )

    models = build_models(config, directory)

    assert set(models) == {SMALL, LARGE}
    reply = models[LARGE].complete([{"role": "user", "content": "hola"}])
    assert reply.model == LARGE
    assert json.loads(reply.text)["answer"]
