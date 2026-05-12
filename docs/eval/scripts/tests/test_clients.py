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
