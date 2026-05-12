"""Tests for /internal/retrieve and /internal/documents/by_ids — one-shot
retrieval + grader-side body_excerpt lookup. Reuses the embedder + dense
pgvector lookup; no agent loop.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent.tools.search_places import SearchPlaceHit
from app.db.models import SourceType
from app.routes import internal_retrieve


class _FakeRetriever:
    def __init__(self, hits: list[SearchPlaceHit]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._hits = hits

    async def search(self, *, session, embedder, query, near, radius_m, limit):
        self.calls.append({"query": query, "limit": limit})
        return self._hits


def _hit(doc_id: str = "wikipedia:X") -> SearchPlaceHit:
    return SearchPlaceHit(
        doc_id=doc_id,
        name="Test Place",
        source_type=SourceType.wikipedia,
        source_url=f"https://en.wikipedia.org/wiki/{doc_id}",
        lat=40.8,
        lon=-73.96,
        distance_m=None,
        score=0.6,
    )


class _BodyStub:
    """Returns canned body excerpts for a given set of doc_ids."""
    def __init__(self, bodies: dict[str, str]) -> None:
        self._bodies = bodies
        self.calls: list[list[str]] = []

    async def fetch(self, session, doc_ids: list[str], *, max_chars: int) -> dict[str, str]:
        self.calls.append(list(doc_ids))
        return {d: self._bodies.get(d, "")[:max_chars] for d in doc_ids}


def _app_with(retriever, bodies: _BodyStub | None = None):
    app = FastAPI()
    app.state.embedder = object()
    app.state.db_session_factory = lambda: _NoOpSession()
    app.include_router(internal_retrieve.router)
    app.state.retriever_for_internal = retriever
    app.state.body_excerpt_fetcher = bodies or _BodyStub({})
    return app


class _NoOpSession:
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return None
    async def execute(self, *a, **k): return None


def test_internal_retrieve_returns_top_k_with_body_excerpt():
    retriever = _FakeRetriever([_hit("wikipedia:A"), _hit("wikipedia:B")])
    bodies = _BodyStub({
        "wikipedia:A": "The Cathedral of Saint John the Divine was begun in 1892…",
        "wikipedia:B": "Riverside Church opened in 1930…",
    })
    app = _app_with(retriever, bodies)
    client = TestClient(app)
    resp = client.post("/internal/retrieve", json={"query": "cathedral", "top_k": 8})
    assert resp.status_code == 200
    body = resp.json()
    assert "results" in body
    assert len(body["results"]) == 2
    assert body["results"][0]["doc_id"] == "wikipedia:A"
    assert body["results"][0]["body_excerpt"].startswith("The Cathedral")
    assert body["results"][1]["body_excerpt"].startswith("Riverside")
    assert retriever.calls[0]["limit"] == 8


def test_internal_retrieve_requires_query():
    retriever = _FakeRetriever([])
    app = _app_with(retriever)
    client = TestClient(app)
    resp = client.post("/internal/retrieve", json={})
    assert resp.status_code == 422


def test_internal_documents_by_ids_returns_body_excerpts():
    bodies = _BodyStub({
        "wikipedia:Cathedral": "The Cathedral of Saint John the Divine…",
        "osm:way/123": "A small cafe at 110th Street.",
    })
    app = _app_with(_FakeRetriever([]), bodies)
    client = TestClient(app)
    resp = client.post(
        "/internal/documents/by_ids",
        json={"doc_ids": ["wikipedia:Cathedral", "osm:way/123", "missing:doc"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    docs = {d["doc_id"]: d for d in body["documents"]}
    assert docs["wikipedia:Cathedral"]["body_excerpt"].startswith("The Cathedral")
    assert docs["osm:way/123"]["body_excerpt"].startswith("A small cafe")
    assert docs["missing:doc"]["body_excerpt"] == ""  # absent → empty, not 404
    assert bodies.calls[0] == ["wikipedia:Cathedral", "osm:way/123", "missing:doc"]


def test_internal_documents_by_ids_rejects_empty():
    app = _app_with(_FakeRetriever([]))
    client = TestClient(app)
    resp = client.post("/internal/documents/by_ids", json={"doc_ids": []})
    assert resp.status_code == 422
