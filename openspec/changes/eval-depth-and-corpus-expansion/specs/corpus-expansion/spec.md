## ADDED Requirements

### Requirement: `SCOPE_BBOX` covers all of Manhattan

`apps/api/app/ingest/scope.py` `SCOPE_BBOX` SHALL be widened from the V1 Morningside-Heights + UWS rectangle to a bbox that encloses all of Manhattan island: latitude `40.7000` to `40.8800`, longitude `-74.0200` to `-73.9100`. The bbox SHALL contain Battery Park / Lower Manhattan, the Empire State Building / Midtown, and Inwood Hill Park, and SHALL NOT contain Prospect Park (Brooklyn) or Forest Hills (Queens).

#### Scenario: Bbox contains Manhattan extremes
- **WHEN** `test_ingest_scope.py` checks `SCOPE_BBOX.contains(...)` for `(40.7060, -74.0090)` (Battery Park), `(40.7484, -73.9857)` (Empire State), and `(40.8676, -73.9213)` (Inwood Hill Park)
- **THEN** all three assertions are true

#### Scenario: Bbox excludes neighboring boroughs
- **WHEN** `test_ingest_scope.py` checks `SCOPE_BBOX.contains(40.6782, -73.9442)` (Prospect Park) and `SCOPE_BBOX.contains(40.7282, -73.7949)` (Forest Hills)
- **THEN** both assertions are false

### Requirement: `SCOPE_VERSION` is bumped to `v2-manhattan`

`apps/api/app/ingest/scope.py` SHALL expose a module-level constant `SCOPE_VERSION` whose value is `"v2-manhattan"`. This constant is read by ingestion code for telemetry and stamped on ingestion log entries so the corpus generation can be identified post-hoc. Any future widening of `SCOPE_BBOX` SHALL bump `SCOPE_VERSION` in the same commit.

#### Scenario: `SCOPE_VERSION` is the Manhattan-wide value
- **WHEN** `test_ingest_scope.py` imports `SCOPE_VERSION` from `app.ingest.scope`
- **THEN** the value is the exact string `"v2-manhattan"`

### Requirement: Re-ingestion runs cleanly on a fresh volume at the widened bbox

After `make nuke && make up`, the auto-ingest pipeline (per the existing `init-ingest` compose service) SHALL re-run OSM Overpass and Wikipedia/Wikidata SPARQL ingestion at the widened bbox without any manual CLI invocation. The post-ingest corpus SHALL contain at least 3,000 places (across `osm`, `wikipedia`, `wikidata` source types) and at least 1,500 `wikipedia` documents. Actual cardinality SHALL be recorded in `docs/eval/notes/2026-05-12-corpus-counts.md`.

#### Scenario: Auto-ingest populates the widened corpus
- **WHEN** `make nuke && make up` finishes on a Manhattan-bbox `scope.py`
- **THEN** `SELECT COUNT(*) FROM places` returns ≥ 3,000 and `SELECT COUNT(*) FROM documents WHERE source_type = 'wikipedia'` returns ≥ 1,500

#### Scenario: Manual CLI override remains available
- **WHEN** an operator runs `docker compose exec api python -m app.ingest.cli osm run` after the auto-ingest has completed
- **THEN** the CLI short-circuits (places already populated for that source_type) and exits without re-fetching, matching the existing V1 behavior

### Requirement: Existing trigram indexes are sufficient — no new migration required for `pg_trgm` coverage

The trigram indexes `places_name_trgm` (on `places.name`) and `documents_body_trgm` (on `documents.body`), declared in `apps/api/app/db/migrations/0002_places.sql` since V1, SHALL be preserved without renaming or dropping. No new migration is required to add trigram coverage for hybrid retrieval. An optional `apps/api/app/db/migrations/0003_widen_scope_indexes.sql` MAY be added if planner ANALYZE statistics trail the new corpus cardinality after re-ingest, but is not required by this requirement.

#### Scenario: Trigram indexes survive `make nuke && make up`
- **WHEN** the postgres container reapplies `0001_init.sql` then `0002_places.sql` on a fresh volume
- **THEN** `SELECT indexname FROM pg_indexes WHERE indexname IN ('places_name_trgm', 'documents_body_trgm')` returns both rows

### Requirement: Retrieval latency on the widened corpus stays within budget

After re-ingest at the Manhattan-wide bbox, `POST /internal/retrieve` p95 latency for a 10-call sample with `top_k=8` SHALL be ≤ 2 seconds when `RETRIEVAL_MODE=dense`. If this budget is exceeded, the operator SHALL apply mitigation R1 from the design (add a per-query bbox filter to `search_places` so the agent can pass a region hint) before continuing.

#### Scenario: p95 latency within budget
- **WHEN** the operator runs 10 sequential `POST /internal/retrieve` calls with `top_k=8` against the freshly-ingested Manhattan corpus
- **THEN** the slowest of the 10 wall-clock times is ≤ 2 seconds

### Requirement: OSRM extract resize is decoupled from headline eval metrics

Resizing `infra/osrm/extract.osm.pbf` to the widened Manhattan bbox is OPTIONAL and MAY be deferred per design risk R8. The eval headline metrics (CCR, HR, FA, NQ) SHALL NOT depend on walk geometry; the SSE `walk` frame is already conditional in the existing code path. If the OSRM extract is not resized, walk-planning queries outside the MH+UWS sub-bbox MAY return without a `walk` frame and this SHALL NOT be treated as an error by the agent or by the frontend.

#### Scenario: Eval runs on the widened corpus without OSRM resize
- **WHEN** the operator runs Phase 3 eval against `RETRIEVAL_MODE=dense` on the widened corpus without having resized the OSRM extract
- **THEN** the eval completes, the `ablation_table.md` rows for CCR / HR / FA / NQ are computed, and Palimpsest rows simply lack a `walk` frame for queries outside the MH+UWS sub-bbox
