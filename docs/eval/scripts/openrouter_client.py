"""Minimal OpenRouter chat client (httpx). Uniform ``chat()`` API for baselines + judge.

Satisfies the ``ChatClient`` Protocol declared in
``docs/eval/scripts/baselines/vanilla_llm.py`` (used by the vanilla baseline,
the naive-RAG baseline, and the LLM judge).
"""

from __future__ import annotations

from typing import Any

import httpx


def _extract_cost_usd(usage: dict[str, Any]) -> float:
    """Return the per-call cost in USD from an OpenRouter ``usage`` block.

    OpenRouter currently documents the field as ``cost`` (see the Usage
    Accounting cookbook), but historical responses and OpenAI passthrough
    routes have used ``total_cost``. Free-tier providers report neither.

    We prefer ``cost`` (the documented canonical field), fall back to
    ``total_cost``, and finally return ``0.0`` so the row schema's numeric
    contract stays intact. Any non-numeric value is treated as missing.
    """

    for key in ("cost", "total_cost"):
        raw = usage.get(key)
        if raw is None:
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return 0.0


class OpenRouterChatClient:
    """Thin wrapper around OpenRouter's ``/chat/completions`` endpoint.

    The constructor accepts an externally-managed ``httpx.AsyncClient`` so the
    orchestrator can pool connections / set a sane ``base_url`` once and pass
    the same client to many baselines + the judge.
    """

    def __init__(self, *, http_client: httpx.AsyncClient, api_key: str) -> None:
        self._http = http_client
        self._api_key = api_key

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        resp = await self._http.post(
            "/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json=payload,
            timeout=120.0,
        )
        resp.raise_for_status()
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        usage = data.get("usage") or {}
        return {
            "content": (choice.get("message") or {}).get("content") or "",
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "cost_usd": _extract_cost_usd(usage),
        }
