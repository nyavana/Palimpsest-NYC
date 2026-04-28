"""Wikipedia + Wikidata ingestor (V1).

Pipeline:
  1. SPARQL Wikidata for items inside `SCOPE_BBOX` that link to an English
     Wikipedia article. Returns (qid, label, point, article_url) per row.
  2. For each row, fetch the article summary via the Wikipedia REST API
     (`/page/summary/<title>`).
  3. Normalize to `PlaceRecord` (always) and `DocumentRecord` (when summary
     fetch succeeds), wired with provenance fields that match the citation
     contract.
  4. Caller (CLI / worker) feeds these to the upsert helper which computes
     embeddings via the singleton Embedder and writes to postgres.

License: every record is tagged `"CC BY-SA 4.0"` per Wikipedia/Wikidata's
content license.
"""

from __future__ import annotations

import re
import time
import urllib.parse
from collections.abc import Iterable, Iterator
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

# ── upstream endpoints ──────────────────────────────────────────────

WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"
WIKIPEDIA_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/"
USER_AGENT = "PalimpsestNYC/0.1 (https://github.com/nyavana/Palimpsest-NYC)"
LICENSE = "CC BY-SA 4.0"


# ── parsing helpers ─────────────────────────────────────────────────


_POINT_RE = re.compile(r"^Point\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)\s*$")


def _parse_point(value: str) -> tuple[float, float]:
    """Wikidata SPARQL returns coords as `Point(<lon> <lat>)`. Return (lat, lon)."""
    m = _POINT_RE.match(value)
    if not m:
        raise ValueError(f"unparseable Point literal: {value!r}")
    lon = float(m.group(1))
    lat = float(m.group(2))
    return (lat, lon)


def _slug_from_url(url: str) -> str:
    """Extract the article slug from `https://en.wikipedia.org/wiki/<slug>`.

    URL-decode percent-escapes so the doc_id is stable across Wikipedia's
    encoded vs decoded forms (e.g., `Caf%C3%A9_Boulud` → `Café_Boulud`).
    """
    path = urllib.parse.urlparse(url).path
    last = path.rstrip("/").rsplit("/", 1)[-1]
    return urllib.parse.unquote(last)


def _sparql_query_for_bbox(scope: ScopeBbox) -> str:
    """Build a SPARQL query for items inside the bbox with an enwiki article.

    Uses the wikibase `box` service with the documented corner parameter
    names `cornerSouthWest` / `cornerNorthEast` (both `Point(<lon> <lat>)`).
    """
    west, south, east, north = scope.as_tuple()
    return f"""
SELECT ?item ?itemLabel ?coord ?article WHERE {{
  SERVICE wikibase:box {{
    ?item wdt:P625 ?coord .
    bd:serviceParam wikibase:cornerSouthWest "Point({west} {south})"^^geo:wktLiteral .
    bd:serviceParam wikibase:cornerNorthEast "Point({east} {north})"^^geo:wktLiteral .
  }}
  ?article schema:about ?item ;
           schema:isPartOf <https://en.wikipedia.org/> .
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
}}
LIMIT 500
""".strip()


# ── raw fetchers (sync — easier to mock with respx) ─────────────────


def _fetch_sparql(client: httpx.Client, query: str) -> dict[str, Any]:
    headers = {
        "Accept": "application/sparql-results+json",
        "User-Agent": USER_AGENT,
    }
    resp = client.post(WIKIDATA_SPARQL_URL, data={"query": query}, headers=headers)
    resp.raise_for_status()
    return resp.json()


