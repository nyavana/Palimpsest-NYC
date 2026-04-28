"""End-to-end provenance ↔ citation field-name parity (§11.6).

Per `swap-llm-tiers-and-lock-mvp-decisions/specs/data-ingest/spec.md` and
`agent-tools/spec.md`: ingested provenance fields and emitted citation
fields share names exactly, so a row's provenance becomes its citation
with no transformation step.

These tests do NOT invoke the (not-yet-built) §12.3 verifier — they verify
the *contract* by constructing a citation from a record's provenance and
checking that all five required Citation fields are present and equal.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import respx
from httpx import Response

from app.db.models import SourceType
from app.ingest.osm import OSM_OVERPASS_URL, OsmIngestor
from app.ingest.scope import ScopeBbox
from app.ingest.wikipedia import (
    WIKIDATA_SPARQL_URL,
    WIKIPEDIA_SUMMARY_URL,
    WikipediaIngestor,
)

# Required citation fields, locked in agent-tools/spec.md §"Citation contract".
CITATION_FIELDS = ("doc_id", "source_url", "source_type", "span", "retrieval_turn")
V1_SOURCE_TYPES = {"wikipedia", "wikidata", "osm"}

_BBOX = ScopeBbox(min_lat=40.7680, max_lat=40.8150, min_lon=-74.0050, max_lon=-73.9550)


def _make_citation(record, *, span: dict[str, int], retrieval_turn: int) -> dict[str, Any]:
    """Build a citation from a row's provenance — NO field renaming.

    `span` and `retrieval_turn` come from the agent loop, not the ingest
    layer, so we construct them here to model what `search_places` would do
    when it returns this record.
    """
    return {
        "doc_id": record.doc_id,
        "source_url": record.source_url,
        "source_type": record.source_type.value,
        "span": span,
        "retrieval_turn": retrieval_turn,
    }


# ── Wikipedia ───────────────────────────────────────────────────────


@respx.mock(base_url="https://query.wikidata.org")
@respx.mock(base_url="https://en.wikipedia.org")
def test_wikipedia_record_yields_valid_citation_shape(respx_mock):
    respx_mock.post(WIKIDATA_SPARQL_URL).mock(
        return_value=Response(
            200,
            json={
                "head": {},
                "results": {
                    "bindings": [
                        {
                            "item": {"value": "http://www.wikidata.org/entity/Q201219"},
                            "itemLabel": {"value": "Cathedral of St. John the Divine"},
                            "coord": {"value": "Point(-73.9619 40.8038)"},
                            "article": {
                                "value": "https://en.wikipedia.org/wiki/Cathedral_of_Saint_John_the_Divine"
                            },
                        }
                    ]
                },
            },
        )
    )
    respx_mock.get(
        f"{WIKIPEDIA_SUMMARY_URL}Cathedral_of_Saint_John_the_Divine"
    ).mock(
        return_value=Response(
            200,
            json={
                "extract": "The Cathedral Church of St. John the Divine …",
                "title": "Cathedral of St. John the Divine",
            },
        )
    )

    ingestor = WikipediaIngestor(scope=_BBOX)
    place, doc = next(ingestor.iter_records_sync())
    assert doc is not None

    # Build citation from the document (a doc-level citation; place-level
    # also works the same way).
    citation = _make_citation(doc, span={"start": 0, "end": 32}, retrieval_turn=1)

    # All five Citation fields present
    for k in CITATION_FIELDS:
        assert k in citation, f"missing citation field: {k}"

    # source_type values match the V1 enum exactly
    assert citation["source_type"] in V1_SOURCE_TYPES
    assert citation["source_type"] == "wikipedia"

    # No field rename: the ingest record has the same field name + value
    assert citation["doc_id"] == doc.doc_id
    assert citation["source_url"] == doc.source_url
    assert citation["source_type"] == doc.source_type.value


# ── OSM ─────────────────────────────────────────────────────────────


@respx.mock
def test_osm_record_yields_valid_citation_shape(respx_mock):
    respx_mock.post(OSM_OVERPASS_URL).mock(
        return_value=Response(
            200,
            json={
                "elements": [
                    {
                        "type": "node",
                        "id": 12345,
                        "lat": 40.8038,
                        "lon": -73.9619,
                        "tags": {"name": "Cathedral of St. John the Divine"},
                    }
                ]
            },
        )
    )
    ingestor = OsmIngestor(scope=_BBOX)
    place, _ = next(ingestor.iter_records_sync())
    citation = _make_citation(place, span={"start": 0, "end": 16}, retrieval_turn=2)

    for k in CITATION_FIELDS:
        assert k in citation
    assert citation["source_type"] == "osm"
    assert citation["source_type"] in V1_SOURCE_TYPES
    assert citation["doc_id"] == place.doc_id
    assert citation["source_url"] == place.source_url


# ── Field-name parity assertion ─────────────────────────────────────


def test_provenance_field_names_overlap_citation_field_names_exactly():
    """The data-ingest spec REQUIRES that provenance fields can become citation
    fields with no rename. The intersection MUST be exact for the three fields
    that the verifier checks (doc_id, source_url, source_type)."""
    from app.ingest.records import DocumentRecord, PlaceRecord

    record_fields = {f.name for f in DocumentRecord.__dataclass_fields__.values()}
    record_fields |= {f.name for f in PlaceRecord.__dataclass_fields__.values()}
    # Verifier-checked citation fields must each have an identically-named
    # field on the ingest record (span + retrieval_turn come from the agent loop).
    must_share = {"doc_id", "source_url", "source_type"}
    assert must_share <= record_fields


def test_source_retrieved_at_is_timezone_aware():
    """Citation generation depends on UTC timestamps; bare datetimes confuse asyncpg."""
    from app.ingest.records import PlaceRecord

    p = PlaceRecord(
        doc_id="t:1",
        name="t",
        lat=0.0,
        lon=0.0,
        source_type=SourceType.osm,
        source_url="https://x.test/y",
        source_retrieved_at=datetime.now(tz=timezone.utc),
        license="ODbL 1.0",
    )
    assert p.source_retrieved_at.tzinfo is not None
