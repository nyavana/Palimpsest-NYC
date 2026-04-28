## MODIFIED Requirements

### Requirement: Provenance captured for every row

Every row written to the `documents` or `places` tables SHALL carry a provenance record with `source_type`, `source_url`, `source_retrieved_at`, `license`, and a stable `doc_id` string. Narration generation depends on these fields for mandatory citations; the citation contract in `specs/agent-tools/spec.md` reuses the same field names so a row's provenance becomes its citation with no field renaming.

For V1, the `source_type` field is an enum with the values **`wikipedia | wikidata | osm`** only. The deferred sources (`chronicling-america`, `nypl`, `nyc-open-data`, `mta`, `noaa`) are NOT part of the V1 enum and SHALL be added back in v2 changes that introduce their respective ingestors. The citation contract in `agent-tools` MUST track this enum exactly — both specs SHALL list the same values at any given point in time.

#### Scenario: Missing provenance blocks insert
- **WHEN** an ingestor tries to insert a row without a populated `source_url`
- **THEN** the insert is rejected at the ORM layer with a validation error

#### Scenario: V1 source_type value is constrained to the V1 enum
- **WHEN** an ingestor tries to insert a row with `source_type="chronicling-america"` (a v2 value)
- **THEN** the insert is rejected at the ORM layer with a validation error naming the V1-allowed values (`wikipedia`, `wikidata`, `osm`)

#### Scenario: Provenance fields match what citations will reference
- **WHEN** a Wikipedia row is inserted with `source_type="wikipedia"` and `source_url="https://en.wikipedia.org/wiki/Cathedral_of_Saint_John_the_Divine"`
- **THEN** a later citation that references this `doc_id` carries identical `source_type` and `source_url` values, no transformation required

### Requirement: Staged ingestion (V1: single-tier; v2: bronze/silver/gold)

For V1, ingestion SHALL write directly into a single Postgres database (the "silver" tier from the original design) plus a local raw-cache directory for re-runnable downloads. The bronze/silver/gold three-tier separation is deferred to v2 — it exists to support the VPS deploy path (§14, deferred) and the §13 evaluation harness, neither of which is part of V1.

In V1, the directory structure is:

```
raw/      → re-runnable downloads, gitignored (e.g., Wikipedia API responses cached as JSON)
postgres/ → single ingestion target; queryable by the agent and the API
```

The V1 spec MUST NOT assume bronze (Parquet partitioning), gold (separate VPS DB), or `pg_dump` between tiers. v2 will re-introduce them as a separate change.

#### Scenario: V1 ingest writes to one Postgres database
- **WHEN** a V1 Wikipedia ingest run completes successfully
- **THEN** the rows are present in the single Postgres database referenced by `POSTGRES_HOST`, and there is no Parquet bronze tier or VPS gold tier in the V1 deployment

#### Scenario: Raw cache supports idempotent re-runs without re-downloading
- **WHEN** an ingestor runs twice and the upstream API has not changed
- **THEN** the second run reads from `raw/` instead of re-fetching, so re-runs are fast even on a cold Postgres

### Requirement: Bulk NLP routes through router `simple` tier

Bulk NLP work during ingestion (relevance filtering, entity extraction, summarization for V1; OCR cleanup is deferred with Chronicling America to v2) SHALL route through the LLM router with `complexity="simple"`. The router decides which underlying model serves that tier; ingestion code MUST NOT hardcode a model name, hostname, or backend type. If the local-tier backend's circuit breaker is open at call time, the router upgrades to the cloud-tier `standard` model and emits a telemetry record showing the upgrade — ingestion code does not need to handle the upgrade path explicitly.

This requirement is intentionally backend-agnostic. In V1 both router tiers terminate at OpenRouter, so "simple" calls hit `google/gemma-4-31b-it:free` by default. In v2 the same code path may hit an on-device endpoint with no ingestion changes.

#### Scenario: Wikipedia relevance filtering uses the simple tier
- **WHEN** the Wikipedia ingestor needs to drop articles whose lead paragraph is off-topic for the scope bbox
- **THEN** the ingestor calls `router.chat(..., complexity="simple")` and the telemetry record shows `backend="local"` (router-internal tier name) and the configured `LOCAL_LLM_MODEL`

#### Scenario: Ingestor hardcoding a backend is forbidden
- **WHEN** an ingestor module is grepped for direct adapter constructions (`OpenRouterAdapter(...)`, `LlamaCppAdapter(...)`, raw `httpx.post` to OpenAI-shaped URLs)
- **THEN** no such call site exists; all LLM access goes through `router.chat(...)`

#### Scenario: Local-tier upgrade is transparent to ingestor
- **WHEN** the local-tier circuit breaker is open and an ingestor calls `router.chat(..., complexity="simple")`
- **THEN** the call returns a `ChatResponse` from the cloud-tier `standard` model with `upgraded_from="local"` in metadata, and the ingestor proceeds without any conditional logic
