"""Precios por modelo y costo por llamada."""

import json
from pathlib import Path

PER_MILLION = 1_000_000


class PricingError(ValueError):
    """Un modelo no tiene precio o el archivo de precios no es válido."""


class Prices:
    """Tabla de precios en USD por millón de tokens.

    :param models: Mapa ``{modelo: {"input": x, "output": y}}``.
    """

    def __init__(self, models):
        self._models = dict(models)

    def require(self, *names) -> None:
        """Verifica que cada modelo tenga precio.

        :param names: Nombres de modelo.
        :raises PricingError: Si alguno no tiene precio.
        """
        for name in names:
            self._price(name)

    def _price(self, model: str) -> dict:
        """Busca el precio de un modelo.

        :param model: Nombre del modelo.
        :return: Diccionario con ``input`` y ``output``.
        :raises PricingError: Si el modelo no tiene precio.
        """
        try:
            return self._models[model]
        except KeyError:
            raise PricingError(f"no price for model '{model}'") from None

    def cost(self, model, input_tokens, output_tokens, cached=False) -> float:
        """Calcula el costo de una llamada.

        :param model: Nombre del modelo.
        :param input_tokens: Tokens de entrada.
        :param output_tokens: Tokens de salida.
        :param cached: Si la llamada salió de la caché (cuesta 0).
        :return: Costo en USD.
        :raises PricingError: Si el modelo no tiene precio.
        """
        price = self._price(model)
        if cached:
            return 0.0
        return (
            input_tokens * price["input"] + output_tokens * price["output"]
        ) / PER_MILLION


def load_prices(path) -> Prices:
    """Carga el archivo de precios.

    :param path: Ruta del JSON con la clave ``models``.
    :return: Tabla de precios.
    :raises PricingError: Si el archivo no se puede leer o no es válido.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        models = data["models"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise PricingError(f"cannot read prices from {path}") from error
    return Prices(models)
