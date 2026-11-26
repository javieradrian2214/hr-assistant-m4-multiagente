"""Trazas opcionales en LangSmith."""

import contextvars
import functools

from app import logs

# Prefijo de las trazas de especialista: ``agent:<nombre>``. Una traza con
# este nombre agrega ``agent`` a sus metadatos y a los de sus trazas hijas.
AGENT_TRACE_PREFIX = "agent:"

# Metadatos que las trazas abiertas heredan a las que se abren dentro de
# ellas (por ejemplo ``agent`` bajo ``agent:<nombre>``). Vive en el contexto
# de la petición, nunca a nivel de proceso.
_INHERITED = contextvars.ContextVar("trace_inherited_metadata", default=None)


def _no_trace(name, run_type="chain", metadata=None):  # pylint: disable=unused-argument
    """Fábrica vacía: devuelve la función tal cual.

    :param name: Nombre de la traza (no se usa).
    :param run_type: Tipo de la traza (no se usa).
    :param metadata: Metadatos extra (no se usan).
    :return: Decorador identidad.
    """
    return lambda func: func


def _own_metadata(name: str, metadata) -> dict:
    """Metadatos propios de una traza, que también heredan sus hijas.

    :param name: Nombre de la traza.
    :param metadata: Metadatos extra pasados a la fábrica, o ``None``.
    :return: Diccionario; incluye ``agent`` si la traza es de especialista.
    """
    own = dict(metadata or {})
    if name.startswith(AGENT_TRACE_PREFIX):
        own.setdefault("agent", name[len(AGENT_TRACE_PREFIX):])
    return own


def _request_metadata() -> dict:
    """Metadatos de la petición en curso: ``request_id`` y ``client``.

    :return: Diccionario con ``request_id`` y, si lo hay, ``client``.
    """
    metadata = {"request_id": logs.current_request_id()}
    if logs.current_client():
        metadata["client"] = logs.current_client()
    return metadata


def build_traceable(config, env, metadata=None):
    """Crea la fábrica de decoradores de trazas.

    Si las trazas están apagadas o falta ``LANGSMITH_API_KEY``, los
    decoradores devuelven la función tal cual y no se importa ``langsmith``.

    Cada traza lleva ``request_id`` y ``client`` de la petición, los
    metadatos fijos de ``metadata`` (por ejemplo ``mode``), los heredados de
    las trazas que la contienen y los suyos propios: los pasados a la fábrica
    y, en una traza ``agent:<nombre>``, ``agent``.

    :param config: Configuración validada.
    :param env: Variables de entorno (de ahí sale la clave).
    :param metadata: Metadatos fijos para todas las trazas, o ``None``.
    :return: Función ``factory(name, run_type="chain", metadata=None)(func)``.
    """
    api_key = env.get("LANGSMITH_API_KEY")
    if not config.langsmith_tracing or not api_key:
        return _no_trace

    # pylint: disable=import-outside-toplevel
    from langsmith import Client, traceable

    client = Client(
        api_key=api_key,
        hide_inputs=config.hide_inputs,
        hide_outputs=config.hide_outputs,
    )
    fixed = dict(metadata or {})

    def factory(name, run_type="chain", metadata=None):
        own = _own_metadata(name, metadata)

        def decorate(func):
            traced = traceable(name=name, run_type=run_type, client=client)(func)

            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                inherited = {**(_INHERITED.get() or {}), **own}
                data = {**fixed, **inherited, **_request_metadata()}
                token = _INHERITED.set(inherited)
                try:
                    return traced(*args, langsmith_extra={"metadata": data},
                                  **kwargs)
                finally:
                    _INHERITED.reset(token)

            return wrapper

        return decorate

    return factory
