"""HybridRetriever — fan out to dense + sparse in parallel, fuse with RRF.

Both branches return the same SearchPlaceHit shape. We index them by doc_id
for the fusion step and reconstruct the hit list in fused order. Internal
fan-out is larger than the caller's `limit` so RRF has room to swap items.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from app.agent.tools.search_places import SearchPlaceHit
from app.retrieval.fusion import reciprocal_rank_fusion


class _RetrieverLike(Protocol):
    async def search(
        self,
        *,
        session: Any,
        embedder: Any,
        query: str,
        near: tuple[float, float] | None,
        radius_m: int | None,
        limit: int,
    ) -> list[SearchPlaceHit]: ...


class HybridRetriever:
    """Fan-out to dense + sparse retrievers, fuse results with Reciprocal Rank Fusion.

    The dense branch is whatever concrete retriever the caller wires in. In V1
    that is `app.agent.tools.search_places.PostgresRetriever`; once Task 4.1
    extracts a `DenseRetriever` in `app/retrieval/dense.py`, swapping that in is
    a one-line wiring change at the call site — `HybridRetriever` itself depends
    only on the duck-typed `.search(...)` protocol.
    """

    def __init__(
        self,
        *,
        dense: _RetrieverLike,
        sparse: _RetrieverLike,
        rrf_k: int = 60,
        fanout_multiplier: int = 3,
    ) -> None:
        self._dense = dense
        self._sparse = sparse
        self._rrf_k = rrf_k
        self._fanout = fanout_multiplier

    async def search(
        self,
        *,
        session: Any,
        embedder: Any,
        query: str,
        near: tuple[float, float] | None,
        radius_m: int | None,
        limit: int,
    ) -> list[SearchPlaceHit]:
        branch_limit = limit * self._fanout
        dense_hits, sparse_hits = await asyncio.gather(
            self._dense.search(
                session=session,
                embedder=embedder,
                query=query,
                near=near,
                radius_m=radius_m,
                limit=branch_limit,
            ),
            self._sparse.search(
                session=session,
                embedder=embedder,
                query=query,
                near=near,
                radius_m=radius_m,
                limit=branch_limit,
            ),
        )

        # Build doc_id → hit lookup. Prefer dense's hit when both have it
        # (dense carries the cosine score the LLM is used to; sparse score
        # is a different signal).
        lookup: dict[str, SearchPlaceHit] = {}
        for h in sparse_hits:
            lookup[h.doc_id] = h
        for h in dense_hits:
            lookup[h.doc_id] = h

        fused_ids = reciprocal_rank_fusion(
            [[h.doc_id for h in dense_hits], [h.doc_id for h in sparse_hits]],
            k=self._rrf_k,
        )
        return [lookup[doc_id] for doc_id in fused_ids[:limit]]
