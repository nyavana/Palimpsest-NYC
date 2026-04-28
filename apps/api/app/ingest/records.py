"""Source-agnostic ingestion record shapes.

Ingestors normalize their upstream payloads into these dataclasses. The
upsert helper writes them to `places` / `documents` and computes embeddings.

Provenance fields (`source_type`, `source_url`, `source_retrieved_at`,
`license`, `doc_id`) match the citation contract in `agent-tools/spec.md`
exactly so a row's provenance becomes its citation with no field renaming.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.db.models import SourceType


@dataclass(slots=True)
class PlaceRecord:
    """Normalized place row, ready for upsert into `places`."""

    doc_id: str
    name: str
    lat: float
    lon: float
    source_type: SourceType
    source_url: str
    source_retrieved_at: datetime
    license: str
    properties: dict[str, Any] = field(default_factory=dict)
    # Free-form text used to compute the place embedding. Typically the
    # name + a short blurb / tags. Empty string skips embedding.
    embed_text: str = ""


@dataclass(slots=True)
class DocumentRecord:
    """Normalized document row, optionally linked to a place via `place_doc_id`."""

    doc_id: str
    place_doc_id: str | None
    title: str
    body: str
    source_type: SourceType
    source_url: str
    source_retrieved_at: datetime
    license: str
    embed_text: str = ""
