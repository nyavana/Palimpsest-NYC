"""SQLAlchemy ORM models — read-only mirrors of `migrations/*.sql`.

Per `db-migrations` spec, schema is owned by SQL files. These ORM models
exist for query construction and type-safe access; they MUST NOT be used
to create or mutate the schema (no `Base.metadata.create_all` in
production code paths).

Provenance fields (`doc_id`, `source_type`, `source_url`,
`source_retrieved_at`, `license`) match the citation contract in
`agent-tools/spec.md` so a row's provenance becomes its citation with no
field renaming.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from geoalchemy2 import Geography
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Locked in `swap-llm-tiers-and-lock-mvp-decisions`. The ORM column dim MUST
# track `EMBEDDING_DIM`; changing the model requires a new migration that
# drops and recreates the column at the new dim.
EMBEDDING_DIM = 384


class SourceType(str, enum.Enum):
    """V1 source enum. Adding values requires both a spec change and a
    migration that runs `ALTER TYPE source_type_enum ADD VALUE ...`."""

    wikipedia = "wikipedia"
    wikidata = "wikidata"
    osm = "osm"


class Base(DeclarativeBase):
    """Single declarative base for all ORM models."""


class Place(Base):
    __tablename__ = "places"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    doc_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    geom: Mapped[Any] = mapped_column(
        Geography(geometry_type="POINT", srid=4326), nullable=False
    )
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, name="source_type_enum", create_type=False),
        nullable=False,
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    license: Mapped[str] = mapped_column(Text, nullable=False)
    properties: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIM), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    documents: Mapped[list["Document"]] = relationship(
        back_populates="place", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("places_geom_gist", "geom", postgresql_using="gist"),
        Index("places_source_typ", "source_type"),
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    doc_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    place_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("places.id", ondelete="CASCADE"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, name="source_type_enum", create_type=False),
        nullable=False,
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    license: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIM), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    place: Mapped[Place | None] = relationship(back_populates="documents")

    __table_args__ = (
        Index("documents_place_id", "place_id"),
        Index("documents_source_typ", "source_type"),
    )
