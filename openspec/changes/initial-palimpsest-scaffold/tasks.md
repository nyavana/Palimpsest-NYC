## 1. OpenSpec Artifacts

- [x] 1.1 Write `proposal.md` with pitch, capabilities, and impact
- [x] 1.2 Write `design.md` with architecture, decisions, and risks
- [x] 1.3 Write `tasks.md` (this file)
- [x] 1.4 Write `specs/llm-router/spec.md`
- [x] 1.5 Write `specs/map-engine/spec.md`
- [x] 1.6 Write `specs/data-ingest/spec.md`
- [x] 1.7 Write `specs/agent-tools/spec.md`
- [x] 1.8 Run `openspec validate initial-palimpsest-scaffold --strict` and fix any issues

## 2. Monorepo Foundation

- [x] 2.1 Create root `README.md` with project overview, quickstart, and demo pitch
- [x] 2.2 Create root `.gitignore` covering Python, Node, logs, .env, ingestion raw/bronze tiers
- [x] 2.3 Create `.env.example` with all required variables documented
- [x] 2.4 Create root `Makefile` with `make dev`, `make up`, `make down`, `make logs`, `make fmt`, `make lint`, `make test` targets
- [x] 2.5 Create root `docker-compose.yml` with postgres (postgis+pgvector), redis, api, worker, web services
- [x] 2.6 Create `logs/claude-sessions/.gitkeep` to reserve the session-log directory

## 3. FastAPI Backend Scaffold

- [x] 3.1 Create `apps/api/pyproject.toml` with dependencies (fastapi, uvicorn, sqlalchemy, asyncpg, pgvector, httpx, redis, structlog, pydantic-settings, tenacity)
- [x] 3.2 Create `apps/api/Dockerfile` (Python 3.12 slim, non-root user)
- [x] 3.3 Create `apps/api/app/main.py` FastAPI application factory, lifespan, CORS, exception handlers
- [x] 3.4 Create `apps/api/app/config.py` with `pydantic-settings` loading from env
- [x] 3.5 Create `apps/api/app/logging.py` structlog JSON setup with request-id middleware
- [x] 3.6 Create `apps/api/app/routes/health.py` exposing `/health` (liveness) and `/ready` (DB+Redis ping)

## 4. LLM Router Capability

- [x] 4.1 Create `apps/api/app/llm/models.py` with `ChatRequest`, `ChatResponse`, `Complexity`, `Message`, `ToolCall` dataclasses
- [x] 4.2 Create `apps/api/app/llm/adapters.py` with `OpenRouterAdapter` and `LlamaCppAdapter` (OpenAI-compatible HTTP clients)
- [x] 4.3 Create `apps/api/app/llm/router.py` implementing complexity-aware dispatch, circuit breaker, fallback ladder
- [x] 4.4 Create `apps/api/app/llm/cache.py` Redis-backed response cache keyed by canonicalized request hash
- [x] 4.5 Create `apps/api/app/llm/telemetry.py` emitting structured records for every call
- [x] 4.6 Create `apps/api/app/routes/llm.py` exposing `/llm/chat` for smoke testing
- [x] 4.7 Write unit tests for router decision logic against a fake adapter

## 5. Meta-Instrumentation Harness

- [x] 5.1 Create `apps/api/app/meta/session_log.py` with `SessionLogger` class writing JSONL
- [x] 5.2 Define `SessionRecord` schema with `schema_version: 1`
- [x] 5.3 Create `apps/api/app/meta/cli.py` for manually appending records (`python -m app.meta.cli append ...`)
- [x] 5.4 Expose `/internal/metrics` endpoint aggregating tokens, cost, and outcome counts
- [x] 5.5 Write a helper that seeds the log with the first entry for this very scaffolding session

## 6. Data Ingestion Stubs

- [x] 6.1 Create `apps/api/app/ingest/__init__.py` with a base `Ingestor` protocol
- [x] 6.2 Create `apps/api/app/ingest/wikipedia.py` stub with scope filter (lat/lon bbox for Morningside + UWS)
- [x] 6.3 Create `apps/api/app/ingest/scope.py` exposing the v1 bounding box as module constants
- [x] 6.4 Create `apps/api/app/ingest/README.md` documenting ingestion tiers (raw/bronze/silver/gold)
- [x] 6.5 Create `apps/worker/worker/main.py` that runs a heartbeat loop. **V1 scope**: heartbeat only; APScheduler integration **deferred to v2** (see `swap-llm-tiers-and-lock-mvp-decisions`). V1 ingestion runs as one-shot CLI: `python -m app.ingest.wikipedia run`.

## 7. Frontend Scaffold

