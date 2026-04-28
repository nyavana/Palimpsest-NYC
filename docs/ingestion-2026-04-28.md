# §11 — Ingestion (Wikipedia + OSM) — 2026-04-28

OpenSpec change: `initial-palimpsest-scaffold` §11.1, §11.4, §11.5, §11.6
(under V1 cuts locked by `swap-llm-tiers-and-lock-mvp-decisions`).
§11.2 / §11.3 deferred to v2.

## What landed

| Path | Purpose |
|---|---|
| `apps/api/app/ingest/raw_cache.py` | Content-addressed JSON cache under `data/raw/`. Atomic writes, treats corrupt files as misses. Used by both ingestors so re-runs don't re-fetch upstream. |
| `apps/api/app/ingest/records.py` | `PlaceRecord` / `DocumentRecord` — source-agnostic ingest dataclasses. Field names match the citation contract exactly. |
| `apps/api/app/ingest/upsert.py` | `INSERT … ON CONFLICT (doc_id) DO UPDATE` for places and documents. Idempotent re-runs. Embeddings via `Embedder` singleton; existing embeddings are preserved (`COALESCE(excluded.embedding, embedding)`) when an upsert payload has none. |
| `apps/api/app/ingest/wikipedia.py` | Wikidata SPARQL (bbox-bounded via the `wikibase:box` service) → Wikipedia REST `/page/summary/<slug>`. Polite 200ms delay between summary fetches; 404/429 → skip cleanly. |
| `apps/api/app/ingest/osm.py` | Overpass API query for named POIs with `amenity` / `tourism` / `historic` / `leisure` tags inside the bbox. POIs map to `places` (no separate document tier). |
| `apps/api/app/ingest/cli.py` | `python -m app.ingest.cli {wikipedia|osm} run`. Per V1 §6.5, ingestion is a one-shot CLI; the worker container only runs a heartbeat loop. |
| `docker-compose.yml` | Adds `./data:/app/data` bind mount on the api service so the raw cache survives container rebuilds. |

## Tests added

- `tests/test_ingest_raw_cache.py` — 8 tests. Hash fan-out, atomic writes, corrupt-file recovery, URL-distinctness.
- `tests/test_ingest_upsert.py` — 10 tests. SQL shape (INSERT INTO / ON CONFLICT / `ST_SetSRID`+`::geography`), bind params for `place_id`, embedder gating.
- `tests/test_ingest_wikipedia.py` — 5 tests. SPARQL response → records, bbox filtering, missing-summary recovery, doc_id slug parsing.
- `tests/test_ingest_osm.py` — 4 tests. Element filter (named-only, in-bbox-only), `osm:<element>:<id>` doc_id format, way-uses-`center`-coords.
- `tests/test_ingest_cli.py` — 2 tests. argparse + dispatch wiring with a fake registry.
- `tests/test_provenance_citation_link.py` — 4 tests. §11.6 round-trip: build a Citation from each ingestor's PlaceRecord/DocumentRecord and assert all five required fields are present, that `source_type` is in the V1 enum, and that the field names parity required by data-ingest spec holds.

`make test` is now **64 passed, 1 skipped** (the skipped one downloads real HF weights when `PALIMPSEST_INTEGRATION=1`).

## Live integration validation

Brought up `postgres + redis + api` against a fresh volume. Schema applied
from §10's migrations. Then ran both ingestors:

```
$ docker compose exec api python -m app.ingest.cli osm run
ingest.osm.done   bbox=(-74.005, 40.768, -73.955, 40.815)  fetched=436  inserted=436  errors=0  duration_s=6.9

$ docker compose exec api python -m app.ingest.cli wikipedia run
ingest.wikipedia.done   bbox=(-74.005, 40.768, -73.955, 40.815)  fetched=500  inserted=500  errors=0  duration_s=27.0
```

Postgres state after the two runs:

```
SELECT source_type, COUNT(*), COUNT(embedding) FROM places GROUP BY source_type;
 source_type |  n  | with_embedding
 wikipedia   | 492 | 492
 osm         | 436 | 436

SELECT source_type, COUNT(*), COUNT(embedding) FROM documents;
 source_type | docs | with_embedding
 wikipedia   |  323 | 323
```

**928 places + 323 documents, 100% embedding coverage.**

### Spatial query sanity check

```
SELECT name,
       ST_Distance(geom, ST_SetSRID(ST_MakePoint(-73.9619, 40.8038), 4326)::geography) AS m
FROM places ORDER BY m LIMIT 5;
```

→ Bison (78m), Pulpit (82m), Biblical Garden (86m), Pulpit Green (88m),
Homeless Jesus (90m). Those are the small landmarks on the Cathedral of
St. John the Divine grounds, which is at the query coordinates. PostGIS
GIST index is doing real work.

### Vector similarity sanity check

Embedded the query string `"gothic cathedral with stained glass"` and
ran cosine-distance ANN against `places.embedding`:

```
0.2463  wikipedia  Archdiocesan Cathedral of the Holy Trinity
0.2705  osm        Cathedral of the Holy Trinity
0.3090  osm        Pulpit
0.3140  osm        Church of the Master
0.3171  osm        Templo Biblico
…
```

Top hits are religious buildings; cathedrals rank first. pgvector ivfflat
+ bge-small embeddings are operational end-to-end.

## Implementation notes

- **SPARQL bbox params**: the wikibase `box` service uses
  `cornerSouthWest` / `cornerNorthEast`, both as `Point(<lon> <lat>)`.
  The first attempt used `cornerWest` / `cornerEast` (incorrect) and
  silently returned 0 rows.
- **Wikipedia rate limiting**: the anonymous REST API throttles
  per-IP. We sleep 200ms between summary fetches when the raw cache
  is cold; cached rows skip the sleep entirely. 429s are treated as
  "skip the document" so a partial throttle event doesn't crash the
  whole run — the place row still lands.
- **OSM is place-only in V1**: the spec lists OSM as needed for §12.1
  routing geometry, but the place-level POIs are useful on their own
  (icons, names, categories). The full street-network ingest can land
  in a §12.1 follow-up migration when the routing engine is picked.
- **Field-name parity**: ingestor records, ORM models, citation
  contract, and migration columns all use the exact same names for
  `doc_id`, `source_url`, `source_type`, `source_retrieved_at`, and
  `license`. `tests/test_provenance_citation_link.py` asserts this
  intersection.

## What unblocks next

- **§9 (agent + `search_places`)**: the corpus is now real. `search_places`
  can run a hybrid query (BM25-ish via `pg_trgm` + cosine ANN over
  embeddings, restricted by bbox / radius) and return real `doc_id` /
  `source_url` / `source_type` triples for citations.
- **§12 (server-side walk planner)**: 928 geocoded places give PostGIS
  enough to compute routes between agent-cited place_ids. Street network
  ingestion (a separate Overpass query for `highway=*` ways with
  `out geom;`) can be added when the routing engine ships.

## Pre-existing items (not addressed in §11)

- `apps/web/Dockerfile` path bug — `make up` (full stack) still fails on
  the web service. Not blocking ingestion or any backend work; flagged
  for the frontend phase.
- Wikipedia ingestion does not currently call the LLM router for
  relevance filtering. The data-ingest spec allows this as a **MAY**
  ("if needed"); the bbox + Wikidata filter are tight enough that the
  ~500 result corpus is on-topic. If §13.4 hand-grading shows noise we
  can plug a `complexity="simple"` relevance pass into the
  `iter_records_sync` loop.
