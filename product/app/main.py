"""API web sin estado del HR Assistant, con observabilidad."""

import os
import re
import unicodedata
import uuid
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from app import logs
from app.agent import Agent
from app.auth import API_KEY_HEADER, INVALID_KEY_DETAIL, authenticate
from app.clock import SystemClock
from app.compliance import check_compliance
from app.config import Config, load_config
from app.directory import Directory
from app.gateway import ModelUnavailable
from app.guards import REDACTED, REJECTED, check_input, check_output
from app.llm import EMPLOYEE_ID_PATTERN, build_models
from app.logs import EventLogger
from app.metrics import Metrics
from app.pricing import load_prices
from app.ratelimit import RateLimiter
from app.router import choose_model
from app.specialists import SPECIALISTS
from app.supervisor import UNKNOWN_TOOL, Supervisor
from app.tracing import build_traceable

PRODUCT_DIR = Path(__file__).resolve().parent.parent
STATIC_INDEX = Path(__file__).resolve().parent / "static" / "index.html"
REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
AUDIT_ARG_KEYS = ("employee_id", "department")
AUDIT_ARG_MAX_CHARS = 64
MULTI_MODE = "multi"
SINGLE_AGENT = "Agent"
INVALID_INPUT_DETAIL = "invalid input"


class AskResponse(BaseModel):
    """Respuesta de ``POST /ask``."""

    answer: str
    steps: int
    tools_used: List[str]
    input_tokens: int
    output_tokens: int
    request_id: str
    model: str
    route: str
    cached_calls: int
    cost_usd: float
    gateway_log_ids: List[str] = []
    mode: str
    agents: List[str]


def _pick_request_id(received: Optional[str]) -> str:
    """Usa el id recibido si es seguro; si no, genera un UUID.

    :param received: Valor del encabezado, si llegó.
    :return: Identificador de la petición.
    """
    if received and _VALID_REQUEST_ID.fullmatch(received):
        return received
    return str(uuid.uuid4())


