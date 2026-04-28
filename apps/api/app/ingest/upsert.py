"""Upsert helpers — write a `PlaceRecord` / `DocumentRecord` to the DB.

Idempotency: `INSERT ... ON CONFLICT (doc_id) DO UPDATE`. The natural key
is `doc_id`, which is source-stable (e.g., `wikipedia:Cathedral_…` is the
same string today and tomorrow), so re-runs update in place rather than
duplicating.

Embeddings: computed via the singleton `Embedder` on `app.state.embedder`
when `embed_text` is non-empty. Empty text → embedding stays NULL, which
is a valid row state — the embedding can be backfilled later.
"""

from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy import bindparam, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, Place
from app.ingest.records import DocumentRecord, PlaceRecord


class _EmbedderLike(Protocol):
    def encode(self, texts: list[str]) -> list[list[float]]: ...


# ── embedding helper ────────────────────────────────────────────────


def canonicalize_embedding(
    embedder: _EmbedderLike | None, text: str
) -> list[float] | None:
    """Return a 384-vector for `text`, or None if no embedder / empty text.

    Skipping when the embedder is missing keeps the upsert path callable from
    unit tests and from a worker that hasn't initialized the model yet.
    """
    if embedder is None or not text or not text.strip():
        return None
    return embedder.encode([text])[0]


# ── place upsert ────────────────────────────────────────────────────


def build_place_upsert(record: PlaceRecord, *, embedding: list[float] | None):
    """Compile an INSERT…ON CONFLICT statement for a Place row.

    Returns the statement so callers can either execute it or inspect the
    SQL in tests. Conflict target is `(doc_id)`; on conflict, all mutable
    fields are overwritten so re-ingestion picks up upstream edits.
    """
    point_4326 = func.ST_SetSRID(func.ST_MakePoint(record.lon, record.lat), 4326)
    geography = func.cast(point_4326, type_=Place.__table__.c.geom.type)

    values: dict[str, Any] = {
        "doc_id": record.doc_id,
        "name": record.name,
        "geom": geography,
        "source_type": record.source_type.value,
        "source_url": record.source_url,
        "source_retrieved_at": record.source_retrieved_at,
        "license": record.license,
        "properties": record.properties,
        "embedding": embedding,
    }

    stmt = pg_insert(Place).values(values)
    update_cols = {
        "name": stmt.excluded.name,
        "geom": stmt.excluded.geom,
        "source_type": stmt.excluded.source_type,
        "source_url": stmt.excluded.source_url,
        "source_retrieved_at": stmt.excluded.source_retrieved_at,
        "license": stmt.excluded.license,
        "properties": stmt.excluded.properties,
        # Don't clobber an existing embedding with NULL — only update when the
        # incoming value is non-NULL. COALESCE preserves the prior vector.
        "embedding": func.coalesce(stmt.excluded.embedding, Place.embedding),
    }
    return stmt.on_conflict_do_update(index_elements=["doc_id"], set_=update_cols)


async def upsert_place(
    session: AsyncSession,
    record: PlaceRecord,
    *,
    embedder: _EmbedderLike | None,
) -> int:
    """Upsert a Place and return its primary key id."""
    embedding = canonicalize_embedding(embedder, record.embed_text)
    stmt = build_place_upsert(record, embedding=embedding).returning(Place.id)
    result = await session.execute(stmt)
    return int(result.scalar_one())


# ── document upsert ─────────────────────────────────────────────────


def build_document_upsert(
    record: DocumentRecord,
    *,
    embedding: list[float] | None,
    place_id: int | None,
):
    """Compile an INSERT…ON CONFLICT statement for a Document row.

    `place_id` is resolved by the caller (typically from a prior place upsert
    or a lookup against `places.doc_id`).
    """
    values: dict[str, Any] = {
        "doc_id": record.doc_id,
        "place_id": bindparam("place_id", value=place_id),
        "title": record.title,
        "body": record.body,
        "source_type": record.source_type.value,
        "source_url": record.source_url,
        "source_retrieved_at": record.source_retrieved_at,
        "license": record.license,
        "embedding": embedding,
    }
    stmt = pg_insert(Document).values(values)
    update_cols = {
        "place_id": stmt.excluded.place_id,
        "title": stmt.excluded.title,
        "body": stmt.excluded.body,
        "source_type": stmt.excluded.source_type,
        "source_url": stmt.excluded.source_url,
        "source_retrieved_at": stmt.excluded.source_retrieved_at,
        "license": stmt.excluded.license,
        "embedding": func.coalesce(stmt.excluded.embedding, Document.embedding),
    }
    return stmt.on_conflict_do_update(index_elements=["doc_id"], set_=update_cols)


async def resolve_place_id(session: AsyncSession, place_doc_id: str) -> int | None:
    """Look up `places.id` for a given `places.doc_id` (or None if absent)."""
    result = await session.execute(
        select(Place.id).where(Place.doc_id == place_doc_id)
    )
    row = result.first()
    return int(row[0]) if row else None


async def upsert_document(
    session: AsyncSession,
    record: DocumentRecord,
    *,
    embedder: _EmbedderLike | None,
) -> int:
    """Upsert a Document, resolving `place_id` from `place_doc_id` if given."""
    place_id: int | None = None
    if record.place_doc_id is not None:
        place_id = await resolve_place_id(session, record.place_doc_id)
    embedding = canonicalize_embedding(embedder, record.embed_text)
    stmt = build_document_upsert(
        record, embedding=embedding, place_id=place_id
    ).returning(Document.id)
    result = await session.execute(stmt)
    return int(result.scalar_one())
