## Why

Week 1 of `initial-palimpsest-scaffold` shipped a dual-backend LLM router whose `simple` tier targeted a `llama.cpp` server running `google/gemma-4-26B-A4B-it` on the Windows 11 host. In the 17 days since the scaffold landed, the Win11 server has not been brought up, and the cost of doing so (driver setup, firewall, GPU warm-up, keeping it running while developing in WSL2) is no longer justifiable now that OpenRouter exposes `google/gemma-4-31b-it:free` at zero marginal cost. Continuing to gate development on a never-started Win11 daemon means the MVP path (§9 agent + §10 DB + §11 ingest + §12 walk planner) cannot start.

**V1 scope decision**: V1 is **online-only**. Every LLM call in V1 terminates at OpenRouter; on-device LLM hosting is **deferred to v2**. The router's two-adapter architecture remains so v2 can swap in an on-device endpoint by changing one env var, but no V1 deployment, test, or demo path requires it.

In addition, four MVP-blocking decisions were left explicitly "TBD" by Week 1 and are now blocking §10 and §11:

- the embedding model (Week 1 said "local Gemma-4 by default, bge-small fallback" — local Gemma is now off the table);
- the database migration tooling (Alembic vs raw SQL);
- the citation JSON shape (sketched in design.md, never locked);
- the code license (README says "TBD: MIT or Apache 2.0").

This change records all of those decisions in one audit-trail entry and adjusts the active specs so subsequent task groups have a stable contract to build against.

## What Changes

- **MODIFY** the `llm-router` capability so the `simple` tier is served by an env-configured OpenAI-compatible endpoint. For V1, both adapters bind to OpenRouter (`simple` → `google/gemma-4-31b-it:free`). The Win11 llama-server is removed from V1 documentation and is tracked as a v2 swap-in.
- **MODIFY** the `llm-router` model defaults: dev runs on free Gemma across all three complexities to keep $/run at zero; the eval harness in §13.6 will flip `OPENROUTER_STANDARD_MODEL` and `OPENROUTER_COMPLEX_MODEL` to the paid OpenAI slugs for the cost-vs-quality comparison.
- **ADD** an `embeddings` capability spec: `BAAI/bge-small-en-v1.5` via `sentence-transformers` running CPU-only inside the api container, 384-dim vectors, deterministic seeded output, batched at 32.
- **ADD** a `db-migrations` capability spec: plain SQL files, init migrations applied via the postgres entrypoint (`docker-entrypoint-initdb.d`), non-init migrations applied idempotently by the api on startup against a `schema_migrations` ledger table.
- **LOCK** the citation JSON contract referenced by `design.md` §7 and add two fields the verifier and frontend need (`source_url`, `retrieval_turn`).
- **LOCK** the code license at MIT and ship a top-level `LICENSE` file.
- **DEFER** to v2: on-device LLM hosting (Win11 llama.cpp), Google Photorealistic 3D Tiles, multimodal image retrieval, cross-session memory.

- **MODIFY** the `agent-tools` capability to (a) lock the citation JSON contract with five required fields (`doc_id`, `source_url`, `source_type`, `span`, `retrieval_turn`) where `span` is opaque to the verifier; (b) reduce the V1 LLM-callable tool surface to a **single tool**, `search_places`. The remaining tools (`spatial_query`, `historical_lookup`, `current_events`, `plan_walk`) are deferred to v2; `plan_walk` becomes server-side post-processing rather than an LLM tool in V1.

- **MODIFY** the `data-ingest` capability to (a) rename the provenance enum field `source_id` → `source_type` for cross-spec consistency with citations; (b) reduce the V1 `source_type` enum to `wikipedia | wikidata | osm` only — `chronicling-america`, `nypl`, `nyc-open-data`, `mta`, `noaa` are deferred with their respective ingestors; (c) defer the bronze/silver/gold three-tier separation to v2 — V1 ingests directly into a single Postgres tier; (d) reword the bulk-NLP requirement so it commits to `complexity="simple"` without naming a specific underlying model.

- **MODIFY** the `map-engine` capability to drop `onCameraChange` from the V1 minimum interface. V1 drives the camera deterministically via `flyTo`; observation of user-driven camera changes is deferred to v2.

- **ADD** `db-migrations` capability with **single execution surface** for V1: all migrations apply via `docker-entrypoint-initdb.d` on first volume creation. The runtime migration applier (`schema_migrations` ledger, idempotent re-application, advisory lock) is deferred to v2 when a deployed instance with persistent data needs in-place upgrades.

- **DEFER** to v2: `/agent/ask` over WebSocket. V1 streams narration over **Server-Sent Events (SSE)** instead — fewer moving parts, simpler proxy config, native browser reconnect, and the only V1 capability that would benefit from WS (mid-stream interrupt) is explicitly out of scope. Swapping back to WS later is a half-day refactor.

- **DEFER** to v2: VPS deployment (§14), live data sources (§13.1-3 NYC Open Data + MTA GTFS-RT + NOAA), retrieval P@5/R@5 evaluation (§13.4), user study (§13.5), APScheduler for the worker (§6.5). V1 demo runs on grader's localhost via `docker compose up`; V1 evaluation is qualitative, hand-graded over ~5 walks.

## Capabilities

### New Capabilities

- `embeddings`: deterministic 384-dim sentence embeddings produced inside the api container with no external HTTP dependency, used to populate `pgvector` columns for semantic retrieval.
- `db-migrations`: an explicit, file-based, idempotent migration mechanism scoped to the size of this project — no Alembic.

### Modified Capabilities

- `llm-router`: relax the "local backend = `llama.cpp`" requirement. The router now talks to two OpenAI-compatible HTTP endpoints whose URLs and models are env-configured. For V1, both terminate at OpenRouter; no on-device daemon is part of the V1 contract.
- `agent-tools`: (a) lock the citation JSON shape with five required fields (`span` is opaque to the verifier); (b) reduce V1 to a single LLM tool (`search_places`); (c) move `plan_walk` to server-side post-processing.
- `data-ingest`: (a) rename `source_id` → `source_type`; (b) trim V1 enum to `wikipedia | wikidata | osm`; (c) defer bronze/gold tiers to v2; (d) replace "Local Gemma-4 is the default for bulk NLP" with backend-agnostic "Bulk NLP routes through router `simple` tier".
- `map-engine`: remove `onCameraChange` from the V1 minimum interface; remaining methods unchanged.

## Impact

- **Filesystem**: adds `LICENSE`, `apps/api/app/embeddings/`, `apps/api/app/db/migrations/` SQL files (per the existing §10.3-10.4 plan but with locked schema). Renames `LLAMA_CPP_*` env vars to `LOCAL_LLM_*` in `.env.example` and `apps/api/app/config.py`.
- **Runtime dependencies**: adds `sentence-transformers` and `huggingface_hub` to `apps/api/pyproject.toml`. Cold start downloads ~30 MB of model weights to a mounted cache volume.
- **External services**: V1 depends only on OpenRouter for LLM calls. The Win11 llama-server is removed from V1 documentation (it's not "alternate config" — it's "not in V1"). On-device hosting is tracked as a v2 swap-in via the same env vars.
- **Cost**: dev/test runs go to `$0` while we're on the free Gemma slug. The §13.6 paid eval is opt-in, scoped, and budgeted separately.
- **Backwards compatibility**: the existing tests in `apps/api/tests/test_llm_router.py` use fake adapters and continue to pass without modification — the router's interface is unchanged, only the env-driven backend mapping moves.