def _fold_department(name: str) -> str:
    """Normaliza un departamento para compararlo con el catálogo.

    Misma regla que ``Directory.search_by_department``: sin distinguir
    mayúsculas ni acentos y sin espacios en los extremos.

    :param name: Nombre del departamento.
    :return: Nombre normalizado.
    """
    decomposed = unicodedata.normalize("NFD", name.strip().lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _known_departments(directory) -> dict:
    """Arma el catálogo de departamentos del directorio.

    :param directory: Directorio de empleados (con ``departments``).
    :return: Diccionario ``{nombre_normalizado: nombre_del_catálogo}``; vacío
        si el directorio no expone departamentos.
    """
    try:
        names = list(getattr(directory, "departments", None) or [])
    except Exception:  # pylint: disable=broad-exception-caught
        return {}
    return {_fold_department(name): name for name in names
            if isinstance(name, str) and name}


def _audit_value(key: str, value: str, departments: dict) -> str:
    """Devuelve el valor auditable o ``[REDACTED]`` si no se reconoce.

    :param key: ``employee_id`` o ``department``.
    :param value: Texto que mandó el modelo.
    :param departments: Catálogo de ``_known_departments``.
    :return: El id con forma ``EMP-NNNN``, el nombre del departamento tal
        como está en el catálogo o ``[REDACTED]``.
    """
    if key == "employee_id" and EMPLOYEE_ID_PATTERN.fullmatch(value):
        return value
    if key == "department":
        return departments.get(_fold_department(value), REDACTED)
    return REDACTED


def _safe_audit_args(args, departments: Optional[dict] = None) -> dict:
    """Deja solo los argumentos conocidos y validados contra el producto.

    Las claves desconocidas, los valores que no son texto y los de más de
    ``AUDIT_ARG_MAX_CHARS`` caracteres se descartan. ``employee_id`` se
    conserva solo si tiene la forma ``EMP-NNNN`` (``EMPLOYEE_ID_PATTERN``) y
    ``department`` solo si está en el catálogo del directorio; cualquier otro
    texto se registra como ``[REDACTED]``, nunca con su valor original.

    :param args: Argumentos que mandó el modelo (pueden ser cualquier cosa).
    :param departments: Catálogo de ``_known_departments``.
    :return: Diccionario con las claves permitidas y sus valores seguros.
    """
    if not isinstance(args, dict):
        return {}
    return {
        key: _audit_value(key, args[key], departments or {})
        for key in AUDIT_ARG_KEYS
        if isinstance(args.get(key), str)
        and len(args[key]) <= AUDIT_ARG_MAX_CHARS
    }


def _install_observer(api: FastAPI, clock, events, metrics) -> None:
    """Agrega el middleware de id, latencia, log y manejo de fallos.

    :param api: Aplicación FastAPI.
    :param clock: Reloj con ``monotonic()``.
    :param events: Emisor de eventos de log.
    :param metrics: Contador de métricas.
    """

    @api.middleware("http")
    async def observe(request: Request, call_next):
        """Fija el id, mide la latencia, registra y atrapa los fallos."""
        request_id = _pick_request_id(request.headers.get(REQUEST_ID_HEADER))
        token = logs.set_request_id(request_id)
        request.state.tokens = (0, 0)
        request.state.cost = 0.0
        started = clock.monotonic()
        try:
            response = await call_next(request)
        except ModelUnavailable as error:
            events.emit("error", error_type=type(error).__name__)
            response = JSONResponse(
                {"detail": "model unavailable", "request_id": request_id},
                status_code=502,
            )
        except Exception as error:  # pylint: disable=broad-exception-caught
            events.emit("error", error_type=type(error).__name__)
            response = JSONResponse(
                {"detail": "internal error", "request_id": request_id},
                status_code=500,
            )
        latency_ms = round((clock.monotonic() - started) * 1000, 3)
        response.headers[REQUEST_ID_HEADER] = request_id
        client = getattr(request.state, "client", "")
        extra = {"client": client} if client else {}
        events.emit(
            "request", method=request.method, path=request.url.path,
            status=response.status_code, latency_ms=latency_ms, **extra,
        )
        metrics.record(
            latency_ms, response.status_code >= 500, *request.state.tokens,
            request.state.cost,
        )
        logs.reset_request_id(token)
        return response


def _resolve(path: str) -> Path:
    """Resuelve una ruta relativa respecto a ``product/``.

    :param path: Ruta absoluta o relativa.
    :return: Ruta absoluta.
    """
    resolved = Path(path)
    return resolved if resolved.is_absolute() else PRODUCT_DIR / resolved


def _build_request_model(config: Config):
    """Crea el modelo del cuerpo de ``POST /ask`` con los límites de entrada.

    :param config: Configuración con los largos y el número máximo de mensajes.
    :return: Clase pydantic del cuerpo.
    """

    class HistoryMessage(BaseModel):
        """Mensaje previo enviado por el cliente, con largo acotado."""

        role: Literal["user", "assistant"]
        content: str = Field(max_length=config.max_history_chars)

    class AskRequest(BaseModel):
        """Cuerpo de ``POST /ask``."""

        question: str = Field(min_length=1, max_length=config.max_question_chars)
        history: Optional[List[HistoryMessage]] = Field(
            default=None, max_length=config.max_history_messages
        )

    return AskRequest


def _make_require_client(config: Config, events, limiter):
    """Crea la dependencia que exige clave válida y respeta el límite.

    :param config: Configuración con las claves por cliente.
    :param events: Emisor de eventos de log.
    :param limiter: Limitador de peticiones por cliente.
    :return: Función de dependencia para FastAPI.
    """

    def require_client(request: Request) -> str:
        """Exige una clave válida y respeta el límite del cliente.

        :param request: Petición en curso.
        :return: Nombre del cliente.
        :raises HTTPException: 401 sin clave válida; 429 si pasó el límite.
        """
        client = authenticate(
            config.api_keys, request.headers.get(API_KEY_HEADER)
        )
        if client is None:
            events.emit("auth_rejected", path=request.url.path)
            raise HTTPException(status_code=401, detail=INVALID_KEY_DETAIL)
        request.state.client = client
        wait = limiter.check(client)
        if wait > 0:
            events.emit("rate_limited", path=request.url.path, client=client)
            raise HTTPException(
                status_code=429, detail="rate limit exceeded",
                headers={"Retry-After": str(wait)},
            )
        return client

    return require_client


class _AskService:  # pylint: disable=too-many-instance-attributes
    """Responde preguntas con el agente (single) o el supervisor (multi).

    No guarda estado entre peticiones: cada pregunta crea su propio agente o
    supervisor; solo comparte dependencias de solo lectura y ``Metrics``.

    :param config: Configuración validada.
    :param models: Diccionario ``{nombre: modelo}``.
    :param directory: Directorio de empleados.
    :param events: Emisor de eventos de log.
    :param metrics: Contador de métricas de este proceso.
    """

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
            self, config: Config, models: dict, directory, events, metrics):
        self._config = config
        self._models = models
        self._directory = directory
        self._events = events
        self._metrics = metrics
        self._traceable = build_traceable(
            config, os.environ, metadata={"mode": config.orchestration}
        )
        self._prices = load_prices(_resolve(config.prices_path))
        self._prices.require(config.model_small, config.model_large)

    def audit(self, tool, args, agent: str = SINGLE_AGENT) -> None:
        """Registra cada herramienta ejecutada, sin datos sin validar.

        :param tool: Nombre de la herramienta.
        :param args: Argumentos que mandó el modelo.
        :param agent: Agente que la ejecutó (``Agent`` en modo single).
        """
        self._events.emit(
            "audit", action="tool_call", tool=tool, agent=agent,
            args=_safe_audit_args(args, _known_departments(self._directory)),
        )

    def tool_denied(self, tool: str, agent: str = SINGLE_AGENT) -> None:
        """Registra ``tool_denied`` igual que el supervisor en modo multi.

        Solo guarda el agente y el nombre de la herramienta, nunca sus
        argumentos. Un nombre que no es una herramienta conocida se registra
        como ``unknown``, para no copiar al log texto arbitrario del modelo.

        :param tool: Nombre de herramienta que pidió el modelo.
        :param agent: Agente que la pidió (``Agent`` en modo single).
        """
        known = {name for spec in SPECIALISTS.values() for name in spec.tools}
        self._events.emit("tool_denied", agent=agent,
                          tool=tool if tool in known else UNKNOWN_TOOL)

    def _record_guard(self, stage: str, report) -> None:
        """Emite el evento ``guard`` y lo cuenta en las métricas.

        Solo registra tipos de PII, nunca valores ni texto.

        :param stage: ``input`` u ``output``.
        :param report: ``GuardReport`` de la guarda.
        """
        self._events.emit(
            "guard", stage=stage, action=report.action,
            pii_types=list(report.pii_types),
        )
        self._metrics.record_guard(report.action)

    def _guard_input(self, body) -> None:
        """Guarda de entrada, antes de correr cualquier agente.

        :param body: Cuerpo validado de la petición.
        :raises HTTPException: 422 ``invalid input`` si la pregunta o el
            historial traen el prefijo de resultado de herramienta.
        """
        report = check_input(body.question, body.history)
        self._record_guard("input", report)
        if report.action == REJECTED:
            raise HTTPException(status_code=422, detail=INVALID_INPUT_DETAIL)

    def _guard_output(self, answer: str) -> str:
        """Guarda de salida: enmascara PII, claves y el prefijo, y corta.

        :param answer: Respuesta del agente.
        :return: Respuesta segura para el cliente.
        """
        text, report = check_output(
            answer, list(self._config.api_keys.values()),
            self._config.max_answer_chars,
        )
        self._record_guard("output", report)
        return text

    def _run_single(self, messages, question: str):
        """Modo single: el enrutador elige el modelo y corre ``Agent``.

        :param messages: Conversación ya recortada.
        :param question: Pregunta de la persona.
        :return: Tupla ``(AgentResult, agentes, ruta)``.
        :raises ModelUnavailable: Si el modelo falla (se cuenta el error).
        """
        name, route = choose_model(question, self._config)
        agent = Agent(
            self._models[name], self._directory, self._config.agent_max_steps,
            audit=self.audit, traceable=self._traceable, prices=self._prices,
            model_name=name, on_denied=self.tool_denied,
        )
        try:
            result = self._traceable("agent_run")(agent.run)(messages)
        except Exception:
            self._metrics.record_agent(SINGLE_AGENT, True, 0.0)
            raise
        self._metrics.record_agent(SINGLE_AGENT, False, result.cost_usd)
        return result, [SINGLE_AGENT], route

    def _run_multi(self, messages, question: str):
        """Modo multi: el supervisor decide y corre un especialista.

        El supervisor emite ``supervisor_decision`` y ``tool_denied`` y
        cuenta las métricas por especialista (también los errores).

        :param messages: Conversación ya recortada.
        :param question: Pregunta de la persona.
        :return: Tupla ``(AgentResult, agentes, ruta)``.
        :raises ModelUnavailable: Si el modelo falla.
        """
        supervisor = Supervisor(
            self._config, self._models, self._directory, events=self._events,
            audit=self.audit, traceable=self._traceable, prices=self._prices,
            metrics=self._metrics,
        )
        outcome = supervisor.run(messages, question)
        return outcome.result, list(outcome.agents), outcome.decision.route

    def _messages(self, body) -> list:
        """Arma la conversación con la ventana de historial configurada.

        :param body: Cuerpo validado de la petición.
        :return: Lista de mensajes para el modelo.
        """
        history = [m.model_dump() for m in body.history or []]
        window = self._config.history_window
        history = history[-window:] if window > 0 else []
        return history + [{"role": "user", "content": body.question}]

    def answer(self, body, request: Request) -> dict:
        """Responde la pregunta del cliente ya identificado.

        Orden: guarda de entrada, ventana de historial, agente según el modo,
        guarda de salida, evento ``agent_run`` y respuesta.

        :param body: Cuerpo validado de la petición.
        :param request: Petición en curso.
        :return: Diccionario compatible con ``AskResponse``.
        :raises HTTPException: 422 ``invalid input`` desde la guarda.
        """
        self._guard_input(body)
        messages = self._messages(body)
        mode = self._config.orchestration
        run = self._run_multi if mode == MULTI_MODE else self._run_single
        result, agents, route = run(messages, body.question)
        request.state.tokens = (result.input_tokens, result.output_tokens)
        request.state.cost = result.cost_usd
        answer = self._guard_output(result.answer)
        self._events.emit(
            "agent_run", question_chars=len(body.question),
            history_messages=len(messages) - 1, steps=result.steps,
            tools=result.tools_used, input_tokens=result.input_tokens,
            output_tokens=result.output_tokens, stopped=result.stopped,
            model=result.model, route=route,
            cached_calls=result.cached_calls, cost_usd=result.cost_usd,
            gateway_log_ids=result.gateway_log_ids, mode=mode,
            agent=agents[-1], agents=agents,
        )
        return {
            "model": result.model, "route": route,
            "cached_calls": result.cached_calls,
            "cost_usd": result.cost_usd,
            "gateway_log_ids": result.gateway_log_ids,
            "answer": answer, "steps": result.steps,
            "tools_used": result.tools_used,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "request_id": logs.current_request_id(),
            "mode": mode, "agents": agents,
        }


