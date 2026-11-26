"""Cliente de Cloudflare AI Gateway (Workers AI) con httpx."""

from app.completion import Completion

GATEWAY_URL = (
    "https://gateway.ai.cloudflare.com/v1/{account}/{gateway}"
    "/workers-ai/v1/chat/completions"
)

# Cabecera con el id de la petición en AI Gateway. NO está verificada contra
# la documentación de Cloudflare: confirmar el nombre antes de depender de ella.
LOG_ID_HEADER = "cf-aig-log-id"


class ModelUnavailable(Exception):
    """El modelo no respondió; el mensaje nunca incluye secretos."""


class GatewayModel:
    """Modelo real al que se llama a través de AI Gateway.

    :param name: Nombre del modelo de Workers AI.
    :param config: Configuración con las variables ``CF_*`` y las palancas.
    :param client: Cliente ``httpx.Client`` (se inyecta para no usar la red
        en las pruebas).
    """

    def __init__(self, name, config, client):
        self._name = name
        self._config = config
        self._client = client

    def complete(self, messages) -> Completion:
        """Llama al modelo y lee el texto, los tokens y el estado de caché.

        :param messages: Conversación como lista de ``{"role", "content"}``.
        :return: Resultado de la llamada.
        :raises ModelUnavailable: Ante cualquier fallo de red, HTTP o formato.
        """
        config = self._config
        url = GATEWAY_URL.format(
            account=config.cf_account_id, gateway=config.cf_gateway_id
        )
        headers = {"Authorization": f"Bearer {config.cf_api_token}"}
        if config.cache_ttl_seconds > 0:
            headers["cf-aig-cache-ttl"] = str(config.cache_ttl_seconds)
        body = {
            "model": self._name,
            "messages": messages,
            "max_tokens": config.model_max_tokens,
            "temperature": config.model_temperature,
        }
        try:
            response = self._client.post(url, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
            usage = data["usage"]
            return Completion(
                text=data["choices"][0]["message"]["content"],
                model=self._name,
                input_tokens=int(usage["prompt_tokens"]),
                output_tokens=int(usage["completion_tokens"]),
                cached=response.headers.get("cf-aig-cache-status") == "HIT",
                gateway_log_id=response.headers.get(LOG_ID_HEADER) or "",
            )
        except Exception as error:  # pylint: disable=broad-exception-caught
            # Solo el tipo: el mensaje original podría traer la URL o datos.
            raise ModelUnavailable(
                f"gateway call failed: {type(error).__name__}"
            ) from None
