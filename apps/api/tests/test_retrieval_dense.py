"""DenseRetriever — pgvector cosine ANN. Same behavior as the previous
inline `PostgresRetriever` in search_places.py.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.db.models import SourceType
from app.retrieval.dense import DenseRetriever


class _FakeSession:
    def __init__(self, *, mappings_rows: list[dict[str, Any]]) -> None:
        self.executed: list[tuple[Any, dict[str, Any]]] = []
        self._rows = mappings_rows

    async def execute(self, sql, params=None):
        self.executed.append((sql, params or {}))
        return _FakeResult(self._rows)


class _FakeResult:
    def __init__(self, rows): self._rows = rows
    def mappings(self): return self._rows


class _FakeEmbedder:
    def __init__(self): self.dim = 3
    def encode(self, texts): return [[0.1, 0.2, 0.3] for _ in texts]


def _row(doc_id="wikipedia:A", distance=0.4, distance_m=None):
    return {
        "doc_id": doc_id,
        "name": doc_id,
        "source_type": "wikipedia",
        "source_url": f"https://example/{doc_id}",
        "lat": 40.8,
        "lon": -73.96,
        "distance_m": distance_m,
        "distance": distance,
    }


async def test_dense_retriever_returns_hits_with_score():
    session = _FakeSession(mappings_rows=[_row("wikipedia:A", 0.2), _row("wikipedia:B", 0.4)])
    embedder = _FakeEmbedder()
    retriever = DenseRetriever()
    hits = await retriever.search(
        session=session, embedder=embedder,
        query="cathedral", near=None, radius_m=None, limit=8,
    )
    assert len(hits) == 2
    assert hits[0].doc_id == "wikipedia:A"
    # score = 1 - distance / 2, clamped to [0, 1]
    assert hits[0].score == pytest.approx(1.0 - 0.2 / 2.0)
    assert hits[1].score == pytest.approx(1.0 - 0.4 / 2.0)
    assert hits[0].source_type == SourceType.wikipedia


async def test_dense_retriever_passes_spatial_params():
    session = _FakeSession(mappings_rows=[])
    embedder = _FakeEmbedder()
    retriever = DenseRetriever()
    await retriever.search(
        session=session, embedder=embedder,
        query="x", near=(40.8, -73.96), radius_m=500, limit=5,
    )
    _, params = session.executed[0]
    assert params["lat"] == 40.8
    assert params["lon"] == -73.96
    assert params["radius_m"] == 500
    assert params["limit"] == 5
