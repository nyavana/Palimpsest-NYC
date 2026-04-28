"""Cost-aware LLM router.

This is the heart of the dual-backend capability:

- `simple` requests go to the local-tier OpenAI-compatible endpoint.
- `standard` requests go to OpenRouter (`OPENROUTER_STANDARD_MODEL`).
- `complex` requests go to OpenRouter (`OPENROUTER_COMPLEX_MODEL`).

V1: both tiers terminate at OpenRouter; the split exists so each backend has
its own circuit breaker and so v2 can swap the local-tier URL to an on-device
endpoint without a code change.

Policies enforced here:
1. Cache first (by canonicalized request hash, TTL by complexity).
2. Circuit breaker per backend — open after 3 failures in 60s, cool down 30s.
3. Fallback ladder — local-down silently upgrades `simple` to the standard
   cloud model; cloud-down surfaces an explicit error for `standard`/`complex`
   rather than silently downgrading user-facing narration.
4. Telemetry emitted for every call (hits, misses, errors).
5. Every call returns a `ChatResponse` or raises a typed exception; requests
   are never silently dropped.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

from app.llm.adapters import LLMAdapter, LlamaCppAdapter, OpenRouterAdapter
from app.llm.cache import LLMCache
from app.llm.models import (
    ChatRequest,
    ChatResponse,
    Complexity,
    NormalizedRequest,
    ToolCall,
    Usage,
)
from app.llm.telemetry import TelemetrySink
from app.logging import get_logger

log = get_logger(__name__)

BackendName = Literal["local", "openrouter"]

# ── Exceptions ───────────────────────────────────────────────────────


class LLMRouterError(RuntimeError):
    """Base class for router failures exposed to callers."""


class CloudBackendUnavailableError(LLMRouterError):
    """Raised when OpenRouter is circuit-broken for a standard/complex call."""


class UnknownToolError(LLMRouterError):
    """Raised when the LLM asks to call a tool not in the fixed surface."""


# ── Circuit breaker ──────────────────────────────────────────────────


@dataclass
class _Breaker:
    fail_threshold: int
    window_s: int
    cooldown_s: int
    failures: list[float] = field(default_factory=list)
    opened_at: float | None = None

    def record_failure(self) -> None:
        now = time.monotonic()
        self.failures = [t for t in self.failures if now - t < self.window_s]
        self.failures.append(now)
        if len(self.failures) >= self.fail_threshold and self.opened_at is None:
            self.opened_at = now

    def record_success(self) -> None:
        self.failures.clear()
        self.opened_at = None

    def is_open(self) -> bool:
        if self.opened_at is None:
            return False
        if time.monotonic() - self.opened_at >= self.cooldown_s:
            # Half-open: clear state, let the next call try.
            self.opened_at = None
            self.failures.clear()
            return False
        return True


# ── Router ───────────────────────────────────────────────────────────


@dataclass
class BackendConfig:
    local_model: str
    standard_model: str
    complex_model: str


class LLMRouter:
    """Dispatch chat requests across local and cloud backends."""

    def __init__(
        self,
        *,
        local: LLMAdapter,
        cloud: LLMAdapter,
        cache: LLMCache,
        telemetry: TelemetrySink,
        config: BackendConfig,
        cb_fail_threshold: int = 3,
        cb_window_s: int = 60,
        cb_cooldown_s: int = 30,
    ) -> None:
        self._local = local
        self._cloud = cloud
        self._cache = cache
        self._telemetry = telemetry
        self._config = config
        self._local_breaker = _Breaker(cb_fail_threshold, cb_window_s, cb_cooldown_s)
        self._cloud_breaker = _Breaker(cb_fail_threshold, cb_window_s, cb_cooldown_s)

    # -- Public API -------------------------------------------------

    async def chat(self, request: ChatRequest) -> ChatResponse:
        request_id = uuid.uuid4().hex
        t0 = time.perf_counter()

        backend, model, upgraded_from = self._select_backend(request.complexity)
        normalized = NormalizedRequest(
            model=model,
            messages=request.messages,
            tools=request.tools,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            response_format=request.response_format,
        )

        # 1. Cache lookup (canonicalized by request content only)
        cached = await self._cache.get(normalized)
        if cached is not None:
            latency_ms = (time.perf_counter() - t0) * 1000
            await self._telemetry.emit(
                TelemetrySink.build(
                    request_id=request_id,
                    backend=backend,
                    model=model,
                    complexity=request.complexity,
                    cached=True,
                    latency_ms=latency_ms,
                    prompt_tokens=cached.usage.prompt_tokens,
                    completion_tokens=cached.usage.completion_tokens,
                    cost_usd=0.0,
                    tags=request.tags,
                )
            )
            return self._to_chat_response(
                cached=True,
                backend=backend,
                upgraded_from=upgraded_from,
                normalized_id=cached.id,
                content=cached.content,
                tool_calls=cached.tool_calls,
                usage=Usage(
                    prompt_tokens=cached.usage.prompt_tokens,
                    completion_tokens=cached.usage.completion_tokens,
                    total_tokens=cached.usage.total_tokens,
                    cost_usd=0.0,
                ),
                model=model,
                latency_ms=latency_ms,
            )

        # 2. Dispatch to backend
        adapter = self._local if backend == "local" else self._cloud
        try:
            response = await adapter.complete(normalized)
            self._breaker_for(backend).record_success()
        except Exception as exc:  # noqa: BLE001 — translated into telemetry + retry
            self._breaker_for(backend).record_failure()
            latency_ms = (time.perf_counter() - t0) * 1000
            await self._telemetry.emit(
                TelemetrySink.build(
                    request_id=request_id,
                    backend=backend,
                    model=model,
                    complexity=request.complexity,
                    cached=False,
                    latency_ms=latency_ms,
                    error_code=type(exc).__name__,
                    tags=request.tags,
                )
            )
            # One retry with fresh backend selection (may upgrade/downgrade per ladder)
            retry_backend, retry_model, retry_from = self._select_backend(request.complexity)
            if retry_backend == backend and retry_model == model:
                raise
            return await self.chat(
                ChatRequest(
                    messages=request.messages,
                    complexity=request.complexity,
                    tools=request.tools,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    response_format=request.response_format,
                    tags={**request.tags, "retry_of": request_id},
                )
            )

        latency_ms = (time.perf_counter() - t0) * 1000
        await self._cache.put(normalized, response, request.complexity)
        await self._telemetry.emit(
            TelemetrySink.build(
                request_id=request_id,
                backend=backend,
                model=response.model,
                complexity=request.complexity,
                cached=False,
                latency_ms=latency_ms,
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                cost_usd=response.usage.cost_usd,
                tags=request.tags,
            )
        )

        return self._to_chat_response(
            cached=False,
            backend=backend,
            upgraded_from=upgraded_from,
            normalized_id=response.id,
            content=response.content,
            tool_calls=response.tool_calls,
            usage=response.usage,
            model=response.model,
            latency_ms=latency_ms,
        )

    async def aclose(self) -> None:
        await self._local.aclose()
        await self._cloud.aclose()

    # -- Internal helpers -------------------------------------------

    def _select_backend(
        self, complexity: Complexity
    ) -> tuple[BackendName, str, Literal["local"] | None]:
        """Pick (backend, model, upgraded_from) honoring the fallback ladder."""
        if complexity == "simple":
            if not self._local_breaker.is_open():
                return "local", self._config.local_model, None
            # local down → upgrade to mini
            return "openrouter", self._config.standard_model, "local"

        if complexity == "standard":
            if self._cloud_breaker.is_open():
                raise CloudBackendUnavailableError("openrouter circuit-broken for standard")
            return "openrouter", self._config.standard_model, None

        # complex
        if self._cloud_breaker.is_open():
            raise CloudBackendUnavailableError("openrouter circuit-broken for complex")
        return "openrouter", self._config.complex_model, None

    def _breaker_for(self, backend: BackendName) -> _Breaker:
        return self._local_breaker if backend == "local" else self._cloud_breaker

    @staticmethod
    def _to_chat_response(
        *,
        cached: bool,
        backend: BackendName,
        upgraded_from: Literal["local"] | None,
        normalized_id: str,
        content: str | None,
        tool_calls: list[ToolCall],
        usage: Usage,
        model: str,
        latency_ms: float,
    ) -> ChatResponse:
        return ChatResponse(
            id=normalized_id,
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            backend=backend,
            model=model,
            cached=cached,
            upgraded_from=upgraded_from,
            latency_ms=latency_ms,
        )


# ── Factory ───────────────────────────────────────────────────────────


def build_llm_router(
    *,
    openrouter_base_url: str,
    openrouter_api_key: str,
    openrouter_timeout_s: float,
    standard_model: str,
    complex_model: str,
    local_base_url: str,
    local_api_key: str,
    local_model: str,
    local_timeout_s: float,
    cache: LLMCache,
    telemetry: TelemetrySink,
    cb_fail_threshold: int,
    cb_window_s: int,
    cb_cooldown_s: int,
) -> LLMRouter:
    local = LlamaCppAdapter(
        base_url=local_base_url,
        api_key=local_api_key,
        timeout_s=local_timeout_s,
    )
    cloud = OpenRouterAdapter(
        base_url=openrouter_base_url,
        api_key=openrouter_api_key,
        timeout_s=openrouter_timeout_s,
    )
    return LLMRouter(
        local=local,
        cloud=cloud,
        cache=cache,
        telemetry=telemetry,
        config=BackendConfig(
            local_model=local_model,
            standard_model=standard_model,
            complex_model=complex_model,
        ),
        cb_fail_threshold=cb_fail_threshold,
        cb_window_s=cb_window_s,
        cb_cooldown_s=cb_cooldown_s,
    )
