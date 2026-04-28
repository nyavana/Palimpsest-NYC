"""Upsert helper tests.

These verify SQL shape (we use postgres-specific INSERT ... ON CONFLICT)
without a live database, by inspecting the compiled statement. Live-DB
round-trips live in tests/integration (gated by PALIMPSEST_INTEGRATION=1).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.dialects import postgresql

from app.db.models import SourceType
from app.ingest.records import DocumentRecord, PlaceRecord
from app.ingest.upsert import (
    build_document_upsert,
    build_place_upsert,
    canonicalize_embedding,
)


def _ts() -> datetime:
    return datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc)


def test_canonicalize_embedding_returns_none_for_no_embedder():
    assert canonicalize_embedding(None, "anything") is None


def test_canonicalize_embedding_returns_none_for_empty_text():
    class _Stub:
        def encode(self, texts: list[str]) -> list[list[float]]:
            raise AssertionError("should not be called")

    assert canonicalize_embedding(_Stub(), "") is None
    assert canonicalize_embedding(_Stub(), "   ") is None


def test_canonicalize_embedding_calls_embedder_once_per_text():
    calls: list[list[str]] = []

    class _Stub:
        def encode(self, texts: list[str]) -> list[list[float]]:
            calls.append(texts)
            return [[0.1] * 384]

    out = canonicalize_embedding(_Stub(), "hello world")
    assert out == [0.1] * 384
    assert calls == [["hello world"]]


# ── Place upsert SQL shape ──────────────────────────────────────────


def _place_record(**overrides: Any) -> PlaceRecord:
    base = {
        "doc_id": "wikipedia:Cathedral_of_Saint_John_the_Divine",
        "name": "Cathedral of St. John the Divine",
        "lat": 40.8038,
        "lon": -73.9619,
        "source_type": SourceType.wikipedia,
        "source_url": "https://en.wikipedia.org/wiki/Cathedral_of_Saint_John_the_Divine",
        "source_retrieved_at": _ts(),
        "license": "CC BY-SA 4.0",
        "properties": {"qid": "Q201219"},
        "embed_text": "Cathedral of St. John the Divine — Episcopal cathedral on Amsterdam Ave",
    }
    base.update(overrides)
    return PlaceRecord(**base)


def test_place_upsert_targets_places_table_with_on_conflict_doc_id():
    stmt = build_place_upsert(_place_record(), embedding=None)
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "INSERT INTO places" in sql
    assert "ON CONFLICT" in sql
    assert "doc_id" in sql


def test_place_upsert_writes_geom_via_postgis_helper():
    stmt = build_place_upsert(_place_record(), embedding=None)
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    # geom is materialized via ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography
    assert "ST_SetSRID" in sql or "ST_MakePoint" in sql
    assert "::geography" in sql or "geography" in sql.lower()


def test_place_upsert_carries_required_provenance_columns():
    stmt = build_place_upsert(_place_record(), embedding=None)
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    for col in (
        "doc_id",
        "name",
        "source_type",
        "source_url",
        "source_retrieved_at",
        "license",
        "properties",
    ):
        assert col in sql, f"missing column in upsert: {col}"


def test_place_upsert_with_embedding_writes_embedding_column():
    stmt = build_place_upsert(_place_record(), embedding=[0.1] * 384)
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "embedding" in sql


# ── Document upsert SQL shape ───────────────────────────────────────


def _document_record(**overrides: Any) -> DocumentRecord:
    base = {
        "doc_id": "wikipedia-doc:Cathedral_of_Saint_John_the_Divine",
        "place_doc_id": "wikipedia:Cathedral_of_Saint_John_the_Divine",
        "title": "Cathedral of St. John the Divine",
        "body": "The Cathedral Church of St. John the Divine is the cathedral of …",
        "source_type": SourceType.wikipedia,
        "source_url": "https://en.wikipedia.org/wiki/Cathedral_of_Saint_John_the_Divine",
        "source_retrieved_at": _ts(),
        "license": "CC BY-SA 4.0",
        "embed_text": "The Cathedral Church of St. John the Divine is …",
    }
    base.update(overrides)
    return DocumentRecord(**base)


def test_document_upsert_targets_documents_table_with_on_conflict_doc_id():
    stmt = build_document_upsert(_document_record(), embedding=None, place_id=42)
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "INSERT INTO documents" in sql
    assert "ON CONFLICT" in sql
    assert "doc_id" in sql


def test_document_upsert_uses_resolved_place_id_value():
    stmt = build_document_upsert(_document_record(), embedding=None, place_id=42)
    # The compiled bind params should include the resolved place_id.
    params = stmt.compile(dialect=postgresql.dialect()).params
    assert params.get("place_id") == 42


def test_document_upsert_allows_null_place_id():
    """Some Wikidata entries (events, abstract concepts) won't have a Place row."""
    stmt = build_document_upsert(_document_record(), embedding=None, place_id=None)
    params = stmt.compile(dialect=postgresql.dialect()).params
    assert params.get("place_id") is None
