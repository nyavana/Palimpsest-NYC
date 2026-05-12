"""Minimal OpenRouter chat client (httpx). Uniform ``chat()`` API for baselines + judge.

Satisfies the ``ChatClient`` Protocol declared in
``docs/eval/scripts/baselines/vanilla_llm.py`` (used by the vanilla baseline,
the naive-RAG baseline, and the LLM judge).
"""

from __future__ import annotations

from typing import Any

import httpx


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
    ) -> dict[str, Any]:
        resp = await self._http.post(
            "/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={"model": model, "messages": messages, "temperature": temperature},
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
            "cost_usd": float(usage.get("total_cost") or 0.0),
        }
