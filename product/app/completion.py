"""Resultado de una llamada al modelo."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Completion:
    """Resultado de una llamada al modelo.

    :param text: Texto devuelto por el modelo.
    :param model: Nombre del modelo que respondió.
    :param input_tokens: Tokens de entrada.
    :param output_tokens: Tokens de salida.
    :param cached: Si la respuesta salió de la caché del gateway.
    :param gateway_log_id: Id de la petición en AI Gateway; vacío si no hay.
    """

    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached: bool = False
    gateway_log_id: str = ""
