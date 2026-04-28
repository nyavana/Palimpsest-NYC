"""Unit tests for the ORM model contract.

Tests verify column shapes, source_type enum constraint, the citation-shaped
provenance fields, and that the embedding column declares dim 384 to match
EMBEDDING_DIM. No live database required.
"""

from __future__ import annotations

from sqlalchemy import inspect

from app.db.models import Base, Document, Place, SourceType


def _columns(model) -> dict[str, object]:  # type: ignore[no-untyped-def]
    return {col.name: col for col in inspect(model).columns}


# ── source_type enum ────────────────────────────────────────────────


def test_source_type_v1_enum_locked() -> None:
    """Per data-ingest spec: V1 enum is exactly wikipedia | wikidata | osm."""
    assert {e.value for e in SourceType} == {"wikipedia", "wikidata", "osm"}


# ── Place ──────────────────────────────────────────────────────────


def test_place_carries_provenance_and_geometry() -> None:
    cols = _columns(Place)
    # Provenance fields shared with the citation contract — must match by name.
    for required in (
        "doc_id",
        "name",
        "geom",
        "source_type",
        "source_url",
        "source_retrieved_at",
        "license",
        "properties",
        "embedding",
        "created_at",
        "updated_at",
    ):
        assert required in cols, f"Place missing required column: {required}"

    # doc_id is unique (citation contract: globally unique within corpus)
    assert cols["doc_id"].unique is True
    # geom is NOT NULL (a place without a location is not useful)
    assert cols["geom"].nullable is False
    # source_url required by data-ingest "missing provenance blocks insert"
    assert cols["source_url"].nullable is False


def test_place_embedding_column_dim_matches_locked_v1_dim() -> None:
    embedding = _columns(Place)["embedding"]
    # pgvector Vector type stores its dim on `.dim` — locked to 384 in V1
    # to match BAAI/bge-small-en-v1.5 output.
    assert getattr(embedding.type, "dim", None) == 384


# ── Document ───────────────────────────────────────────────────────


def test_document_carries_provenance_and_optional_place_fk() -> None:
    cols = _columns(Document)
    for required in (
        "doc_id",
        "place_id",
        "title",
        "body",
        "source_type",
        "source_url",
        "source_retrieved_at",
        "license",
        "embedding",
        "created_at",
        "updated_at",
    ):
        assert required in cols, f"Document missing required column: {required}"

    # place_id is the FK to places.id — optional (a free-floating doc is allowed
    # in V1 because Wikidata tags may not always geocode).
    assert cols["place_id"].nullable is True
    # source_url required, doc_id unique (citation contract)
    assert cols["source_url"].nullable is False
    assert cols["doc_id"].unique is True


def test_document_embedding_column_dim_locked() -> None:
    embedding = _columns(Document)["embedding"]
    assert getattr(embedding.type, "dim", None) == 384


# ── Schema-of-record ────────────────────────────────────────────────


def test_models_share_a_single_base() -> None:
    """All ORM models must share one declarative Base for migrations to be
    a complete picture of the ORM-visible schema."""
    assert Place.metadata is Base.metadata
    assert Document.metadata is Base.metadata


def test_no_create_all_referenced_in_app_code() -> None:
    """Spec: schema MUST NOT be created via Base.metadata.create_all in app code.
    Migrations are the single source of truth. Look for actual call sites
    (`metadata.create_all(`) — docstring mentions don't count."""
    import pathlib
    import re

    api_app = pathlib.Path(__file__).resolve().parent.parent / "app"
    offenders: list[str] = []
    pattern = re.compile(r"metadata\.create_all\s*\(")
    for py in api_app.rglob("*.py"):
        text = py.read_text()
        # Strip docstrings/comments by removing triple-quoted blocks and #-lines
        stripped = re.sub(r'""".*?"""', "", text, flags=re.S)
        stripped = re.sub(r"'''.*?'''", "", stripped, flags=re.S)
        stripped = re.sub(r"#[^\n]*", "", stripped)
        if pattern.search(stripped):
            offenders.append(str(py.relative_to(api_app)))
    assert offenders == [], f"production code calls metadata.create_all: {offenders}"
