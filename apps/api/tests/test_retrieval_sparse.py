"""SparseRetriever — pg_trgm similarity over places.name (and documents.body
when JOIN'd). Returns the same SearchPlaceHit shape as DenseRetriever so the
hybrid layer can merge them with RRF.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.db.models import SourceType
from app.retrieval.sparse import SparseRetriever


class _FakeSession:
    def __init__(self, *, mappings_rows: list[dict[str, Any]]) -> None:
        self.executed: list[tuple[Any, dict[str, Any]]] = []
        self._rows = mappings_rows

    async def execute(self, sql: Any, params: dict[str, Any] | None = None) -> Any:
        self.executed.append((sql, params or {}))
        return _FakeResult(self._rows)


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> list[dict[str, Any]]:
        return self._rows


def _row(doc_id: str = "osm:way:1", similarity: float = 0.42) -> dict[str, Any]:
    return {
        "doc_id": doc_id,
        "name": "Some Place",
        "source_type": "osm",
        "source_url": f"https://example/{doc_id}",
        "lat": 40.8,
        "lon": -73.96,
        "similarity": similarity,
        "distance_m": None,
    }


async def test_sparse_retriever_returns_score_from_similarity() -> None:
    session = _FakeSession(
        mappings_rows=[_row("osm:way:1", 0.6), _row("osm:way:2", 0.4)]
    )
    retriever = SparseRetriever()
    hits = await retriever.search(
        session=session,
        embedder=None,
        query="flatiron",
        near=None,
        radius_m=None,
        limit=8,
    )
    assert len(hits) == 2
    assert hits[0].doc_id == "osm:way:1"
    assert hits[0].score == pytest.approx(0.6)
    assert hits[0].source_type == SourceType.osm


async def test_sparse_retriever_binds_query_text() -> None:
    session = _FakeSession(mappings_rows=[])
    retriever = SparseRetriever()
    await retriever.search(
        session=session,
        embedder=None,
        query="cathedral",
        near=None,
        radius_m=None,
        limit=10,
    )
    _, params = session.executed[0]
    assert params["q"] == "cathedral"
    assert params["limit"] == 10
