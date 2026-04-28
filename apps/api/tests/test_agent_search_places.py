"""search_places tool tests.

Heavy lifting (cosine ANN, ST_DWithin filter) is delegated to a small
helper that the test patches with a fake. We assert:
  - tool definition is accepted by the LLM `tools` parameter
  - JSON-Schema validation enforces required `query`, optional `near`/`radius_m`
  - results carry the citation-shape provenance (doc_id, source_url, source_type)
  - `near` without `radius_m` falls back to a sensible default
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.tools.base import ToolArgError, ToolExecutionContext
from app.agent.tools.search_places import (
    DEFAULT_LIMIT,
    DEFAULT_RADIUS_M,
    SearchPlaceHit,
    SearchPlacesTool,
)
from app.db.models import SourceType


class _FakeRetriever:
    """Stand-in for the postgres-backed retriever used by the tool."""

    def __init__(self, hits: list[SearchPlaceHit]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._hits = hits

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
        self.calls.append(
            {
                "query": query,
                "near": near,
                "radius_m": radius_m,
                "limit": limit,
            }
        )
        return self._hits


def _hit(**overrides: Any) -> SearchPlaceHit:
    base = {
        "doc_id": "wikipedia:Cathedral_of_Saint_John_the_Divine",
        "name": "Cathedral of St. John the Divine",
        "source_type": SourceType.wikipedia,
        "source_url": "https://en.wikipedia.org/wiki/Cathedral_of_Saint_John_the_Divine",
        "lat": 40.8038,
        "lon": -73.9619,
        "distance_m": None,
        "score": 0.74,
    }
    base.update(overrides)
    return SearchPlaceHit(**base)


# ── Tool definition shape ───────────────────────────────────────────


def test_tool_definition_metadata():
    tool = SearchPlacesTool(retriever=_FakeRetriever([]))
    definition = tool.definition()
    assert definition.name == "search_places"
    assert "search" in definition.description.lower()
    assert definition.parameters["type"] == "object"
    assert "query" in definition.parameters["required"]


def test_tool_definition_locks_required_query():
    tool = SearchPlacesTool(retriever=_FakeRetriever([]))
    schema = tool.definition().parameters
    assert schema["required"] == ["query"]
    # Optional params declared
    assert "near" in schema["properties"]
    assert "radius_m" in schema["properties"]
    assert "limit" in schema["properties"]


# ── Argument validation ─────────────────────────────────────────────


async def test_missing_query_raises():
    tool = SearchPlacesTool(retriever=_FakeRetriever([]))
    with pytest.raises(ToolArgError):
        await tool.run({}, ToolExecutionContext())


async def test_query_must_be_non_empty():
    tool = SearchPlacesTool(retriever=_FakeRetriever([]))
    with pytest.raises(ToolArgError):
        await tool.run({"query": ""}, ToolExecutionContext())


async def test_near_must_be_two_numbers():
    tool = SearchPlacesTool(retriever=_FakeRetriever([]))
    with pytest.raises(ToolArgError):
        await tool.run({"query": "x", "near": [40.8]}, ToolExecutionContext())


async def test_radius_m_lower_bound_enforced():
    tool = SearchPlacesTool(retriever=_FakeRetriever([]))
    with pytest.raises(ToolArgError):
        await tool.run(
            {"query": "x", "radius_m": 0}, ToolExecutionContext()
        )


# ── Default values ──────────────────────────────────────────────────


async def test_default_limit_applied_when_not_provided():
    retriever = _FakeRetriever([])
    tool = SearchPlacesTool(retriever=retriever)
    await tool.run({"query": "cathedral"}, ToolExecutionContext())
    assert retriever.calls[0]["limit"] == DEFAULT_LIMIT


async def test_default_radius_applied_when_near_provided_without_radius():
    retriever = _FakeRetriever([])
    tool = SearchPlacesTool(retriever=retriever)
    await tool.run(
        {"query": "x", "near": [40.8038, -73.9619]}, ToolExecutionContext()
    )
    assert retriever.calls[0]["radius_m"] == DEFAULT_RADIUS_M


# ── Result shape ────────────────────────────────────────────────────


async def test_result_carries_citation_shape_provenance():
    retriever = _FakeRetriever([_hit()])
    tool = SearchPlacesTool(retriever=retriever)
    out = await tool.run({"query": "cathedral"}, ToolExecutionContext())
    assert "results" in out
    assert isinstance(out["results"], list)
    hit = out["results"][0]
    # Citation contract field names — no rename
    for k in ("doc_id", "source_url", "source_type"):
        assert k in hit
    assert hit["source_type"] == "wikipedia"
    assert hit["doc_id"].startswith("wikipedia:")


async def test_result_round_trip_to_citation_shape():
    """A search hit must directly populate the verifier-required Citation
    fields with no transformation (data-ingest spec parity)."""
    retriever = _FakeRetriever([_hit(), _hit(doc_id="osm:node:1", source_type=SourceType.osm,
                                       source_url="https://www.openstreetmap.org/node/1",
                                       name="Random POI")])
    tool = SearchPlacesTool(retriever=retriever)
    out = await tool.run({"query": "anything"}, ToolExecutionContext())
    types = {r["source_type"] for r in out["results"]}
    assert types == {"wikipedia", "osm"}


async def test_empty_corpus_returns_empty_list_not_error():
    retriever = _FakeRetriever([])
    tool = SearchPlacesTool(retriever=retriever)
    out = await tool.run({"query": "obscure"}, ToolExecutionContext())
    assert out["results"] == []
