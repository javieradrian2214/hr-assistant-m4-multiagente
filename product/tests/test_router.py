"""Pruebas de app.router: la regla en código que elige el modelo."""

import pytest
from conftest import LARGE, SMALL

from app.config import Config
from app.router import choose_model


def make_config(**overrides):
    """Configuración mínima con nombres de modelo de prueba."""
    return Config(
        model_provider="fake", agent_max_steps=3, max_question_chars=2000,
        employees_path="unused.json", model_small=SMALL, model_large=LARGE,
        **overrides,
    )


@pytest.mark.parametrize("question", [
    "Compara a Ana con Luis",
    "Resume el departamento de Ventas",
    "Explica quién es EMP-0001",
    "¿POR QUÉ se fue Marta?",
    "Analiza Finanzas",
    "Dame TODOS los empleados",
])
def test_keywords_send_the_question_to_the_large_model(question):
    model, reason = choose_model(question, make_config())

    assert model == LARGE
    assert reason


def test_question_length_limit_is_exact_and_simple_questions_stay_small():
    config = make_config(router_max_chars=80)

    at_limit, reason = choose_model("a" * 80, config)
    over_limit, _ = choose_model("a" * 81, config)

    assert at_limit == SMALL and reason
    assert over_limit == LARGE


# --- sesión 5: find_keyword para el supervisor ------------------------------
# Supuesto: ``find_keyword(question)`` devuelve la palabra de análisis tal
# como está en la lista del enrutador (minúsculas y sin acentos) o ``None``.
# Se importa dentro de cada prueba para que su ausencia no tumbe las pruebas
# de choose_model de arriba.


@pytest.mark.parametrize("question, keyword", [
    ("Compara EMP-0001 y EMP-0002", "compara"),
    ("¿POR QUÉ se fue Marta?", "por que"),
    ("Dame TODOS los empleados", "todos"),
])
def test_find_keyword_returns_the_analysis_word_without_accents(question, keyword):
    from app.router import find_keyword  # pylint: disable=import-outside-toplevel

    assert find_keyword(question) == keyword


def test_find_keyword_returns_none_when_there_is_no_analysis_word():
    from app.router import find_keyword  # pylint: disable=import-outside-toplevel

    assert find_keyword("¿Quién es EMP-0004?") is None
    assert find_keyword("Gente de Finanzas") is None


def test_choose_model_keeps_the_same_reasons_as_before():
    config = make_config(router_max_chars=80)

    assert choose_model("Analiza Finanzas", config) == (LARGE, "keyword 'analiza'")
    assert choose_model("¿Quién es EMP-0004?", config) == (SMALL, "simple question")
    assert choose_model("a" * 81, config) == (LARGE, "longer than 80 chars")
    assert choose_model("hola", make_config(routing=False)) == (LARGE, "routing off")
