"""HTTP client for /internal/documents/by_ids — grader-side body enrichment.

Used by the palimpsest baseline AFTER the SSE stream finishes to attach
body_excerpts to every doc_id surfaced via tool_result frames. The agent
itself never sees these excerpts; this is purely grader context.
"""

from __future__ import annotations

import httpx


class DocumentClient:
    def __init__(self, *, http_client: httpx.AsyncClient) -> None:
        self._http = http_client

    async def by_ids(self, doc_ids: list[str]) -> dict[str, str]:
        if not doc_ids:
            return {}
        # The endpoint has a hard cap (64); split larger lists.
        out: dict[str, str] = {}
        for i in range(0, len(doc_ids), 64):
            batch = doc_ids[i : i + 64]
            resp = await self._http.post(
                "/internal/documents/by_ids",
                json={"doc_ids": batch},
                timeout=30.0,
            )
            resp.raise_for_status()
            for d in resp.json().get("documents") or []:
                out[d["doc_id"]] = d.get("body_excerpt") or ""
        return out
