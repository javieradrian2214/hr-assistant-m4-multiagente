"""Configuración del servicio leída desde variables de entorno."""

from dataclasses import dataclass, field
from typing import Dict, Mapping

SUPPORTED_PROVIDERS = ("fake", "gateway")
DEFAULT_GATEWAY_ID = "default"
DEFAULT_MODEL_SMALL = "@cf/meta/llama-3.1-8b-instruct-fast"
DEFAULT_MODEL_LARGE = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
DEFAULT_PRICES_PATH = "data/model_prices.json"
DEFAULT_ROUTER_MAX_CHARS = 80
DEFAULT_HISTORY_WINDOW = 6
DEFAULT_MODEL_MAX_TOKENS = 300
DEFAULT_MODEL_TEMPERATURE = 0.0
DEFAULT_CACHE_TTL_SECONDS = 0
DEFAULT_MODEL_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_HISTORY_MESSAGES = 100
DEFAULT_MAX_HISTORY_CHARS = 8000
DEFAULT_PROVIDER = "fake"
DEFAULT_MAX_STEPS = 3
DEFAULT_MAX_QUESTION_CHARS = 2000
DEFAULT_EMPLOYEES_PATH = "data/employees.json"
DEFAULT_SERVICE_NAME = "hr-assistant"
DEFAULT_SLO_P95_MS = 2000
DEFAULT_ENVIRONMENT = "development"
DEFAULT_RATE_LIMIT_PER_MINUTE = 30
SUPPORTED_ORCHESTRATIONS = ("single", "multi")
DEFAULT_ORCHESTRATION = "single"
DEFAULT_MAX_ANSWER_CHARS = 2000


class ConfigError(ValueError):
    """Error de configuración que impide arrancar el servicio."""


@dataclass(frozen=True)
class Config:  # pylint: disable=too-many-instance-attributes
    """Valores de configuración ya validados.

    :param model_provider: Nombre del modelo a usar.
    :param agent_max_steps: Tope de vueltas del bucle del agente.
    :param max_question_chars: Largo máximo de la pregunta.
    :param employees_path: Ruta del archivo de empleados.
    :param service_name: Campo ``service`` del log.
    :param slo_p95_ms: Meta de latencia p95 en milisegundos.
    :param langsmith_tracing: Si se envían trazas a LangSmith.
    :param hide_inputs: Si se ocultan las entradas en las trazas.
    :param hide_outputs: Si se ocultan las salidas en las trazas.
    :param environment: ``production`` activa las reglas de compliance.
    :param api_keys: ``{cliente: clave}``; secreto, fuera de ``repr``.
    :param rate_limit_per_minute: Peticiones por cliente por minuto.
    :param orchestration: ``single`` (un agente) o ``multi`` (supervisor y
        especialistas).
    :param max_answer_chars: Largo máximo de ``answer`` tras la guarda de
        salida.
    """

    model_provider: str
    agent_max_steps: int
    max_question_chars: int
    employees_path: str
    service_name: str = DEFAULT_SERVICE_NAME
    slo_p95_ms: int = DEFAULT_SLO_P95_MS
    langsmith_tracing: bool = False
    hide_inputs: bool = True
    hide_outputs: bool = True
    cf_account_id: str = ""
    cf_gateway_id: str = DEFAULT_GATEWAY_ID
    cf_api_token: str = field(default="", repr=False)
    model_small: str = DEFAULT_MODEL_SMALL
    model_large: str = DEFAULT_MODEL_LARGE
    routing: bool = True
    router_max_chars: int = DEFAULT_ROUTER_MAX_CHARS
    history_window: int = DEFAULT_HISTORY_WINDOW
    model_max_tokens: int = DEFAULT_MODEL_MAX_TOKENS
    model_temperature: float = DEFAULT_MODEL_TEMPERATURE
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS
    prices_path: str = DEFAULT_PRICES_PATH
    model_timeout_seconds: float = DEFAULT_MODEL_TIMEOUT_SECONDS
    max_history_messages: int = DEFAULT_MAX_HISTORY_MESSAGES
    max_history_chars: int = DEFAULT_MAX_HISTORY_CHARS
    environment: str = DEFAULT_ENVIRONMENT
    api_keys: Dict[str, str] = field(default_factory=dict, repr=False)
    rate_limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE
    orchestration: str = DEFAULT_ORCHESTRATION
    max_answer_chars: int = DEFAULT_MAX_ANSWER_CHARS


