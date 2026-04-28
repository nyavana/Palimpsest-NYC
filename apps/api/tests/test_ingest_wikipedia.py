"""Wikipedia/Wikidata ingestor unit tests.

Httpx is mocked via `respx` (already in the dev deps) so the suite is
network-free. A separate live integration test (PALIMPSEST_INTEGRATION=1)
hits the real Wikidata SPARQL endpoint + Wikipedia REST API.
"""

from __future__ import annotations

import respx
from httpx import Response

from app.db.models import SourceType
from app.ingest.scope import ScopeBbox
from app.ingest.wikipedia import (
    WIKIPEDIA_SUMMARY_URL,
    WIKIDATA_SPARQL_URL,
    WikipediaIngestor,
)


_BBOX = ScopeBbox(min_lat=40.7680, max_lat=40.8150, min_lon=-74.0050, max_lon=-73.9550)


# ── SPARQL response → normalized records ────────────────────────────


_SPARQL_PAYLOAD = {
    "head": {"vars": ["item", "itemLabel", "coord", "article"]},
    "results": {
        "bindings": [
            {
                "item": {"value": "http://www.wikidata.org/entity/Q201219"},
                "itemLabel": {"value": "Cathedral of St. John the Divine"},
                "coord": {"value": "Point(-73.9619 40.8038)"},
                "article": {
                    "value": "https://en.wikipedia.org/wiki/Cathedral_of_Saint_John_the_Divine"
                },
            },
            {
                # Outside the bbox (lat too low) — must be filtered out.
                "item": {"value": "http://www.wikidata.org/entity/Q123"},
                "itemLabel": {"value": "Some Far-Away Place"},
                "coord": {"value": "Point(-73.97 40.5)"},
                "article": {
                    "value": "https://en.wikipedia.org/wiki/Far_Away"
                },
            },
            {
                # Inside the bbox.
                "item": {"value": "http://www.wikidata.org/entity/Q124"},
                "itemLabel": {"value": "Riverside Church"},
                "coord": {"value": "Point(-73.9626 40.8108)"},
                "article": {"value": "https://en.wikipedia.org/wiki/Riverside_Church"},
            },
        ]
    },
}


_SUMMARY_BY_TITLE = {
    "Cathedral_of_Saint_John_the_Divine": {
        "extract": "The Cathedral Church of St. John the Divine is the cathedral …",
        "title": "Cathedral of St. John the Divine",
    },
    "Riverside_Church": {
        "extract": "Riverside Church is an interdenominational church …",
        "title": "Riverside Church",
    },
}


@respx.mock(base_url="https://en.wikipedia.org")
@respx.mock(base_url="https://query.wikidata.org")
def test_ingestor_collects_records_inside_bbox_only(respx_mock):
    respx_mock.post(WIKIDATA_SPARQL_URL).mock(
        return_value=Response(200, json=_SPARQL_PAYLOAD)
    )
    for title, payload in _SUMMARY_BY_TITLE.items():
        respx_mock.get(f"{WIKIPEDIA_SUMMARY_URL}{title}").mock(
            return_value=Response(200, json=payload)
        )

    ingestor = WikipediaIngestor(scope=_BBOX)
    records = list(ingestor.iter_records_sync())

    place_titles = {r[0].name for r in records}
    assert "Cathedral of St. John the Divine" in place_titles
    assert "Riverside Church" in place_titles
    assert "Some Far-Away Place" not in place_titles


@respx.mock(base_url="https://en.wikipedia.org")
@respx.mock(base_url="https://query.wikidata.org")
def test_record_provenance_matches_citation_contract(respx_mock):
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
    records = list(ingestor.iter_records_sync())
    place, doc = records[0]

    # doc_id must follow the spec example: wikipedia:<page-id-slug>
    assert place.doc_id == "wikipedia:Cathedral_of_Saint_John_the_Divine"
    assert place.source_type is SourceType.wikipedia
    assert place.source_url.startswith("https://en.wikipedia.org/wiki/")
    assert place.license == "CC BY-SA 4.0"

    # Document provenance shares fields with place
    assert doc is not None
    assert doc.source_type is SourceType.wikipedia
    assert doc.source_url == place.source_url
    assert doc.place_doc_id == place.doc_id
    # Document doc_id is its own identifier (must be unique across the corpus)
    assert doc.doc_id != place.doc_id
    assert doc.doc_id.startswith("wikipedia-doc:")


@respx.mock(base_url="https://query.wikidata.org")
def test_ingestor_recovers_when_summary_endpoint_404s(respx_mock):
    """Some Wikidata items have no English Wikipedia article. Skip cleanly."""
    respx_mock.post(WIKIDATA_SPARQL_URL).mock(
        return_value=Response(
            200,
            json={
                "head": {},
                "results": {
                    "bindings": [
                        {
                            "item": {"value": "http://www.wikidata.org/entity/Q999"},
                            "itemLabel": {"value": "Stub"},
                            "coord": {"value": "Point(-73.97 40.78)"},
                            "article": {
                                "value": "https://en.wikipedia.org/wiki/Nonexistent"
                            },
                        }
                    ]
                },
            },
        )
    )

    with respx.mock(base_url="https://en.wikipedia.org") as wiki:
        wiki.get(f"{WIKIPEDIA_SUMMARY_URL}Nonexistent").mock(
            return_value=Response(404)
        )

        ingestor = WikipediaIngestor(scope=_BBOX)
        records = list(ingestor.iter_records_sync())
        # Place still emitted (we have coord + label) but no Document.
        assert len(records) == 1
        place, doc = records[0]
        assert place.name == "Stub"
        assert doc is None


def test_parse_point_handles_well_known_text():
    """SPARQL returns coords as `Point(<lon> <lat>)`."""
    from app.ingest.wikipedia import _parse_point

    lat, lon = _parse_point("Point(-73.9619 40.8038)")
    assert (lat, lon) == (40.8038, -73.9619)


def test_doc_id_for_url_slug():
    from app.ingest.wikipedia import _slug_from_url

    assert (
        _slug_from_url("https://en.wikipedia.org/wiki/Cathedral_of_Saint_John_the_Divine")
        == "Cathedral_of_Saint_John_the_Divine"
    )
    assert (
        _slug_from_url("https://en.wikipedia.org/wiki/Caf%C3%A9_Boulud")
        == "Café_Boulud"
    )