- [x] 7.1 Create `apps/web/package.json` with react, react-dom, vite, typescript, tailwindcss, maplibre-gl
- [x] 7.2 Create `apps/web/vite.config.ts`, `tsconfig.json`, `tsconfig.node.json`, `tailwind.config.ts`, `postcss.config.js`
- [x] 7.3 Create `apps/web/index.html`, `apps/web/src/main.tsx`, `apps/web/src/App.tsx`, `apps/web/src/index.css`
- [x] 7.4 Create `apps/web/Dockerfile` (multi-stage: node build → nginx serve)
- [x] 7.5 Create `apps/web/nginx.conf` proxying `/api` to the backend service
- [x] 7.6 Create `apps/web/.env.example`

## 8. Map Engine Capability

- [x] 8.1 Create `apps/web/src/map/types.ts` with `Viewport`, `Marker`, `PathStyle`, `LatLng` type definitions
- [x] 8.2 Create `apps/web/src/map/MapEngine.ts` interface
- [x] 8.3 Create `apps/web/src/map/engines/MaplibreEngine.ts` implementation using `maplibre-gl`
- [x] 8.4 Create `apps/web/src/map/engines/GoogleTilesEngine.ts` stub throwing `NotImplementedError`
- [x] 8.5 Create `apps/web/src/map/index.ts` factory reading `VITE_MAP_ENGINE` env var
- [x] 8.6 Create `apps/web/src/components/MapView.tsx` that mounts the engine on a container div
- [x] 8.7 Add ESLint rule forbidding `maplibre-gl` imports outside `apps/web/src/map/engines/` *(created manually via option B — config-protection hook blocks Claude from writing lint configs)*

## 9. Agent Tools (stub surface)

> **V1 cuts (per `swap-llm-tiers-and-lock-mvp-decisions`)**: tool surface reduced to a single LLM-callable tool (`search_places`); `plan_walk` becomes server-side post-processing, not a tool; `/agent/ask` streams over Server-Sent Events instead of WebSocket.

- [ ] 9.1 Create `apps/api/app/agent/__init__.py` *(keeps tool base + JSON Schema infrastructure even though only one V1 tool is registered — the protocol is reused by §12.1 server-side `plan_walk` post-processing)*
- [ ] 9.2 Create `apps/api/app/agent/tools/base.py` with `Tool` base class and JSON schema helpers
- [ ] 9.3 Create `apps/api/app/agent/tools/search_places.py` stub returning empty results — **only V1 LLM-callable tool**
- [ ] 9.4 ~~Create `apps/api/app/agent/tools/spatial_query.py` stub~~ **Deferred to v2.**
- [ ] 9.5 ~~Create `apps/api/app/agent/tools/historical_lookup.py` stub~~ **Deferred to v2.**
- [ ] 9.6 ~~Create `apps/api/app/agent/tools/current_events.py` stub~~ **Deferred to v2.**
- [ ] 9.7 Implement `plan_walk` as **server-side post-processing** (PostGIS routing pass after the agent emits its final `citations[]`), NOT as an LLM-callable tool. Lives at `apps/api/app/agent/walk.py` (or `app/walk/`), invoked by the SSE handler before terminal narration is sent.
- [ ] 9.8 Create `apps/api/app/agent/loop.py` with the tool-calling loop. **V1**: register only `search_places` in the LLM `tools` parameter; turn cap remains 6 to allow multi-turn refinement (broad query → narrowed query).
- [ ] 9.9 Create `apps/api/app/routes/agent.py` exposing `/agent/ask` as a **Server-Sent Events** endpoint (`StreamingResponse(media_type="text/event-stream")`). Update `apps/web/nginx.conf` with `proxy_buffering off; proxy_read_timeout 86400s;` for the `/api/agent/ask` location.

## 10. Database Schema (stubs)

> **V1 migration mechanism (per `swap-llm-tiers-and-lock-mvp-decisions`)**: SQL files in `apps/api/app/db/migrations/` are mounted into the postgres container via `docker-entrypoint-initdb.d` and run on first volume creation. **No Alembic, no runtime applier.** Schema changes during V1 dev require `make nuke && make up`. Idempotent runtime applier with `schema_migrations` ledger is deferred to v2.

- [x] 10.1 Create `apps/api/app/db/engine.py` async SQLAlchemy engine and session factory
- [x] 10.2 Create `apps/api/app/db/models.py` with `Place`, `Document` ORM classes (`Embedding` is a typed `Vector(384)` column, not a separate table — locked V1 schema)
- [x] 10.3 Create `apps/api/app/db/migrations/0001_init.sql` enabling `postgis`, `pgvector`, `pg_trgm`. Mount this directory into postgres via `docker-entrypoint-initdb.d` (single execution surface for V1).
- [x] 10.4 Create `apps/api/app/db/migrations/0002_places.sql` with the `places` and `documents` tables. Embedding columns declared as **`vector(384)`** (locked to `BAAI/bge-small-en-v1.5` output dim).
- [x] 10.5 Create `apps/api/app/embeddings/` module with a `sentence-transformers` singleton attached to `app.state.embedder` at startup; reads `EMBEDDING_MODEL`, `EMBEDDING_DIM`, `EMBEDDING_BATCH_SIZE` from settings; first-run downloads to mounted `/cache/huggingface`.

