"""RerankedRetriever — wraps a hybrid retriever and applies the reranker."""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.tools.search_places import SearchPlaceHit
from app.db.models import SourceType
from app.retrieval.reranked import RerankedRetriever


def _hit(doc_id: str, name: str | None = None) -> SearchPlaceHit:
    return SearchPlaceHit(
        doc_id=doc_id,
        name=name or doc_id,
        source_type=SourceType.wikipedia,
        source_url=f"https://example/{doc_id}",
        lat=40.8,
        lon=-73.96,
        distance_m=None,
        score=0.5,
    )


class _StubInner:
    def __init__(self, hits: list[SearchPlaceHit]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._hits = hits

    async def search(self, **kwargs: Any) -> list[SearchPlaceHit]:
        self.calls.append(kwargs)
        return self._hits


class _StubReranker:
    """Returns documents in reverse order — last input ranks first."""

    def rerank(
        self,
        *,
        query: str,
        documents: list[str],
        top_k: int | None = None,
    ) -> list[str]:
        ordered = list(reversed(documents))
        return ordered if top_k is None else ordered[:top_k]


async def test_reranked_reorders_inner_hits() -> None:
    inner = _StubInner([_hit("A", "Aaa"), _hit("B", "Bbb"), _hit("C", "Ccc")])
    rr = RerankedRetriever(inner=inner, reranker=_StubReranker(), top_n_for_rerank=10)
    hits = await rr.search(
        session=None,
        embedder=None,
        query="q",
        near=None,
        radius_m=None,
        limit=5,
    )
    # Reranker reverses → C, B, A
    assert [h.doc_id for h in hits] == ["C", "B", "A"]


async def test_reranked_respects_limit() -> None:
    inner = _StubInner([_hit(f"D{i}") for i in range(10)])
    rr = RerankedRetriever(inner=inner, reranker=_StubReranker(), top_n_for_rerank=10)
    hits = await rr.search(
        session=None,
        embedder=None,
        query="q",
        near=None,
        radius_m=None,
        limit=3,
    )
    assert len(hits) == 3


async def test_reranked_returns_empty_when_inner_empty() -> None:
    inner = _StubInner([])
    rr = RerankedRetriever(inner=inner, reranker=_StubReranker(), top_n_for_rerank=10)
    hits = await rr.search(
        session=None,
        embedder=None,
        query="q",
        near=None,
        radius_m=None,
        limit=5,
    )
    assert hits == []


async def test_reranked_calls_inner_with_top_n() -> None:
    """Inner retriever should be asked for top_n_for_rerank candidates, not `limit`."""
    inner = _StubInner([_hit(f"E{i}") for i in range(12)])
    rr = RerankedRetriever(inner=inner, reranker=_StubReranker(), top_n_for_rerank=12)
    await rr.search(
        session=None,
        embedder=None,
        query="q",
        near=None,
        radius_m=None,
        limit=5,
    )
    assert inner.calls[0]["limit"] == 12
