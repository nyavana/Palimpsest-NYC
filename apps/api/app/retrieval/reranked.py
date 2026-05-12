"""RerankedRetriever — second-stage cross-encoder over hybrid candidates.

Pipeline:
  1. Inner (hybrid) retriever produces top-N candidates (N=12 by default).
  2. We materialize a short text per hit (name + first ~80 chars of source URL
     slug as a cheap proxy for body).
  3. Cross-encoder scores (query, text) pairs; we reorder hits by predicted
     score and truncate to `limit`.

Why name-only text: the body for many places is empty (OSM rows have tags,
not prose). Name + slug is the most consistent signal available across
source types.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.agent.tools.search_places import SearchPlaceHit


class _InnerLike(Protocol):
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


class _RerankerLike(Protocol):
    def rerank(
        self,
        *,
        query: str,
        documents: list[str],
        top_k: int | None = None,
    ) -> list[str]: ...


def _text_for_rerank(hit: SearchPlaceHit) -> str:
    return hit.name


class RerankedRetriever:
    def __init__(
        self,
        *,
        inner: _InnerLike,
        reranker: _RerankerLike,
        top_n_for_rerank: int = 12,
    ) -> None:
        self._inner = inner
        self._reranker = reranker
        self._top_n = top_n_for_rerank

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
        candidates = await self._inner.search(
            session=session,
            embedder=embedder,
            query=query,
            near=near,
            radius_m=radius_m,
            limit=self._top_n,
        )
        if not candidates:
            return []
        texts = [_text_for_rerank(h) for h in candidates]
        by_text: dict[str, SearchPlaceHit] = {}
        for h in candidates:
            # If two hits collide on the rerank text (rare but possible for
            # near-duplicate names), keep the first one (highest hybrid rank).
            by_text.setdefault(_text_for_rerank(h), h)

        ordered_texts = self._reranker.rerank(query=query, documents=texts, top_k=limit)
        return [by_text[t] for t in ordered_texts]