## 11. Full Ingestion Pipelines (Week 2)

> **V1 source enum (per `swap-llm-tiers-and-lock-mvp-decisions`)**: `wikipedia | wikidata | osm`. Provenance field renamed `source_id` → `source_type` to match the citation contract.

- [ ] 11.1 Wikipedia/Wikidata: fetch + geocode + insert for scope bbox; provenance row uses `source_type="wikipedia"`.
- [ ] 11.2 ~~Chronicling America: stream download, filter, local-Gemma OCR cleanup + geocoding~~ **Deferred to v2.**
- [ ] 11.3 ~~NYPL Digital Collections: API fetch, filter, store~~ **Deferred to v2.**
- [ ] 11.4 OpenStreetMap: Overpass query for scope, extract POIs (street geometries needed for §12.1 routing); provenance row uses `source_type="osm"`.
- [ ] 11.5 Embedding generation pipeline: `BAAI/bge-small-en-v1.5` via `sentence-transformers` running CPU-only inside the api container (V1 locked default — see §10.5).
- [ ] 11.6 Provenance and citation linking verified end to end (`source_type`, `doc_id`, `source_url`, `span`, `retrieval_turn`).

## 12. Agent Loop + Walk Planner (Week 3)

- [ ] 12.1 Implement `plan_walk` as a **server-side post-processing step** (not an LLM tool): after the agent emits its terminal narration with `citations[]` referencing N `place_ids`, run a deterministic PostGIS routing pass to produce an ordered walking route. Returned as part of the `/agent/ask` SSE stream's terminal frame.
- [ ] 12.2 Implement narration generator with mandatory citation JSON contract — narration is the agent's terminal response; no separate "narrate" tool. Five required Citation fields: `doc_id`, `source_url`, `source_type`, `span`, `retrieval_turn`.
- [ ] 12.3 Implement citation verifier pass — verifies `doc_id`, `source_type`, `retrieval_turn`; **`span` is opaque to the verifier** (per locked contract).
- [ ] 12.4 Wire **Server-Sent Events** streaming of narration chunks to the frontend (replaces WebSocket per `swap-llm-tiers-and-lock-mvp-decisions`). Frontend uses native `EventSource`.
- [ ] 12.5 Frontend: render walk as a path + stop markers + fly-to animation per stop, using the ordered route from §12.1.

## 13. Live Data + Evaluation + Paper (Week 4)

- [ ] 13.1 ~~NYC Open Data events ingestion (daily cron via worker)~~ **Deferred to v2.**
- [ ] 13.2 ~~MTA GTFS-RT subway status feed~~ **Deferred to v2.**
- [ ] 13.3 ~~NOAA Weather overlay~~ **Deferred to v2.**
- [ ] 13.4 V1 evaluation: **qualitative hand-graded review of 5 walks**, capture screenshots and citation correctness rate. (P@5/R@5 + factuality LLM-judge + latency percentiles deferred to v2.)
- [ ] 13.5 ~~User study: 5-10 classmates rate 3 walks each on accuracy and interestingness~~ **Deferred to v2 (post-grading).**
- [ ] 13.6 Router cost analysis: ~10-walk sample comparing free Gemma vs paid OpenAI models (single env-var flip of `OPENROUTER_STANDARD_MODEL` / `OPENROUTER_COMPLEX_MODEL`).
- [ ] 13.7 Final report draft with agentic-engineering chapter sourced from session-log JSONL.
- [ ] 13.8 30-second demo video.

## 14. Deployment — **All deferred to v2**

V1 demo runs on the grader's localhost via `docker compose up`. VPS bring-up is tracked separately when v2 work resumes.

- [ ] 14.1 ~~VPS bootstrap playbook (docker, caddy, unattended-upgrades)~~ **Deferred to v2.**
- [ ] 14.2 ~~Postgres tuning for 2.5 GB RAM (shared_buffers, work_mem, max_connections)~~ **Deferred to v2.**
- [ ] 14.3 ~~pg_dump from dev silver to VPS gold~~ **Deferred to v2.**
- [ ] 14.4 ~~Caddy reverse proxy with automatic HTTPS~~ **Deferred to v2.**
- [ ] 14.5 ~~Smoke test on VPS end-to-end~~ **Deferred to v2.**