def parse_api_keys(raw: str) -> Dict[str, str]:
    """Lee ``cliente:clave,cliente2:clave2``.

    :param raw: Texto de ``API_KEYS``.
    :return: Diccionario ``{cliente: clave}``; vacío si no hay texto.
    :raises ConfigError: Si una entrada está mal formada. El mensaje dice
        el número de la entrada y su largo, nunca su contenido.
    """
    if not raw.strip():
        return {}
    keys = {}
    for position, entry in enumerate(raw.split(","), start=1):
        client, separator, key = entry.strip().partition(":")
        client, key = client.strip(), key.strip()
        if not separator or not client or not key or client in keys:
            raise ConfigError(
                f"API_KEYS entry {position} is malformed or repeated; "
                f"expected client:key (entry length {len(entry.strip())})"
            )
        keys[client] = key
    return keys


def _number(env, name, default, kind):
    """Lee un número que no puede ser negativo.

    :param env: Variables de entorno.
    :param name: Nombre de la variable.
    :param default: Valor por omisión.
    :param kind: ``int`` o ``float``.
    :return: El número validado.
    :raises ConfigError: Si no es un número o es negativo.
    """
    raw = env.get(name)
    if raw is None:
        return default
    try:
        value = kind(raw)
    except ValueError as error:
        raise ConfigError(f"{name} must be a number, got '{raw}'") from error
    if value < 0:
        raise ConfigError(f"{name} must not be negative, got {value}")
    return value


def _positive_number(env, name, default):
    """Lee un número decimal mayor que cero.

    :param env: Variables de entorno.
    :param name: Nombre de la variable.
    :param default: Valor por omisión.
    :return: El número validado.
    :raises ConfigError: Si no es un número mayor que cero.
    """
    value = _number(env, name, default, float)
    if value == 0:
        raise ConfigError(f"{name} must be greater than 0, got {value}")
    return value


def _boolean(env: Mapping[str, str], name: str, default: bool) -> bool:
    """Lee un booleano (``true`` o ``false``) de la variable indicada.

    :param env: Variables de entorno.
    :param name: Nombre de la variable.
    :param default: Valor por omisión.
    :return: El booleano validado.
    :raises ConfigError: Si no es ``true`` ni ``false``.
    """
    raw = env.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value not in ("true", "false"):
        raise ConfigError(f"{name} must be true or false, got '{raw}'")
    return value == "true"


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    """Lee un entero positivo de la variable indicada.

    :param env: Variables de entorno.
    :param name: Nombre de la variable.
    :param default: Valor por omisión.
    :return: El entero validado.
    :raises ConfigError: Si no es un entero mayor que cero.
    """
    raw = env.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ConfigError(f"{name} must be an integer, got '{raw}'") from error
    if value <= 0:
        raise ConfigError(f"{name} must be greater than 0, got {value}")
    return value


def _orchestration(env: Mapping[str, str]) -> str:
    """Lee el modo de orquestación de ``ORCHESTRATION``.

    :param env: Variables de entorno.
    :return: ``single`` o ``multi``; ausente o en blanco cae a ``single``.
    :raises ConfigError: Si el valor no es un modo conocido.
    """
    raw = env.get("ORCHESTRATION") or ""
    value = raw.strip().lower()
    if not value:
        return DEFAULT_ORCHESTRATION
    if value not in SUPPORTED_ORCHESTRATIONS:
        raise ConfigError(f"ORCHESTRATION '{raw}' is not supported")
    return value


def _gateway_id(env: Mapping[str, str]) -> str:
    """Lee ``CF_GATEWAY_ID``; ausente o en blanco cae a ``default``.

    Así nunca se arma una URL del gateway con un segmento vacío.

    :param env: Variables de entorno.
    :return: Id del gateway sin espacios alrededor.
    """
    value = (env.get("CF_GATEWAY_ID") or "").strip()
    return value or DEFAULT_GATEWAY_ID


