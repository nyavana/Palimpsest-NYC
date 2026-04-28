"""Backend adapters for the LLM router.

Both adapters implement the same `complete(request) -> response` protocol
so the router can swap between them without branching on backend type.

- `OpenRouterAdapter`: calls OpenRouter's OpenAI-compatible endpoint.
- `LlamaCppAdapter`:   calls a local llama.cpp `llama-server` OpenAI-compatible
                       endpoint (typically bound on the Win11 host and
                       reachable at http://host.docker.internal:8080/v1).

Both adapters are thin — they translate ChatRequest/ChatResponse shapes to
and from provider JSON, issue an HTTP POST via httpx, and return without
policy decisions. All policy (routing, caching, circuit-breaker, fallback)
lives in `app.llm.router`.
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol, runtime_checkable

import httpx

from app.llm.models import (
    Message,
    NormalizedRequest,
    NormalizedResponse,
    ToolCall,
    ToolDefinition,
    Usage,
)

# ── Cost table (USD per 1K tokens) ───────────────────────────────────
#
# Values are approximate and will be refined as the final report compares
# them against OpenRouter-reported `cost` fields. Local calls are assigned
# a nominal cost of 0 since the user pays only electricity.
_COST_TABLE: dict[str, tuple[float, float]] = {
    "openai/gpt-5.4": (0.010, 0.030),
    "openai/gpt-5.4-mini": (0.0015, 0.006),
    "google/gemma-4-26B-A4B-it": (0.0, 0.0),
}


def _estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    prompt_rate, completion_rate = _COST_TABLE.get(model, (0.0, 0.0))
    return (prompt_tokens / 1000.0) * prompt_rate + (completion_tokens / 1000.0) * completion_rate


# ── Protocol ─────────────────────────────────────────────────────────


@runtime_checkable
class LLMAdapter(Protocol):
    """Protocol every backend adapter implements."""

    name: str
    """Short identifier used in telemetry: `local` or `openrouter`."""

    async def complete(self, request: NormalizedRequest) -> NormalizedResponse:
        ...

    async def aclose(self) -> None:
        ...


# ── JSON translation helpers ─────────────────────────────────────────


def _message_to_dict(msg: Message) -> dict[str, Any]:
    out: dict[str, Any] = {"role": msg.role}
    if msg.content is not None:
        out["content"] = msg.content
    if msg.name is not None:
        out["name"] = msg.name
    if msg.tool_call_id is not None:
        out["tool_call_id"] = msg.tool_call_id
    if msg.tool_calls:
        out["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": _dumps_json(tc.arguments)},
            }
            for tc in msg.tool_calls
        ]
    return out


def _tool_to_dict(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _dumps_json(obj: Any) -> str:
    import json

    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def _loads_json(raw: str | None) -> dict[str, Any]:
    import json

    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}


def _build_payload(request: NormalizedRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": [_message_to_dict(m) for m in request.messages],
        "temperature": request.temperature,
    }
    if request.max_tokens is not None:
        payload["max_tokens"] = request.max_tokens
    if request.tools:
        payload["tools"] = [_tool_to_dict(t) for t in request.tools]
        payload["tool_choice"] = "auto"
    if request.response_format == "json":
        payload["response_format"] = {"type": "json_object"}
    return payload


def _parse_response(payload: dict[str, Any], default_model: str) -> NormalizedResponse:
    choice = (payload.get("choices") or [{}])[0]
    message = choice.get("message") or {}

    tool_calls: list[ToolCall] = []
    for raw_tc in message.get("tool_calls") or []:
        fn = raw_tc.get("function") or {}
        tool_calls.append(
            ToolCall(
                id=raw_tc.get("id", uuid.uuid4().hex),
                name=fn.get("name", ""),
                arguments=_loads_json(fn.get("arguments")),
            )
        )

    usage = payload.get("usage") or {}
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))
    model = payload.get("model") or default_model
    cost = float(usage.get("cost") or _estimate_cost_usd(model, prompt_tokens, completion_tokens))

    return NormalizedResponse(
        id=str(payload.get("id", uuid.uuid4().hex)),
        content=message.get("content"),
        tool_calls=tool_calls,
        usage=Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost,
        ),
        model=model,
    )


# ── OpenRouter adapter ───────────────────────────────────────────────


class OpenRouterAdapter:
    """Cloud backend. Talks OpenAI-compatible JSON against OpenRouter."""

    name = "openrouter"

    def __init__(self, *, base_url: str, api_key: str, timeout_s: float) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_s,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://palimpsest.local",
                "X-Title": "Palimpsest NYC",
            },
        )

    async def complete(self, request: NormalizedRequest) -> NormalizedResponse:
        payload = _build_payload(request)
        resp = await self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        return _parse_response(resp.json(), default_model=request.model)

    async def aclose(self) -> None:
        await self._client.aclose()


# ── llama.cpp adapter (local Gemma-4) ────────────────────────────────


class LlamaCppAdapter:
    """Local backend. Targets `llama-server`'s OpenAI-compatible endpoint."""

    name = "local"

    def __init__(self, *, base_url: str, api_key: str, timeout_s: float) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_s,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    async def complete(self, request: NormalizedRequest) -> NormalizedResponse:
        payload = _build_payload(request)
        # llama.cpp ignores `model` but still echoes it back; keep it for parity.
        resp = await self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        return _parse_response(resp.json(), default_model=request.model)

    async def aclose(self) -> None:
        await self._client.aclose()
