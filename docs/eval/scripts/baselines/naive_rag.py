"""Naive-RAG baseline — one-shot retrieval, one-shot generate, no agent loop.

Embeds query → top-K retrieval via /internal/retrieve → stuffs docs into the
prompt → single OpenRouter call. The comparison vs Palimpsest isolates the
contribution of the agent loop + citation verifier specifically.

Public API:
    async def run_naive_rag(*, question, model, chat_client, retrieve_client,
                            top_k, temperature) -> dict
"""

from __future__ import annotations

import json
import time
from typing import Any, Protocol

from docs.eval.scripts.baselines._json_utils import strip_json_fences

_SYSTEM_PROMPT = """You are a Manhattan walking-tour narrator. The user's question is followed by a list
of retrieved documents. Use ONLY information from those documents in your narration. Cite each
factual claim with one of the retrieved doc_ids.

Return ONLY one JSON object — no prose before or after, no markdown code fences,
no commentary. The first character of your reply MUST be '{' and the last MUST
be '}'. Use exactly this shape:

{
  "narration": "<your narration text>",
  "citations": [
    {
      "doc_id":      "<one of the retrieved doc_ids>",
      "source_url":  "<the matching source_url from the retrieval list>",
      "source_type": "<the matching source_type>",
      "span":        "<short span supporting the claim>"
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


class RetrieveClient(Protocol):
    async def retrieve(self, *, query: str, top_k: int) -> list[dict[str, Any]]: ...


def _format_retrievals(results: list[dict[str, Any]]) -> str:
    lines = ["Retrieved documents:"]
    for r in results:
        lines.append(
            f"- doc_id={r['doc_id']} "
            f"source_type={r.get('source_type', '?')} "
            f"source_url={r.get('source_url', '?')} "
            f"name={r.get('name', '?')!r} "
            f"score={r.get('score', 0):.3f}"
        )
    return "\n".join(lines)


async def run_naive_rag(
    *,
    question: str,
    model: str,
    chat_client: ChatClient,
    retrieve_client: RetrieveClient,
    top_k: int = 8,
    temperature: float = 0.0,
) -> dict[str, Any]:
    started = time.perf_counter()
    error: str | None = None
    narration = ""
    citations: list[dict[str, Any]] = []
    retrieved: list[dict[str, Any]] = []
    response: dict[str, Any] = {}

    try:
        retrieved = await retrieve_client.retrieve(query=question, top_k=top_k)
        user_msg = f"{question}\n\n{_format_retrievals(retrieved)}"
        response = await chat_client.chat(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
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
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"

    elapsed = time.perf_counter() - started

    return {
        "system": "naive_rag",
        "question": question,
        "narration": narration,
        "citations": citations,
        "retrieved_docs": retrieved,
        "llm_cost_usd": float(response.get("cost_usd") or 0.0),
        "llm_prompt_tokens": int(response.get("prompt_tokens") or 0),
        "llm_completion_tokens": int(response.get("completion_tokens") or 0),
        "latency_s": round(elapsed, 3),
        "error": error,
    }
