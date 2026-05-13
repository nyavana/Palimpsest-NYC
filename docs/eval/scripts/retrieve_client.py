"""HTTP client for ``/internal/retrieve``. Used by the naive-RAG baseline."""

from __future__ import annotations

from typing import Any

import httpx


class InternalRetrieveClient:
    """Thin wrapper around the Palimpsest API's ``/internal/retrieve`` endpoint.

    The endpoint returns ``{"results": [...]}``; this client unwraps the
    ``results`` list so callers don't need to repeat the unwrap.
    """

    def __init__(self, *, http_client: httpx.AsyncClient) -> None:
        self._http = http_client

    async def retrieve(self, *, query: str, top_k: int) -> list[dict[str, Any]]:
        resp = await self._http.post(
            "/internal/retrieve",
            json={"query": query, "top_k": top_k},
            timeout=30.0,
        )
        resp.raise_for_status()
        return list(resp.json().get("results") or [])
