"""Regla en código que elige el modelo de cada pregunta."""

import unicodedata

KEYWORDS = ("compara", "resume", "explica", "por que", "analiza", "todos")


def _fold(text: str) -> str:
    """Minúsculas y sin acentos.

    :param text: Texto original.
    :return: Texto normalizado.
    """
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def find_keyword(question: str):
    """Busca la primera palabra de análisis de la pregunta.

    Compara sin mayúsculas ni acentos, en el orden de ``KEYWORDS``.

    :param question: Pregunta de la persona.
    :return: La palabra tal como está en ``KEYWORDS`` (minúsculas y sin
        acentos), o ``None`` si no hay ninguna.
    """
    folded = _fold(question)
    for keyword in KEYWORDS:
        if keyword in folded:
            return keyword
    return None


def choose_model(question: str, config):
    """Elige entre el modelo pequeño y el capaz.

    :param question: Pregunta de la persona.
    :param config: Configuración con ``routing``, ``router_max_chars``,
        ``model_small`` y ``model_large``.
    :return: Tupla ``(modelo, motivo)``.
    """
    if not config.routing:
        return config.model_large, "routing off"
    if len(question) > config.router_max_chars:
        return config.model_large, f"longer than {config.router_max_chars} chars"
    keyword = find_keyword(question)
    if keyword is not None:
        return config.model_large, f"keyword '{keyword}'"
    return config.model_small, "simple question"
