"""HybridRetriever fan-out + RRF merge."""

from __future__ import annotations

from typing import Any

from app.agent.tools.search_places import SearchPlaceHit
from app.db.models import SourceType
from app.retrieval.hybrid import HybridRetriever


class _StubRetriever:
    def __init__(self, hits: list[SearchPlaceHit]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._hits = hits

    async def search(self, *, session, embedder, query, near, radius_m, limit):
        self.calls.append({"query": query, "limit": limit})
        return self._hits


def _hit(doc_id: str, score: float = 0.5) -> SearchPlaceHit:
    return SearchPlaceHit(
        doc_id=doc_id,
        name=doc_id,
        source_type=SourceType.wikipedia,
        source_url=f"https://example/{doc_id}",
        lat=40.8,
        lon=-73.96,
        distance_m=None,
        score=score,
    )


async def test_hybrid_returns_union_of_dense_and_sparse() -> None:
    dense = _StubRetriever([_hit("A", 0.9), _hit("B", 0.7)])
    sparse = _StubRetriever([_hit("B", 0.6), _hit("C", 0.5)])
    hybrid = HybridRetriever(dense=dense, sparse=sparse, rrf_k=60)

    hits = await hybrid.search(
        session=None,
        embedder=None,
        query="x",
        near=None,
        radius_m=None,
        limit=10,
    )
    doc_ids = [h.doc_id for h in hits]
    assert set(doc_ids) == {"A", "B", "C"}
    # B is in both → ranks first
    assert doc_ids[0] == "B"


async def test_hybrid_respects_limit() -> None:
    dense = _StubRetriever([_hit(f"D{i}") for i in range(20)])
    sparse = _StubRetriever([_hit(f"S{i}") for i in range(20)])
    hybrid = HybridRetriever(dense=dense, sparse=sparse, rrf_k=60)

    hits = await hybrid.search(
        session=None,
        embedder=None,
        query="x",
        near=None,
        radius_m=None,
        limit=5,
    )
    assert len(hits) == 5


async def test_hybrid_fans_out_with_larger_internal_limit() -> None:
    """Each branch should fetch more than `limit` so RRF has room to swap."""
    dense = _StubRetriever([_hit("A")])
    sparse = _StubRetriever([_hit("B")])
    hybrid = HybridRetriever(dense=dense, sparse=sparse, rrf_k=60, fanout_multiplier=3)

    await hybrid.search(
        session=None,
        embedder=None,
        query="x",
        near=None,
        radius_m=None,
        limit=5,
    )
    assert dense.calls[0]["limit"] == 15
    assert sparse.calls[0]["limit"] == 15
