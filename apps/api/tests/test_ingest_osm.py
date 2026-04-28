"""OSM Overpass ingestor unit tests (mocked httpx via respx)."""

from __future__ import annotations

import respx
from httpx import Response

from app.db.models import SourceType
from app.ingest.osm import OSM_OVERPASS_URL, OsmIngestor
from app.ingest.scope import ScopeBbox

_BBOX = ScopeBbox(min_lat=40.7680, max_lat=40.8150, min_lon=-74.0050, max_lon=-73.9550)


_OVERPASS_PAYLOAD = {
    "elements": [
        # Node-style POI inside bbox
        {
            "type": "node",
            "id": 12345,
            "lat": 40.8038,
            "lon": -73.9619,
            "tags": {"name": "Cathedral of St. John the Divine", "amenity": "place_of_worship"},
        },
        # Way-style with `center` populated by Overpass `out center;`
        {
            "type": "way",
            "id": 67890,
            "center": {"lat": 40.8108, "lon": -73.9626},
            "tags": {"name": "Riverside Church", "amenity": "place_of_worship"},
        },
        # Element with no name — must be skipped (citations need a label)
        {
            "type": "node",
            "id": 99,
            "lat": 40.78,
            "lon": -73.97,
            "tags": {"amenity": "bench"},
        },
        # Element outside bbox — skipped
        {
            "type": "node",
            "id": 100,
            "lat": 39.0,
            "lon": -74.0,
            "tags": {"name": "Far Away", "amenity": "park"},
        },
    ],
}


@respx.mock
def test_iter_records_emits_named_elements_inside_bbox(respx_mock):
    respx_mock.post(OSM_OVERPASS_URL).mock(
        return_value=Response(200, json=_OVERPASS_PAYLOAD)
    )
    ingestor = OsmIngestor(scope=_BBOX)
    records = list(ingestor.iter_records_sync())

    names = {r[0].name for r in records}
    assert "Cathedral of St. John the Divine" in names
    assert "Riverside Church" in names
    # No-name and out-of-bbox both excluded
    assert len(records) == 2


@respx.mock
def test_record_provenance_matches_citation_contract(respx_mock):
    respx_mock.post(OSM_OVERPASS_URL).mock(
        return_value=Response(200, json=_OVERPASS_PAYLOAD)
    )
    ingestor = OsmIngestor(scope=_BBOX)
    records = list(ingestor.iter_records_sync())

    place, doc = records[0]
    assert place.source_type is SourceType.osm
    # doc_id matches the documented format: osm:<element>:<id>
    assert place.doc_id.startswith("osm:")
    assert place.doc_id.split(":")[1] in {"node", "way"}
    assert place.source_url.startswith("https://www.openstreetmap.org/")
    assert place.license == "ODbL 1.0"
    # OSM POIs are place-only — no separate Document tier in V1
    assert doc is None


@respx.mock
def test_way_uses_center_coords(respx_mock):
    respx_mock.post(OSM_OVERPASS_URL).mock(
        return_value=Response(200, json=_OVERPASS_PAYLOAD)
    )
    ingestor = OsmIngestor(scope=_BBOX)
    records = list(ingestor.iter_records_sync())
    riverside = next(r[0] for r in records if r[0].name == "Riverside Church")
    assert (riverside.lat, riverside.lon) == (40.8108, -73.9626)


def test_doc_id_format():
    from app.ingest.osm import _doc_id_for

    assert _doc_id_for({"type": "node", "id": 12345}) == "osm:node:12345"
    assert _doc_id_for({"type": "way", "id": 67890}) == "osm:way:67890"
    assert _doc_id_for({"type": "relation", "id": 1}) == "osm:relation:1"
