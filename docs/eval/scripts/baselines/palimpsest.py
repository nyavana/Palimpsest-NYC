"""Palimpsest baseline.

Drives the live SSE route via a POST+JSON client (sse_client.stream_agent_ask),
captures every `tool_result` frame, flattens search_places.results and
plan_walk.discovered_stops into a `retrieved_docs` list, then post-hoc enriches
each doc with a body_excerpt via /internal/documents/by_ids so the LLM-judge
has the document text needed to grade CCR/HR/FA.

Why not import _run_one from docs/eval/scripts/run_eval.py?
  - That script still uses GET ?q=… (the legacy V1.0 transport). The live
    route is POST with a JSON body since V1.1, so a direct import would 405
    every call.
  - That script collects events but never extracts tool_result payloads, so
    retrieved_docs would be empty — the grader's CCR/HR rubric scores empty
    retrieved_docs as 0 / 1.0 respectively, which would penalize palimpsest
    by construction.

If/when run_eval.py is refactored to POST and to expose tool_result data, this
module can be slimmed back to a normalizer; for now it owns the SSE call.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from docs.eval.scripts.sse_client import stream_agent_ask


# Tool names whose `result.results` (or `result.discovered_stops`) list
# corresponds to the citation-shape hits the agent "saw" on that turn.
_FLATTENABLE_TOOLS = ("search_places", "plan_walk")


def flatten_retrieved_docs(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collect every doc_id-bearing entry from tool_result frames.

    Dedupes by doc_id (first-seen wins, so the earliest score/score_origin is
    preserved). The shape matches /internal/retrieve's RetrieveResult except
    `body_excerpt` is filled in afterwards by run_palimpsest().
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for fr in frames:
        if fr.get("event") != "tool_result":
            continue
        data = fr.get("data") or {}
        if data.get("name") not in _FLATTENABLE_TOOLS:
            continue
        result = data.get("result") or {}
        for key in ("results", "discovered_stops", "stops"):
            for hit in result.get(key) or []:
                doc_id = hit.get("doc_id")
                if not doc_id or doc_id in seen:
                    continue
                seen.add(doc_id)
                out.append({
                    "doc_id": doc_id,
                    "name": hit.get("name"),
                    "source_type": hit.get("source_type"),
                    "source_url": hit.get("source_url"),
                    "lat": hit.get("lat"),
                    "lon": hit.get("lon"),
                    "score": hit.get("score"),
                    "body_excerpt": "",  # filled by enrichment step
                    "from_tool": data.get("name"),
                })
    return out


def _terminal_result(frames: list[dict[str, Any]]) -> dict[str, Any] | None:
    for fr in reversed(frames):
        if fr.get("event") == "done":
            return ((fr.get("data") or {}).get("result")) or {}
    return None


def normalize_palimpsest_row(
    *,
    frames: list[dict[str, Any]],
    question: str,
    client_latency_s: float,
    system_name: str,
    retrieval_mode: str,
    body_excerpts: dict[str, str],
    error: str | None,
) -> dict[str, Any]:
    result = _terminal_result(frames) or {}
    retrieved = flatten_retrieved_docs(frames)
    for d in retrieved:
        d["body_excerpt"] = body_excerpts.get(d["doc_id"], "")
    tool_calls = [
        {"name": fr["data"].get("name"), "args": fr["data"].get("args")}
        for fr in frames
        if fr.get("event") == "tool_call"
    ]
    warnings = [
        fr["data"].get("message")
        for fr in frames
        if fr.get("event") == "warning" and fr["data"].get("message")
    ]
    return {
        "system": system_name,
        "retrieval_mode": retrieval_mode,
        "question": question,
        "narration": result.get("narration") or "",
        "citations": list(result.get("citations") or []),
        "retrieved_docs": retrieved,
        "llm_cost_usd": 0.0,  # filled by aggregate.py from /internal/metrics delta
        "llm_prompt_tokens": 0,
        "llm_completion_tokens": 0,
        "latency_s": float(client_latency_s),
        "server_duration_s": result.get("duration_s"),
        "turns": result.get("turns"),
        "tool_calls": tool_calls,
        "warnings": warnings,
        "verified": result.get("verified"),
        "verifier_warning": result.get("warning"),
        "error": error,
    }


async def run_palimpsest(
    *,
    question: str,
    api_http_client: httpx.AsyncClient,
    doc_client: Any,  # DocumentClient (or a fake with `by_ids(doc_ids)`)
    system_name: str,
    retrieval_mode: str,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """One call → one normalized eval row, including body_excerpt enrichment."""
    started_at = time.perf_counter()
    frames: list[dict[str, Any]] = []
    error: str | None = None
    try:
        async for fr in stream_agent_ask(api_http_client, question=question, history=history or []):
            frames.append(fr)
            if fr["event"] == "done":
                break
    except httpx.HTTPError as exc:
        error = f"{type(exc).__name__}: {exc}"
    elapsed = round(time.perf_counter() - started_at, 3)

    # Enrich every captured doc_id with its body_excerpt for the grader.
    doc_ids = [d["doc_id"] for d in flatten_retrieved_docs(frames)]
    body_excerpts: dict[str, str] = {}
    if doc_ids and error is None:
        try:
            body_excerpts = await doc_client.by_ids(doc_ids)
        except Exception as exc:  # noqa: BLE001 — enrichment failure is non-fatal
            error = f"enrichment_failed: {type(exc).__name__}: {exc}"

    return normalize_palimpsest_row(
        frames=frames, question=question, client_latency_s=elapsed,
        system_name=system_name, retrieval_mode=retrieval_mode,
        body_excerpts=body_excerpts, error=error,
    )
