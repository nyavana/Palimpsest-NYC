## ADDED Requirements

### Requirement: Public-domain and free sources only

All v1 data sources SHALL be public-domain or free/open-licensed. No paid APIs, no private datasets, no scraped content under restrictive terms. The approved v1 source list is: Wikipedia/Wikidata, Chronicling America (Library of Congress), NYPL Digital Collections, OpenStreetMap (Overpass), NYC Open Data (Socrata), MTA GTFS-Realtime, NOAA Weather API, Wikimedia Commons. Adding a new source requires an entry in `apps/api/app/ingest/README.md` documenting the license and citation format.

#### Scenario: Adding a new source without license docs fails review
- **WHEN** a developer introduces a new ingestor module without updating `apps/api/app/ingest/README.md`
- **THEN** the PR is blocked until the license and citation format are documented

### Requirement: Staged ingestion with bronze/silver/gold tiers

Every ingestor SHALL write through a three-tier pipeline: `bronze` (raw downloaded files on the dev box, partitioned Parquet), `silver` (normalized rows in dev-box Postgres), and `gold` (pruned subset in VPS Postgres produced via `pg_dump`). Raw archives MUST NOT be copied to the VPS.

#### Scenario: Chronicling America raw zip never reaches VPS
- **WHEN** Chronicling America ingestion completes successfully
- **THEN** `bronze/chronicling-america/**` contains downloaded files on the dev box only and does not appear on the VPS filesystem

### Requirement: Scope bounding box constant

Ingestors SHALL filter incoming rows by a single shared bounding box constant imported from `apps/api/app/ingest/scope.py`. The v1 bbox SHALL cover Morningside Heights + Upper West Side (roughly west of Central Park West, east of the Hudson, north of W 59th St, south of W 125th St). Widening the scope requires updating this constant in a later change and re-running ingestion.

#### Scenario: Row outside scope is dropped at ingest time
- **WHEN** an ingestor encounters a Wikipedia article geocoded to Brooklyn
- **THEN** the row is dropped with a counter increment, not inserted into Postgres

### Requirement: Provenance captured for every row

Every row written to the `documents` or `places` tables SHALL carry a provenance record with `source_id` (enum of approved sources), `source_url`, `source_retrieved_at`, `license`, and a stable `doc_id` string. Narration generation depends on these fields for mandatory citations.

#### Scenario: Missing provenance blocks insert
- **WHEN** an ingestor tries to insert a row without a populated `source_url`
- **THEN** the insert is rejected at the ORM layer with a validation error

### Requirement: Idempotent upserts

Every ingestor SHALL support idempotent re-runs: running the same ingest twice MUST produce the same row count and content (modulo updated timestamps). Upserts SHALL use natural keys (e.g., Wikipedia page ID + revision, Chronicling America LCCN + page ID).

#### Scenario: Wikipedia ingest run twice
- **WHEN** `python -m app.ingest.wikipedia run` is executed twice in succession with the same scope
- **THEN** the second run updates zero new rows and does not create duplicates

### Requirement: Local Gemma-4 is the default for bulk NLP tasks

Bulk NLP work during ingestion (OCR cleanup, relevance filtering, entity extraction, sentiment) SHALL route through the LLM router with `complexity="simple"`, targeting the local Gemma-4 backend. Only if the local backend is unavailable MAY ingestion fall back to the cloud model, and this SHALL be logged clearly.

#### Scenario: Chronicling America OCR cleanup uses local Gemma
- **WHEN** a Chronicling America article needs OCR cleanup during silver-tier processing
- **THEN** the ingestor calls `router.chat(..., complexity="simple")` and the telemetry record shows `backend="local"`
