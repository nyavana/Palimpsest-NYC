"""Tests for the OpenRouter chat client + /internal/retrieve HTTP client.

Both clients are thin httpx wrappers; we mock the network via
``httpx.MockTransport`` so the suite is hermetic — no real OpenRouter
or local-API calls.
"""

from __future__ import annotations

import json

import httpx
import pytest

from docs.eval.scripts.openrouter_client import OpenRouterChatClient
from docs.eval.scripts.retrieve_client import InternalRetrieveClient

pytestmark = pytest.mark.asyncio


async def test_openrouter_chat_extracts_content_and_usage():
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "m"
        assert body["messages"] == [{"role": "user", "content": "x"}]
        assert body["temperature"] == 0.0
        assert request.headers["authorization"] == "Bearer k"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {
                    "prompt_tokens": 50,
                    "completion_tokens": 5,
                    "total_cost": 0.001,
                },
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://x") as inner:
        client = OpenRouterChatClient(http_client=inner, api_key="k")
        resp = await client.chat(
            model="m",
            messages=[{"role": "user", "content": "x"}],
            temperature=0.0,
        )

    assert resp["content"] == "ok"
    assert resp["prompt_tokens"] == 50
    assert resp["completion_tokens"] == 5
    assert resp["cost_usd"] == pytest.approx(0.001)


async def test_openrouter_chat_handles_missing_usage_fields():
    """A response with no usage block should not crash; numeric fields default to 0."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "hi"}}]},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://x") as inner:
        client = OpenRouterChatClient(http_client=inner, api_key="k")
        resp = await client.chat(model="m", messages=[], temperature=0.0)

    assert resp["content"] == "hi"
    assert resp["prompt_tokens"] == 0
    assert resp["completion_tokens"] == 0
    assert resp["cost_usd"] == 0.0


async def test_openrouter_chat_prefers_usage_cost_over_total_cost():
    """Per OpenRouter docs the canonical field is ``cost``; we prefer it when present."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "cost": 0.0025,
                    "total_cost": 0.0099,
                },
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://x") as inner:
        client = OpenRouterChatClient(http_client=inner, api_key="k")
        resp = await client.chat(model="m", messages=[], temperature=0.0)

    assert resp["cost_usd"] == pytest.approx(0.0025)


async def test_openrouter_chat_falls_back_to_total_cost_when_cost_missing():
    """Legacy / OpenAI-passthrough rows only carry ``total_cost``."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_cost": 0.0011,
                },
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://x") as inner:
        client = OpenRouterChatClient(http_client=inner, api_key="k")
        resp = await client.chat(model="m", messages=[], temperature=0.0)

    assert resp["cost_usd"] == pytest.approx(0.0011)


async def test_openrouter_chat_returns_zero_cost_when_neither_field_present():
    """Free-tier rows have ``usage`` but no cost field — must not crash."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://x") as inner:
        client = OpenRouterChatClient(http_client=inner, api_key="k")
        resp = await client.chat(model="m", messages=[], temperature=0.0)

    assert resp["cost_usd"] == 0.0


async def test_openrouter_chat_forwards_response_format():
    """``response_format`` must round-trip into the request payload when supplied."""

    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "{}"}}]},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://x") as inner:
        client = OpenRouterChatClient(http_client=inner, api_key="k")
        await client.chat(
            model="m",
            messages=[],
            temperature=0.0,
            response_format={"type": "json_object"},
        )

    assert captured["response_format"] == {"type": "json_object"}


async def test_openrouter_chat_omits_response_format_when_not_set():
    """When the caller does not pass response_format, it must not appear in the payload."""

    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "x"}}]},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://x") as inner:
        client = OpenRouterChatClient(http_client=inner, api_key="k")
        await client.chat(model="m", messages=[], temperature=0.0)

    assert "response_format" not in captured


async def test_openrouter_chat_raises_on_http_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://x") as inner:
        client = OpenRouterChatClient(http_client=inner, api_key="bad")
        with pytest.raises(httpx.HTTPStatusError):
            await client.chat(model="m", messages=[], temperature=0.0)


async def test_internal_retrieve_client_posts():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/internal/retrieve"
        assert json.loads(request.content) == {"query": "q", "top_k": 5}
        return httpx.Response(200, json={"results": [{"doc_id": "a"}]})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://x") as inner:
        client = InternalRetrieveClient(http_client=inner)
        results = await client.retrieve(query="q", top_k=5)

    assert results == [{"doc_id": "a"}]


async def test_internal_retrieve_client_returns_empty_list_when_missing():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://x") as inner:
        client = InternalRetrieveClient(http_client=inner)
        results = await client.retrieve(query="q", top_k=3)

    assert results == []


async def test_internal_retrieve_client_raises_on_http_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://x") as inner:
        client = InternalRetrieveClient(http_client=inner)
        with pytest.raises(httpx.HTTPStatusError):
            await client.retrieve(query="q", top_k=1)
