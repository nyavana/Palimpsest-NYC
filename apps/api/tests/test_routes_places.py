from __future__ import annotations

from typing import Any

from app.routes.places import router as places_router
from fastapi import FastAPI
from fastapi.testclient import TestClient


class _FakeEmbedder:
    dim = 3

    def encode(self, texts: list[str]) -> list[list[float]]:
        assert texts == ["ramen"]
        return [[0.1, 0.2, 0.3]]


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeSession:
    async def execute(self, _sql: Any, params: dict[str, Any]) -> _FakeResult:
        assert params["limit"] == 3
        assert params["query_lower"] == "ramen"
        assert params["lat"] == 40.8075
        assert params["lon"] == -73.9626
        return _FakeResult(
            [
                {
                    "doc_id": "osm:node:1",
                    "name": "Campus Ramen",
                    "source_type": "osm",
                    "source_url": "https://www.openstreetmap.org/node/1",
                    "lat": 40.8072,
                    "lon": -73.9641,
                    "distance_m": 220.4,
                    "amenity": "restaurant",
                    "cuisine": "ramen;japanese",
                    "tags": {"amenity": "restaurant", "cuisine": "ramen;japanese"},
                    "distance": 0.12,
                }
            ]
        )


class _FakeSessionCM:
    async def __aenter__(self) -> _FakeSession:
        return _FakeSession()

    async def __aexit__(self, *args: Any) -> None:
        return None


def _build_app() -> FastAPI:
    app = FastAPI()
    app.state.db_session_factory = _FakeSessionCM
    app.state.embedder = _FakeEmbedder()
    app.include_router(places_router)
    return app


def test_food_discovery_returns_structured_candidates() -> None:
    app = _build_app()

    with TestClient(app) as client:
        resp = client.post(
            "/food/discover",
            json={
                "query": "ramen",
                "near": [40.8075, -73.9626],
                "radius_m": 900,
                "limit": 3,
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["query"] == "ramen"
    assert len(body["results"]) == 1
    candidate = body["results"][0]
    assert candidate["doc_id"] == "osm:node:1"
    assert candidate["name"] == "Campus Ramen"
    assert candidate["cuisine"] == "ramen;japanese"
    assert candidate["distance_m"] == 220.4
    assert candidate["why"] == "Good match for ramen, japanese - 220 m away"
