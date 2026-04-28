"""Unit tests for LLMRouter decision logic.

These tests exercise the router with fake adapters and a fake Redis so they
run deterministically without any network or external services. They verify
the spec requirements from `specs/llm-router/spec.md`.
"""

from __future__ import annotations

import fakeredis.aioredis
import pytest

from app.llm.adapters import LLMAdapter
from app.llm.cache import CacheTtl, LLMCache
from app.llm.models import (
    ChatRequest,
    Message,
    NormalizedRequest,
    NormalizedResponse,
    Usage,
)
from app.llm.router import (
    BackendConfig,
    CloudBackendUnavailableError,
    LLMRouter,
)
from app.llm.telemetry import TelemetrySink

pytestmark = pytest.mark.asyncio


class FakeAdapter(LLMAdapter):
    """Configurable fake that can succeed, fail, or count calls."""

    def __init__(self, name: str, *, fail: bool = False, content: str = "ok") -> None:
        self.name = name
        self._fail = fail
        self._content = content
        self.calls = 0

    async def complete(self, request: NormalizedRequest) -> NormalizedResponse:
        self.calls += 1
        if self._fail:
            raise RuntimeError("adapter exploded")
        return NormalizedResponse(
            id=f"resp-{self.calls}",
            content=self._content,
            tool_calls=[],
            usage=Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15, cost_usd=0.0),
            model=request.model,
        )

    async def aclose(self) -> None:
        return None


async def _make_router(
    *,
    local: FakeAdapter,
    cloud: FakeAdapter,
    cb_fail_threshold: int = 3,
) -> LLMRouter:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cache = LLMCache(redis, CacheTtl(simple_s=60, standard_s=60, complex_s=60))
    telemetry = TelemetrySink(redis)
    return LLMRouter(
        local=local,
        cloud=cloud,
        cache=cache,
        telemetry=telemetry,
        config=BackendConfig(
            local_model="google/gemma-4-26B-A4B-it",
            standard_model="openai/gpt-5.4-mini",
            complex_model="openai/gpt-5.4",
        ),
        cb_fail_threshold=cb_fail_threshold,
        cb_window_s=60,
        cb_cooldown_s=30,
    )


def _req(complexity: str, content: str = "hello") -> ChatRequest:
    return ChatRequest(
        messages=[Message(role="user", content=content)],
        complexity=complexity,  # type: ignore[arg-type]
    )


# ── Requirement: Dual-backend dispatch by complexity ─────────────────


async def test_simple_routes_to_local() -> None:
    local = FakeAdapter("local")
    cloud = FakeAdapter("openrouter")
    router = await _make_router(local=local, cloud=cloud)

    response = await router.chat(_req("simple"))

    assert response.backend == "local"
    assert response.model == "google/gemma-4-26B-A4B-it"
    assert local.calls == 1
    assert cloud.calls == 0


async def test_standard_routes_to_cloud_mini() -> None:
    local = FakeAdapter("local")
    cloud = FakeAdapter("openrouter")
    router = await _make_router(local=local, cloud=cloud)

    response = await router.chat(_req("standard"))

    assert response.backend == "openrouter"
    assert response.model == "openai/gpt-5.4-mini"
    assert cloud.calls == 1


async def test_complex_routes_to_cloud_full() -> None:
    local = FakeAdapter("local")
    cloud = FakeAdapter("openrouter")
    router = await _make_router(local=local, cloud=cloud)

    response = await router.chat(_req("complex"))

    assert response.backend == "openrouter"
    assert response.model == "openai/gpt-5.4"
    assert cloud.calls == 1


# ── Requirement: Fallback ladder ─────────────────────────────────────


async def test_simple_upgrades_to_cloud_when_local_breaker_open() -> None:
    local = FakeAdapter("local", fail=True)
    cloud = FakeAdapter("openrouter")
    router = await _make_router(local=local, cloud=cloud, cb_fail_threshold=1)

    # First call fails on local, router retries with upgraded backend
    response = await router.chat(_req("simple", content="first"))

    assert response.backend == "openrouter"
    assert response.upgraded_from == "local"
    assert local.calls >= 1
    assert cloud.calls == 1


async def test_complex_raises_when_cloud_breaker_open() -> None:
    local = FakeAdapter("local")
    cloud = FakeAdapter("openrouter", fail=True)
    router = await _make_router(local=local, cloud=cloud, cb_fail_threshold=1)

    # First complex call fails on cloud, trips breaker
    with pytest.raises(Exception):  # noqa: B017 - covers both Runtime and CloudBackendUnavailable
        await router.chat(_req("complex", content="c1"))

    # Second complex call should surface CloudBackendUnavailableError
    with pytest.raises(CloudBackendUnavailableError):
        await router.chat(_req("complex", content="c2"))

    assert local.calls == 0


# ── Requirement: Request caching ─────────────────────────────────────


async def test_identical_requests_hit_cache() -> None:
    local = FakeAdapter("local")
    cloud = FakeAdapter("openrouter")
    router = await _make_router(local=local, cloud=cloud)

    first = await router.chat(_req("simple", content="same"))
    second = await router.chat(_req("simple", content="same"))

    assert first.cached is False
    assert second.cached is True
    assert local.calls == 1  # second call served from cache


async def test_whitespace_only_diff_still_hits_cache() -> None:
    local = FakeAdapter("local")
    cloud = FakeAdapter("openrouter")
    router = await _make_router(local=local, cloud=cloud)

    await router.chat(_req("simple", content="hello"))
    second = await router.chat(_req("simple", content="  hello  "))

    assert second.cached is True
    assert local.calls == 1


async def test_different_temperature_is_cache_miss() -> None:
    local = FakeAdapter("local")
    cloud = FakeAdapter("openrouter")
    router = await _make_router(local=local, cloud=cloud)

    req = _req("simple")
    await router.chat(req)
    await router.chat(
        ChatRequest(
            messages=req.messages,
            complexity="simple",
            temperature=0.9,
        )
    )

    assert local.calls == 2
