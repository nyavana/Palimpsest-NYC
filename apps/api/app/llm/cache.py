"""Redis-backed response cache for the LLM router.

Caching is keyed on a canonicalized hash of the normalized request so that
prompts with only whitespace or ordering differences collide on the same key.
TTLs differ by complexity tier.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import redis.asyncio as aioredis

from app.llm.models import Complexity, NormalizedRequest, NormalizedResponse

_CACHE_NAMESPACE = "llm:cache:v1"


@dataclass(frozen=True)
class CacheTtl:
    simple_s: int
    standard_s: int
    complex_s: int

    def for_complexity(self, complexity: Complexity) -> int:
        return {
            "simple": self.simple_s,
            "standard": self.standard_s,
            "complex": self.complex_s,
        }[complexity]


def _canonicalize(request: NormalizedRequest) -> bytes:
    """Stable canonical bytes for hashing — whitespace, ordering-insensitive."""
    payload: dict[str, Any] = {
        "model": request.model,
        "temperature": round(request.temperature, 3),
        "max_tokens": request.max_tokens,
        "response_format": request.response_format,
        "messages": [
            {
                "role": m.role,
                "content": (m.content or "").strip(),
                "name": m.name,
                "tool_call_id": m.tool_call_id,
                "tool_calls": [
                    {"name": tc.name, "arguments": tc.arguments} for tc in (m.tool_calls or [])
                ],
            }
            for m in request.messages
        ],
        "tools": [
            {"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in (request.tools or [])
        ],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def request_cache_key(request: NormalizedRequest) -> str:
    digest = hashlib.sha256(_canonicalize(request)).hexdigest()
    return f"{_CACHE_NAMESPACE}:{digest}"


class LLMCache:
    """Thin Redis wrapper for storing NormalizedResponse JSON under a request key."""

    def __init__(self, redis: aioredis.Redis, ttl: CacheTtl) -> None:
        self._redis = redis
        self._ttl = ttl

    async def get(self, request: NormalizedRequest) -> NormalizedResponse | None:
        key = request_cache_key(request)
        raw = await self._redis.get(key)
        if raw is None:
            return None
        try:
            return NormalizedResponse.model_validate_json(raw)
        except Exception:  # noqa: BLE001 — corrupt cache entry, treat as miss
            await self._redis.delete(key)
            return None

    async def put(
        self,
        request: NormalizedRequest,
        response: NormalizedResponse,
        complexity: Complexity,
    ) -> None:
        key = request_cache_key(request)
        await self._redis.set(
            key,
            response.model_dump_json(),
            ex=self._ttl.for_complexity(complexity),
        )
