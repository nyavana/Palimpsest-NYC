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
from app.agent.tools.search_places import SearchPlacesTool
from app.config import Settings, get_settings
from app.db.engine import build_engine, build_session_factory
from app.embeddings import build_embedder
from app.llm.cache import CacheTtl, LLMCache
from app.llm.router import build_llm_router
from app.llm.telemetry import TelemetrySink
from app.logging import configure_logging, get_logger
from app.routes import agent, health, llm, meta

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

    # LLM router: local-tier (V1 = OpenRouter free Gemma) + cloud-tier (OpenRouter)
    cache = LLMCache(
        redis_client,
        CacheTtl(
            simple_s=settings.llm_router.cache_ttl_simple_s,
            standard_s=settings.llm_router.cache_ttl_standard_s,
            complex_s=settings.llm_router.cache_ttl_complex_s,
        ),
    )
    telemetry = TelemetrySink(redis_client)
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

    # Agent surface — V1 contract: exactly one tool registered (search_places)
    tool_registry = ToolRegistry()
    tool_registry.register(SearchPlacesTool())
    app.state.agent_tool_registry = tool_registry
    app.state.agent_loop_builder = lambda _request: AgentLoop(
        router=app.state.llm_router,
        registry=tool_registry,
    )

    # Meta-instrumentation harness (populated in task 9)
    from app.meta.session_log import SessionLogger

    app.state.session_logger = SessionLogger(log_dir=settings.meta.session_log_dir)

    try:
        yield
    finally:
        log.info("api.shutdown")
        await app.state.llm_router.aclose()
        await engine.dispose()
        await redis_client.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(
        title="Palimpsest NYC API",
        version=__version__,
        description="Agentic walking-tour backend for Palimpsest NYC",
        lifespan=lifespan,
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
    app.include_router(llm.router, prefix="/llm", tags=["llm"])
    app.include_router(meta.router, prefix="/internal", tags=["meta"])
    app.include_router(agent.router)

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
