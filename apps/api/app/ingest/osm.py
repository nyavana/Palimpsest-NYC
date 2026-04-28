"""OpenStreetMap (Overpass) ingestor (V1).

V1 scope: named POIs (amenities, historic sites, leisure features, tourist
attractions) inside `SCOPE_BBOX`. Street geometries needed for §12.1 routing
land in a follow-up migration once the routing engine is chosen.

`source_type="osm"`, `doc_id="osm:<element>:<id>"` per the source catalog.
License: ODbL 1.0.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

import httpx

from app.db.models import SourceType
from app.ingest.base import IngestReport
from app.ingest.raw_cache import RawCache
from app.ingest.records import DocumentRecord, PlaceRecord
from app.ingest.scope import SCOPE_BBOX, ScopeBbox
from app.logging import get_logger

log = get_logger(__name__)

OSM_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "PalimpsestNYC/0.1 (https://github.com/nyavana/Palimpsest-NYC)"
LICENSE = "ODbL 1.0"


def _overpass_query_for_bbox(scope: ScopeBbox) -> str:
    """Overpass query: named amenity / historic / tourism / leisure features.

    Uses bbox filter `(<south>,<west>,<north>,<east>)` and `out center;` so
    way features come back with a representative point.
    """
    s, w, n, e = scope.min_lat, scope.min_lon, scope.max_lat, scope.max_lon
    bbox = f"({s},{w},{n},{e})"
    return f"""
[out:json][timeout:60];
(
  node["amenity"~"^(place_of_worship|theatre|library|museum|university|college|arts_centre|cinema)$"]["name"]{bbox};
  node["tourism"~"^(attraction|museum|gallery|artwork|viewpoint)$"]["name"]{bbox};
  node["historic"]["name"]{bbox};
  node["leisure"~"^(park|garden)$"]["name"]{bbox};
  way ["amenity"~"^(place_of_worship|theatre|library|museum|university|college|arts_centre|cinema)$"]["name"]{bbox};
  way ["tourism"~"^(attraction|museum|gallery|artwork|viewpoint)$"]["name"]{bbox};
  way ["historic"]["name"]{bbox};
  way ["leisure"~"^(park|garden)$"]["name"]{bbox};
);
out center;
""".strip()


def _doc_id_for(element: dict[str, Any]) -> str:
    return f"osm:{element['type']}:{element['id']}"


def _coords_for(element: dict[str, Any]) -> tuple[float, float] | None:
    """Pull (lat, lon) from a node (lat/lon) or way/relation (`center`)."""
    if "lat" in element and "lon" in element:
        return float(element["lat"]), float(element["lon"])
    center = element.get("center")
    if center and "lat" in center and "lon" in center:
        return float(center["lat"]), float(center["lon"])
    return None


def _osm_url(element: dict[str, Any]) -> str:
    return f"https://www.openstreetmap.org/{element['type']}/{element['id']}"


def _embed_text_for(name: str, tags: dict[str, Any]) -> str:
    """Build a short blurb that captures the salient OSM tags for embedding.

    Concatenates name + a few human-readable tag values so the place's
    semantic vector reflects what the place *is*, not just its label.
    """
    parts: list[str] = [name]
    for k in ("amenity", "tourism", "historic", "leisure", "religion", "denomination"):
        v = tags.get(k)
        if v:
            parts.append(f"{k}: {v}")
    return ". ".join(parts)


def _fetch_overpass(client: httpx.Client, query: str) -> dict[str, Any]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    resp = client.post(OSM_OVERPASS_URL, data={"data": query}, headers=headers)
    resp.raise_for_status()
    return resp.json()


class OsmIngestor:
    """OpenStreetMap POI ingestor for V1 scope."""

    source = "osm"

    def __init__(
        self,
        *,
        scope: ScopeBbox = SCOPE_BBOX,
        cache: RawCache | None = None,
        client_factory: type[httpx.Client] = httpx.Client,
    ) -> None:
        self._scope = scope
        self._cache = cache
        self._client_factory = client_factory

    def iter_records_sync(self) -> Iterator[tuple[PlaceRecord, DocumentRecord | None]]:
        query = _overpass_query_for_bbox(self._scope)
        cache_key = f"overpass:{self._scope.as_tuple()}"
        with self._client_factory(timeout=120.0) as client:
            payload = self._cached_or_fetch(
                cache_key, lambda: _fetch_overpass(client, query)
            )
        for element in payload.get("elements", []):
            record = self._element_to_record(element)
            if record is not None:
                yield record

    def _element_to_record(
        self, element: dict[str, Any]
    ) -> tuple[PlaceRecord, None] | None:
        tags = element.get("tags") or {}
        name = tags.get("name")
        if not name:
            return None
        coords = _coords_for(element)
        if coords is None:
            return None
        lat, lon = coords
        if not self._scope.contains(lat, lon):
            return None

        retrieved = datetime.now(tz=timezone.utc)
        place = PlaceRecord(
            doc_id=_doc_id_for(element),
            name=name,
            lat=lat,
            lon=lon,
            source_type=SourceType.osm,
            source_url=_osm_url(element),
            source_retrieved_at=retrieved,
            license=LICENSE,
            properties={"tags": tags},
            embed_text=_embed_text_for(name, tags),
        )
        # OSM POIs in V1 are place-only — there's no separate "Document"
        # body for an OSM tag set. The tag info is captured in `properties`.
        return (place, None)

    def _cached_or_fetch(self, key: str, fetch: Any) -> Any:
        if self._cache is None:
            return fetch()
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        result = fetch()
        if result is not None:
            self._cache.put(key, result)
        return result

    async def run(self, session, embedder=None) -> IngestReport:  # type: ignore[no-untyped-def]
        from app.ingest.upsert import upsert_place

        t0 = time.perf_counter()
        report = IngestReport(source=self.source)
        log.info("ingest.osm.start", bbox=self._scope.as_tuple())

        for place_record, _ in self.iter_records_sync():
            report.fetched += 1
            try:
                await upsert_place(session, place_record, embedder=embedder)
                report.inserted += 1
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"{place_record.doc_id}: {exc}")
                continue

        await session.commit()
        report.duration_s = time.perf_counter() - t0
        log.info(
            "ingest.osm.done",
            fetched=report.fetched,
            inserted=report.inserted,
            errors=len(report.errors),
            duration_s=round(report.duration_s, 3),
        )
        return report


__all__ = ["OsmIngestor", "OSM_OVERPASS_URL"]
