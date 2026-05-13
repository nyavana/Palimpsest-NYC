"""Vanilla-LLM baseline — one-shot OpenRouter call, no retrieval.

Asked to produce the same JSON shape as Palimpsest (narration + citations).
Whatever the model fabricates goes in as-is; that is the point.

Public API:
    async def run_vanilla(*, question, model, chat_client, temperature) -> dict
"""

from __future__ import annotations

import json
import time
from typing import Any, Protocol

from docs.eval.scripts.baselines._json_utils import strip_json_fences

_SYSTEM_PROMPT = """You are a Manhattan walking-tour narrator. Answer the user's question with a short narration
(2-4 sentences) about real places in Manhattan, and provide citations supporting your claims.

Return ONLY one JSON object — no prose before or after, no markdown code fences,
no commentary. The first character of your reply MUST be '{' and the last MUST
be '}'. Use exactly this shape:

{
  "narration": "<your narration text>",
  "citations": [
    {
      "doc_id":      "<stable id e.g. 'wikipedia:Foo_Bar' or 'osm:way:1234'>",
      "source_url":  "<url>",
      "source_type": "wikipedia" | "wikidata" | "osm",
      "span":        "<short quoted span from the source supporting the claim>"
    }
  ]
}
"""


class ChatClient(Protocol):
    async def chat(
        self,
        *,
        model: str,
        messages: list[dict],
        temperature: float,
        response_format: dict[str, Any] | None = ...,
    ) -> dict[str, Any]: ...


async def run_vanilla(
    *,
    question: str,
    model: str,
    chat_client: ChatClient,
    temperature: float = 0.0,
) -> dict[str, Any]:
    started = time.perf_counter()
    error: str | None = None
    narration = ""
    citations: list[dict[str, Any]] = []
    response: dict[str, Any] = {}

    try:
        response = await chat_client.chat(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        content = strip_json_fences(response.get("content") or "")
        parsed = json.loads(content)
        narration = str(parsed.get("narration") or "")
        raw_citations = parsed.get("citations") or []
        if isinstance(raw_citations, list):
            citations = [c for c in raw_citations if isinstance(c, dict)]
    except json.JSONDecodeError as exc:
        error = f"JSONDecodeError: {exc}"
    except Exception as exc:  # noqa: BLE001 - surfaces all baseline failures
        error = f"{type(exc).__name__}: {exc}"

    elapsed = time.perf_counter() - started

    return {
        "system": "vanilla",
        "question": question,
        "narration": narration,
        "citations": citations,
        "retrieved_docs": [],
        "llm_cost_usd": float(response.get("cost_usd") or 0.0),
        "llm_prompt_tokens": int(response.get("prompt_tokens") or 0),
        "llm_completion_tokens": int(response.get("completion_tokens") or 0),
        "latency_s": round(elapsed, 3),
        "error": error,
    }