def _register_routes(  # pylint: disable=R0913,R0917
        api: FastAPI, config: Config, service: _AskService,
        require_ask_client, require_metrics_client, metrics) -> None:
    """Registra las rutas de la API.

    Cada endpoint protegido usa su propia dependencia para que el cupo de
    ``/ask`` y el de ``/metrics`` no se compartan.

    :param api: Aplicación FastAPI.
    :param config: Configuración validada.
    :param service: Servicio que responde las preguntas.
    :param require_ask_client: Dependencia de autenticación y límite de
        ``/ask``.
    :param require_metrics_client: Dependencia de autenticación y límite de
        ``/metrics``.
    :param metrics: Contador de métricas.
    """
    ask_request = _build_request_model(config)

    @api.get("/")
    def index():
        """Sirve la página web."""
        return FileResponse(STATIC_INDEX, media_type="text/html")

    @api.get("/health")
    def health():
        """Informa que el proceso está vivo."""
        return {"status": "ok", "pid": os.getpid()}

    @api.get("/metrics", dependencies=[Depends(require_metrics_client)])
    def get_metrics():
        """Devuelve las métricas de este proceso."""
        return metrics.snapshot(config.slo_p95_ms)

    @api.post("/ask", response_model=AskResponse)
    def ask(body: ask_request, request: Request,  # type: ignore[valid-type]
            client: str = Depends(require_ask_client)):
        """Responde una pregunta sin guardar nada."""
        token = logs.set_client(client)
        try:
            return service.answer(body, request)
        finally:
            logs.reset_client(token)