def _fetch_summary(client: httpx.Client, slug: str) -> dict[str, Any] | None:
    """Fetch a Wikipedia article summary. Returns None on 404 OR 429.

    Wikipedia's anonymous REST API is rate-limited (~200 req/s globally,
    but per-IP throttling kicks in well before that). On 429 we treat the
    document as "skip for this run" — the place row still lands; the doc
    can be filled in on a later run that hits the cache.
    """
    resp = client.get(
        f"{WIKIPEDIA_SUMMARY_URL}{slug}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    if resp.status_code in (404, 429):
        return None
    resp.raise_for_status()
    return resp.json()


# ── main ingestor ───────────────────────────────────────────────────


class WikipediaIngestor:
    """Wikipedia + Wikidata ingestor.

    Public surface:
      - `iter_records_sync()` returns `(PlaceRecord, DocumentRecord | None)`
         tuples. Sync because httpx.Client + respx is the simplest test path.
      - `run(session, embedder)` is the async one-shot used by the CLI / worker.
    """

    source = "wikipedia"

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

    # -- iter_records_sync ------------------------------------------

    def iter_records_sync(self) -> Iterator[tuple[PlaceRecord, DocumentRecord | None]]:
        query = _sparql_query_for_bbox(self._scope)
        with self._client_factory(timeout=60.0) as client:
            sparql = self._cached_or_fetch(
                f"sparql:{self._scope.as_tuple()}",
                lambda: _fetch_sparql(client, query),
            )
            for i, row in enumerate(sparql.get("results", {}).get("bindings", [])):
                # Be polite to Wikipedia's anonymous REST endpoint. ~5 req/s
                # is well under the rate limit and finishes a 200-row run in
                # ~40s. Cached rows (raw/) skip the sleep.
                if i and self._cache is None:
                    time.sleep(0.2)
                pair = self._row_to_records(client, row)
                if pair is not None:
                    yield pair

    def _row_to_records(
        self, client: httpx.Client, row: dict[str, Any]
    ) -> tuple[PlaceRecord, DocumentRecord | None] | None:
        try:
            label = row["itemLabel"]["value"]
            coord = row["coord"]["value"]
            article_url = row["article"]["value"]
        except KeyError:
            return None

        try:
            lat, lon = _parse_point(coord)
        except ValueError:
            return None

        if not self._scope.contains(lat, lon):
            return None

        slug = _slug_from_url(article_url)
        place_doc_id = f"wikipedia:{slug}"
        retrieved = datetime.now(tz=timezone.utc)

        place = PlaceRecord(
            doc_id=place_doc_id,
            name=label,
            lat=lat,
            lon=lon,
            source_type=SourceType.wikipedia,
            source_url=article_url,
            source_retrieved_at=retrieved,
            license=LICENSE,
            properties={"qid": _qid_from_uri(row.get("item", {}).get("value", ""))},
            embed_text=label,  # short, fast embedding; doc body adds a richer one.
        )

        summary = self._cached_or_fetch(
            f"summary:{slug}",
            lambda: _fetch_summary(client, slug),
        )
        document: DocumentRecord | None = None
        if summary is not None and summary.get("extract"):
            document = DocumentRecord(
                doc_id=f"wikipedia-doc:{slug}",
                place_doc_id=place_doc_id,
                title=summary.get("title") or label,
                body=summary["extract"],
                source_type=SourceType.wikipedia,
                source_url=article_url,
                source_retrieved_at=retrieved,
                license=LICENSE,
                embed_text=f"{label}. {summary['extract']}",
            )
        return (place, document)

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

    # -- async run for the CLI / worker -----------------------------

    async def run(self, session, embedder=None) -> IngestReport:  # type: ignore[no-untyped-def]
        from app.ingest.upsert import upsert_document, upsert_place

        t0 = time.perf_counter()
        report = IngestReport(source=self.source)
        log.info("ingest.wikipedia.start", bbox=self._scope.as_tuple())

        for place_record, doc_record in self.iter_records_sync():
            report.fetched += 1
            try:
                await upsert_place(session, place_record, embedder=embedder)
                if doc_record is not None:
                    await upsert_document(session, doc_record, embedder=embedder)
                report.inserted += 1
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"{place_record.doc_id}: {exc}")
                continue

        await session.commit()
        report.duration_s = time.perf_counter() - t0
        log.info(
            "ingest.wikipedia.done",
            fetched=report.fetched,
            inserted=report.inserted,
            errors=len(report.errors),
            duration_s=round(report.duration_s, 3),
        )
        return report


def _qid_from_uri(uri: str) -> str:
    """`http://www.wikidata.org/entity/Q201219` → `Q201219`."""
    return uri.rsplit("/", 1)[-1]


# Re-export `Iterable` so downstream callers can type-annotate without
# pulling collections.abc directly.
__all__ = [
    "WikipediaIngestor",
    "WIKIPEDIA_SUMMARY_URL",
    "WIKIDATA_SPARQL_URL",
    "Iterable",
]