def load_config(env: Mapping[str, str]) -> Config:
    """Construye y valida la configuración.

    :param env: Variables de entorno.
    :type env: Mapping[str, str]
    :return: Configuración validada.
    :rtype: Config
    :raises ConfigError: Si algún valor es inválido.
    """
    provider = env.get("MODEL_PROVIDER", DEFAULT_PROVIDER)
    if provider not in SUPPORTED_PROVIDERS:
        raise ConfigError(f"MODEL_PROVIDER '{provider}' is not supported")
    account = env.get("CF_ACCOUNT_ID", "")
    gateway_id = _gateway_id(env)
    token = env.get("CF_API_TOKEN", "")
    if provider == "gateway":
        # Con gateway la cuenta y el token son obligatorios; CF_GATEWAY_ID
        # es opcional y cae a "default".
        for name in ("CF_ACCOUNT_ID", "CF_API_TOKEN"):
            if not env.get(name, "").strip():
                raise ConfigError(f"{name} is required with gateway")
    return Config(
        cf_account_id=account,
        cf_gateway_id=gateway_id,
        cf_api_token=token,
        model_small=env.get("MODEL_SMALL", DEFAULT_MODEL_SMALL),
        model_large=env.get("MODEL_LARGE", DEFAULT_MODEL_LARGE),
        routing=_boolean(env, "ROUTING", True),
        router_max_chars=_positive_int(
            env, "ROUTER_MAX_CHARS", DEFAULT_ROUTER_MAX_CHARS
        ),
        history_window=_number(
            env, "HISTORY_WINDOW", DEFAULT_HISTORY_WINDOW, int
        ),
        model_max_tokens=_positive_int(
            env, "MODEL_MAX_TOKENS", DEFAULT_MODEL_MAX_TOKENS
        ),
        model_temperature=_number(
            env, "MODEL_TEMPERATURE", DEFAULT_MODEL_TEMPERATURE, float
        ),
        cache_ttl_seconds=_number(
            env, "CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL_SECONDS, int
        ),
        prices_path=env.get("PRICES_PATH", DEFAULT_PRICES_PATH),
        model_timeout_seconds=_positive_number(
            env, "MODEL_TIMEOUT_SECONDS", DEFAULT_MODEL_TIMEOUT_SECONDS
        ),
        max_history_messages=_positive_int(
            env, "MAX_HISTORY_MESSAGES", DEFAULT_MAX_HISTORY_MESSAGES
        ),
        max_history_chars=_positive_int(
            env, "MAX_HISTORY_CHARS", DEFAULT_MAX_HISTORY_CHARS
        ),
        model_provider=provider,
        agent_max_steps=_positive_int(env, "AGENT_MAX_STEPS", DEFAULT_MAX_STEPS),
        max_question_chars=_positive_int(
            env, "MAX_QUESTION_CHARS", DEFAULT_MAX_QUESTION_CHARS
        ),
        employees_path=env.get("EMPLOYEES_PATH", DEFAULT_EMPLOYEES_PATH),
        service_name=env.get("SERVICE_NAME", DEFAULT_SERVICE_NAME),
        slo_p95_ms=_positive_int(env, "SLO_P95_MS", DEFAULT_SLO_P95_MS),
        langsmith_tracing=_boolean(env, "LANGSMITH_TRACING", False),
        hide_inputs=_boolean(env, "HIDE_INPUTS", True),
        hide_outputs=_boolean(env, "HIDE_OUTPUTS", True),
        environment=env.get("ENVIRONMENT", DEFAULT_ENVIRONMENT).strip().lower(),
        api_keys=parse_api_keys(env.get("API_KEYS", "")),
        rate_limit_per_minute=_positive_int(
            env, "RATE_LIMIT_PER_MINUTE", DEFAULT_RATE_LIMIT_PER_MINUTE
        ),
        orchestration=_orchestration(env),
        max_answer_chars=_positive_int(
            env, "MAX_ANSWER_CHARS", DEFAULT_MAX_ANSWER_CHARS
        ),
    )