def create_app(config: Config, models, directory, clock=None,
               metrics=None) -> FastAPI:
    """Crea la aplicación con sus dependencias inyectadas.

    :param config: Configuración validada.
    :param models: Diccionario ``{nombre: modelo}``; también se acepta un
        único modelo, que se usa para los dos nombres.
    :param directory: Directorio de empleados.
    :param clock: Reloj con ``now()`` y ``monotonic()``.
    :param metrics: Contador de métricas de este proceso.
    :return: Aplicación FastAPI.
    :raises PricingError: Si un modelo configurado no tiene precio.
    """
    check_compliance(config)
    clock = clock or SystemClock()
    metrics = metrics or Metrics()
    # Un limitador por endpoint: el cupo de /ask y el de /metrics son
    # independientes, con el mismo límite por minuto y el mismo reloj.
    ask_limiter = RateLimiter(config.rate_limit_per_minute, clock)
    metrics_limiter = RateLimiter(config.rate_limit_per_minute, clock)
    events = EventLogger(config.service_name, clock)
    if not isinstance(models, dict):
        models = {config.model_small: models, config.model_large: models}
    service = _AskService(config, models, directory, events, metrics)
    api = FastAPI(title="HR Assistant")
    _install_observer(api, clock, events, metrics)
    require_ask_client = _make_require_client(config, events, ask_limiter)
    require_metrics_client = _make_require_client(
        config, events, metrics_limiter
    )
    _register_routes(api, config, service, require_ask_client,
                     require_metrics_client, metrics)
    return api


def _build_default_app() -> FastAPI:
    """Construye la aplicación con la configuración del entorno.

    :return: Aplicación FastAPI.
    """
    config = load_config(os.environ)
    directory = Directory(_resolve(config.employees_path))
    return create_app(config, build_models(config, directory), directory)


app = _build_default_app()
