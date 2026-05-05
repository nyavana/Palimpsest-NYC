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


# ── BYOK: user-supplied credentials are isolated from the singleton ──


class _CapturingAdapter:
    """Fake OpenRouterAdapter for BYOK tests. Records init kwargs and
    completion calls, optionally fails to exercise breaker isolation."""

    name = "openrouter"
    construction_log: list[dict[str, object]] = []

    def __init__(self, *, base_url: str, api_key: str, timeout_s: float) -> None:
        type(self).construction_log.append(
            {"base_url": base_url, "api_key": api_key, "timeout_s": timeout_s}
        )
        self.base_url = base_url
        self.api_key = api_key
        self.calls = 0
        self.fail = False

    async def complete(self, request: NormalizedRequest) -> NormalizedResponse:
        self.calls += 1
        if self.fail:
            raise RuntimeError("user key bad")
        return NormalizedResponse(
            id=f"byok-resp-{self.calls}",
            content="byok-ok",
            tool_calls=[],
            usage=Usage(prompt_tokens=2, completion_tokens=2, total_tokens=4, cost_usd=0.0),
            model=request.model,
        )

    async def aclose(self) -> None:
        return None


async def test_with_user_credentials_constructs_adapter_with_user_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`with_user_credentials` builds two OpenRouterAdapter instances
    (one for local, one for cloud) using the user-supplied base_url and
    api_key. Both adapters route to the same user-chosen model."""
    _CapturingAdapter.construction_log = []
    monkeypatch.setattr("app.llm.router.OpenRouterAdapter", _CapturingAdapter)

    local = FakeAdapter("local")
    cloud = FakeAdapter("openrouter")
    singleton = await _make_router(local=local, cloud=cloud)

    byok = singleton.with_user_credentials(
        api_key="sk-user-1234",
        model="anthropic/claude-haiku",
        base_url="https://api.openrouter.ai/v1",
        timeout_s=12.5,
    )
    assert byok is not singleton

    # Two adapters: one for local tier, one for cloud tier.
    assert len(_CapturingAdapter.construction_log) == 2
    for entry in _CapturingAdapter.construction_log:
        assert entry["api_key"] == "sk-user-1234"
        assert entry["base_url"] == "https://api.openrouter.ai/v1"
        assert entry["timeout_s"] == 12.5


async def test_with_user_credentials_isolates_breaker_from_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user-supplied bad key trips ONLY the BYOK router's breakers;
    the shared singleton's breakers stay closed and its adapters are
    never called."""
    _CapturingAdapter.construction_log = []
    monkeypatch.setattr("app.llm.router.OpenRouterAdapter", _CapturingAdapter)

    local = FakeAdapter("local")
    cloud = FakeAdapter("openrouter")
    singleton = await _make_router(local=local, cloud=cloud, cb_fail_threshold=1)

    byok = singleton.with_user_credentials(
        api_key="sk-bad",
        model="x/y",
        base_url="https://example.test",
        timeout_s=10.0,
    )

    # Mark the BYOK router's adapters as failing. Both the local-tier and
    # cloud-tier adapters share the same fake class — flip their flag.
    byok._local.fail = True  # type: ignore[attr-defined]
    byok._cloud.fail = True  # type: ignore[attr-defined]

    for _ in range(5):
        with pytest.raises(Exception):  # noqa: B017, PT011 — broad: standard/complex paths raise different types
            await byok.chat(_req("standard"))

    # Singleton's breakers untouched, singleton adapters never called.
    assert not singleton._cloud_breaker.is_open()
    assert not singleton._local_breaker.is_open()
    assert local.calls == 0
    assert cloud.calls == 0

    # Singleton normal flow still serves traffic.
    response = await singleton.chat(_req("simple"))
    assert response.backend == "local"
    assert local.calls == 1


async def test_with_user_credentials_bypasses_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two identical chat() calls on the BYOK router both hit the
    adapter — the no-op cache never serves a hit."""
    _CapturingAdapter.construction_log = []
    monkeypatch.setattr("app.llm.router.OpenRouterAdapter", _CapturingAdapter)

    local = FakeAdapter("local")
    cloud = FakeAdapter("openrouter")
    singleton = await _make_router(local=local, cloud=cloud)

    byok = singleton.with_user_credentials(
        api_key="sk-user",
        model="x/y",
        base_url="https://example.test",
        timeout_s=10.0,
    )

    r1 = await byok.chat(_req("standard", "same"))
    r2 = await byok.chat(_req("standard", "same"))

    assert r1.cached is False
    assert r2.cached is False
    # Both calls reached the adapter (not served from cache).
    assert byok._local.calls + byok._cloud.calls >= 2  # type: ignore[attr-defined]


async def test_byok_router_tags_telemetry_byok_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every emission from the BYOK router carries `byok=true` in tags
    (without ever including the api_key in any tag value)."""
    _CapturingAdapter.construction_log = []
    monkeypatch.setattr("app.llm.router.OpenRouterAdapter", _CapturingAdapter)

    local = FakeAdapter("local")
    cloud = FakeAdapter("openrouter")
    singleton = await _make_router(local=local, cloud=cloud)

    captured_tags: list[dict[str, str]] = []

    async def _spy_emit(record):  # type: ignore[no-untyped-def]
        captured_tags.append(dict(record.tags))

    byok = singleton.with_user_credentials(
        api_key="sk-secret-do-not-leak",
        model="x/y",
        base_url="https://example.test",
        timeout_s=10.0,
    )
    monkeypatch.setattr(byok._telemetry, "emit", _spy_emit)

    await byok.chat(_req("standard", "hello"))

    assert len(captured_tags) == 1
    assert captured_tags[0].get("byok") == "true"
    # Belt-and-braces: the secret never appears in any tag value.
    for value in captured_tags[0].values():
        assert "sk-secret" not in value


async def test_singleton_chat_does_not_carry_byok_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard: the singleton router must NOT tag emissions
    with byok=true (only the BYOK subclass does)."""
    local = FakeAdapter("local")
    cloud = FakeAdapter("openrouter")
    singleton = await _make_router(local=local, cloud=cloud)

    captured_tags: list[dict[str, str]] = []

    async def _spy_emit(record):  # type: ignore[no-untyped-def]
        captured_tags.append(dict(record.tags))

    monkeypatch.setattr(singleton._telemetry, "emit", _spy_emit)

    await singleton.chat(_req("simple", "hello"))

    assert all("byok" not in tags for tags in captured_tags)
