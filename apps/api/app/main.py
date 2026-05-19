"""FastAPI application factory and lifespan wiring."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app import __version__
from app.agent.loop import AgentLoop
from app.agent.tools.base import ToolRegistry
from app.agent.tools.plan_walk import PlanWalkTool
from app.agent.tools.search_places import SearchPlacesTool
from app.config import Settings, get_settings
from app.db.engine import build_engine, build_session_factory
from app.embeddings import build_embedder
from app.llm.cache import CacheTtl, LLMCache
from app.llm.router import build_llm_router
from app.llm.telemetry import TelemetrySink
from app.logging import configure_logging, get_logger
from app.routes import agent, config, health, internal_retrieve, llm, meta, places
from app.routing import OsrmBackend

log = get_logger(__name__)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach an X-Request-ID to every request and bind it to the log context."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()
        response.headers["X-Request-ID"] = request_id
        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    log.info("api.startup", version=__version__, env=settings.app_env)

    # Shared Redis client for cache + telemetry
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    app.state.redis = redis_client

    # LLM router: local-tier (V1 = OpenRouter free Gemma) + cloud-tier (OpenRouter).
    # When no OPENROUTER_API_KEY is configured, the server runs in BYOK mode:
    # the singleton router is not built and every /agent/ask request must
    # supply an X-LLM-Credentials header (decoded into a per-request router
    # in routes/agent.py). /llm/chat returns 503 in this mode.
    cache = LLMCache(
        redis_client,
        CacheTtl(
            simple_s=settings.llm_router.cache_ttl_simple_s,
            standard_s=settings.llm_router.cache_ttl_standard_s,
            complex_s=settings.llm_router.cache_ttl_complex_s,
        ),
    )
    telemetry = TelemetrySink(redis_client)
    app.state.byok_required = settings.byok_required
    app.state.llm_cache = cache
    app.state.llm_telemetry = telemetry
    if settings.byok_required:
        app.state.llm_router = None
        log.info("llm_router.byok_mode")
    else:
        assert settings.openrouter.api_key is not None  # narrowed by byok_required
        app.state.llm_router = build_llm_router(
            openrouter_base_url=settings.openrouter.base_url,
            openrouter_api_key=settings.openrouter.api_key.get_secret_value(),
            openrouter_timeout_s=settings.openrouter.timeout_s,
            standard_model=settings.openrouter.standard_model,
            complex_model=settings.openrouter.complex_model,
            local_base_url=settings.local_llm.base_url,
            local_api_key=settings.local_llm.api_key.get_secret_value(),
            local_model=settings.local_llm.model,
            local_timeout_s=settings.local_llm.timeout_s,
            cache=cache,
            telemetry=telemetry,
            cb_fail_threshold=settings.llm_router.cb_fail_threshold,
            cb_window_s=settings.llm_router.cb_window_s,
            cb_cooldown_s=settings.llm_router.cb_cooldown_s,
        )

    # Database (async SQLAlchemy)
    engine = build_engine(settings.postgres)
    app.state.db_engine = engine
    app.state.db_session_factory = build_session_factory(engine)

    # Sentence-transformers embedder singleton — loaded once, ~30MB weights
    # read from /cache/huggingface (mounted volume).
    log.info("embedder.loading", model=settings.embeddings.model)
    app.state.embedder = build_embedder(settings.embeddings)
    log.info("embedder.ready", dim=app.state.embedder.dim)

    # Reranker singleton — loaded only when needed. CPU-only.
    if settings.reranker_enabled or settings.retrieval_mode == "hybrid_reranked":
        log.info("reranker.loading", model=settings.reranker_model)
        from app.embeddings.reranker import build_reranker

        app.state.reranker = build_reranker(settings.reranker_model)
        log.info("reranker.ready")
    else:
        app.state.reranker = None

    # Routing backend (V1 = OSRM in-cluster). The backend opens a fresh
    # httpx.AsyncClient per `route()` call so there is no connection pool
    # to dispose on shutdown.
    app.state.routing_backend = OsrmBackend(base_url=settings.osrm_base_url)
    log.info("routing_backend.ready", base_url=settings.osrm_base_url)

    # Agent surface — V1 (route-planning amendment): two tools, search_places
    # and plan_walk. `plan_walk` reads `routing_backend` and `retrieval_ledger`
    # from its `ToolExecutionContext`. The routing_backend is process-wide and
    # is wired into the context in apps/api/app/routes/agent.py (Wave 4); the
    # retrieval_ledger is per-conversation and is attached to the context by
    # the agent loop before each tool dispatch (Wave 3). This file only
    # registers the tool — the context plumbing lives where the context is
    # constructed.
    # TODO(wave-4): once routes/agent.py builds ToolExecutionContext with
    #   routing_backend=app.state.routing_backend, this comment can be deleted.
    # Build the retriever once and share it between the agent tool and the
    # /internal/retrieve endpoint. Coupling them keeps Phase 4's ablation rows
    # honest (naive_rag-{mode} vs palimpsest-{mode} isolates only the agent
    # loop, not the retrieval pipeline). See task 4.5 Step 6.
    from app.retrieval.factory import build_retriever

    retriever = build_retriever(
        mode=settings.retrieval_mode,
        reranker=getattr(app.state, "reranker", None),
    )
    app.state.retriever_for_internal = retriever
    tool_registry = ToolRegistry()
    tool_registry.register(
        SearchPlacesTool(
            retriever=retriever,
            mode=settings.retrieval_mode,
            reranker=getattr(app.state, "reranker", None),
        )
    )
    tool_registry.register(PlanWalkTool())
    app.state.agent_tool_registry = tool_registry
    # The builder receives the per-request router (resolved by the route
    # handler from either the singleton or X-LLM-Credentials). This lets
    # BYOK and env-key paths share the same agent loop construction code.
    app.state.agent_loop_builder = lambda _request, router: AgentLoop(
        router=router,
        registry=tool_registry,
    )
    # Stash the registry separately so the BYOK path in routes/agent.py can
    # build an AgentLoop against a per-request router without going through
    # the singleton-bound builder above.
    app.state.agent_tool_registry = tool_registry

    # Meta-instrumentation harness (populated in task 9)
    from app.meta.session_log import SessionLogger

    app.state.session_logger = SessionLogger(log_dir=settings.meta.session_log_dir)

    try:
        yield
    finally:
        log.info("api.shutdown")
        if app.state.llm_router is not None:
            await app.state.llm_router.aclose()
        await engine.dispose()
        await redis_client.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    # /docs, /redoc, /openapi.json are reachable via the /api proxy on a
    # public deployment, so they're disabled outside dev.
    docs_kwargs: dict = (
        {"docs_url": None, "redoc_url": None, "openapi_url": None}
        if settings.app_env == "production"
        else {}
    )
    app = FastAPI(
        title="Palimpsest NYC API",
        version=__version__,
        description="Agentic walking-tour backend for Palimpsest NYC",
        lifespan=lifespan,
        **docs_kwargs,
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIdMiddleware)

    # ── Routes ─────────────────────────────────────────────────
    app.include_router(health.router)
    app.include_router(config.router)
    app.include_router(llm.router, prefix="/llm", tags=["llm"])
    app.include_router(meta.router, prefix="/internal", tags=["meta"])
    app.include_router(places.router)
    app.include_router(agent.router)
    app.include_router(internal_retrieve.router)

    # ── Exception handlers ────────────────────────────────────
    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_exception", path=request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": "internal_server_error", "detail": str(exc)},
        )

    return app


app = create_app()
