## 1. OpenSpec Artifacts

- [x] 1.1 Write `proposal.md`
- [x] 1.2 Write `design.md`
- [x] 1.3 Write `tasks.md` (this file)
- [x] 1.4 Write MODIFIED `specs/llm-router/spec.md`
- [x] 1.5 Write ADDED `specs/embeddings/spec.md`
- [x] 1.6 Write ADDED `specs/db-migrations/spec.md`
- [x] 1.7 Write MODIFIED `specs/agent-tools/spec.md` (citation contract locked, V1 single-tool surface, span field opaque to verifier)
- [x] 1.8 Write MODIFIED `specs/data-ingest/spec.md` (source_type rename, V1 enum trim, single-tier ingestion, backend-agnostic bulk NLP)
- [x] 1.9 Write MODIFIED `specs/map-engine/spec.md` (drop `onCameraChange` from V1 minimum interface)
- [x] 1.10 Run `openspec validate swap-llm-tiers-and-lock-mvp-decisions --strict` and fix any issues

## 2. Environment & Config Surface (V1 = online-only via OpenRouter)

- [x] 2.1 Update root `.env.example`: rename `LLAMA_CPP_*` → `LOCAL_LLM_*`, point both `LOCAL_LLM_BASE_URL` and `OPENROUTER_BASE_URL` at OpenRouter, default models to `google/gemma-4-31b-it:free`, add `EMBEDDING_*` vars, drop the on-device "Configuration B" block
- [x] 2.2 Create user's local `.env` with the provided OpenRouter key (V1 online-only — no Win11 host setup required)
- [x] 2.3 Update `apps/api/app/config.py` `Settings` to expose `LOCAL_LLM_BASE_URL`, `LOCAL_LLM_MODEL`, `LOCAL_LLM_API_KEY` (replacing the `LLAMA_CPP_*` fields) and `EMBEDDING_MODEL`, `EMBEDDING_DIM`, `EMBEDDING_BATCH_SIZE`
- [x] 2.4 Update `apps/api/app/main.py` lifespan to read the new var names when constructing the router
- [x] 2.5 Update `apps/api/app/llm/router.py::build_llm_router` parameter names to `local_*` (drop the `llama_cpp_*` kwargs entirely — V1 has no on-device path to preserve)
- [x] 2.6 Re-run `apps/api/tests/test_llm_router.py` to confirm router unit tests still pass with renamed env

## 3. Repository Hygiene

- [x] 3.1 Add top-level `LICENSE` (MIT, copyright user 2026)
- [x] 3.2 Update root `README.md`: remove "Code license TBD" wording (license now MIT)
- [x] 3.3 Update root `README.md`: delete the "Windows-side llama.cpp host" section and the `llama-server` requirement from the prereqs (V1 online-only); add a one-line note that on-device LLM is v2 work
- [x] 3.4 Update `apps/api/README.md` to reference the new env var names
- [x] 3.5 Update `docker-compose.yml` if it currently propagates `LLAMA_CPP_*` env vars into the api/worker services; remove `extra_hosts: host-gateway` if it was only there for llama.cpp

## 4. Cross-link to initial-palimpsest-scaffold (apply V1 cuts)

### 4.1 Database schema and embeddings (§10)

- [x] 4.1.1 In `initial-palimpsest-scaffold/tasks.md`, edit §10.4 to declare `vector(384)` (was `vector(768)`)
- [x] 4.1.2 Edit §10.3 to reference SQL-only **init-time** migration mechanism (no Alembic, no runtime applier — V1 = single execution surface via `docker-entrypoint-initdb.d`)
- [x] 4.1.3 Add §10.5 "create `apps/api/app/embeddings/` module + sentence-transformers singleton on app.state"

### 4.2 Agent surface (§9) — single-tool V1

- [x] 4.2.1 Edit §9.1 / §9.2 to keep tool base + JSON Schema infrastructure (still needed for one tool)
- [x] 4.2.2 Keep §9.3 `search_places` as the only V1 LLM tool
- [x] 4.2.3 Mark §9.4 `spatial_query`, §9.5 `historical_lookup`, §9.6 `current_events` as **deferred to v2**
- [x] 4.2.4 Edit §9.7 `plan_walk`: implement as **server-side post-processing** (PostGIS routing pass after agent emits `citations[]`), NOT as an LLM-callable tool
- [x] 4.2.5 Edit §9.8 agent loop: register only `search_places` in the LLM `tools` parameter; turn cap stays 6 to allow refinement turns
- [x] 4.2.6 Edit §9.9: change `/agent/ask` from WebSocket to **Server-Sent Events** (`StreamingResponse(media_type="text/event-stream")`); update nginx.conf with `proxy_buffering off; proxy_read_timeout 86400s`

### 4.3 Ingestion (§11) — Wikipedia + OSM only for V1

- [x] 4.3.1 Edit §11.1 to use renamed `source_type` field (was `source_id`); set value to `"wikipedia"`
- [x] 4.3.2 Mark §11.2 Chronicling America as **deferred to v2**
- [x] 4.3.3 Mark §11.3 NYPL Digital Collections as **deferred to v2**
- [x] 4.3.4 Keep §11.4 OSM Overpass for V1 (street geometries needed for routing); set `source_type="osm"`
- [x] 4.3.5 Edit §11.5: "Embedding generation pipeline (BAAI/bge-small-en-v1.5 in api container)" — drop "local Gemma-4 by default, bge-small fallback"
- [x] 4.3.6 Keep §11.6 provenance/citation linkage end-to-end check

### 4.4 Walk planner (§12) — server-side, not agent tool

- [x] 4.4.1 Edit §12.1 to clarify `plan_walk` runs server-side after agent completion; takes the `place_ids` referenced in `citations[]` and returns an ordered route
- [x] 4.4.2 Keep §12.2 narration generator with citation contract — narration is the agent's terminal response, no separate "narrate" tool
- [x] 4.4.3 Keep §12.3 citation verifier — verifies `doc_id`, `source_type`, `retrieval_turn`; `span` opaque
- [x] 4.4.4 Edit §12.4: SSE streaming, not WebSocket
- [x] 4.4.5 Keep §12.5 frontend route + marker + flyTo rendering (uses ordered list from server-side §4.4.1)

### 4.5 Live data, eval, deploy — all deferred to v2

- [x] 4.5.1 Mark §13.1 NYC Open Data events ingestion **deferred to v2**
- [x] 4.5.2 Mark §13.2 MTA GTFS-RT **deferred to v2**
- [x] 4.5.3 Mark §13.3 NOAA Weather **deferred to v2**
- [x] 4.5.4 Replace §13.4 "P@5/R@5 + factuality LLM-judge + latency percentiles" with V1 "qualitative hand-graded review of 5 walks, capture screenshots and citation correctness rate"
- [x] 4.5.5 Mark §13.5 user study **deferred to v2** (post-grading)
- [x] 4.5.6 Keep §13.6 router cost analysis (single env-var flip from free to paid models for ~10-walk sample)
- [x] 4.5.7 Keep §13.7 final report draft + agentic-engineering chapter from session-log JSONL
- [x] 4.5.8 Keep §13.8 30-second demo video
- [x] 4.5.9 Mark all of §14 (VPS deploy) **deferred to v2**

### 4.6 Worker scheduling (§6.5) — deferred to v2

- [x] 4.6.1 Edit §6.5 to keep heartbeat loop only; mark APScheduler integration **deferred to v2**. V1 ingestion runs as one-shot CLI (`python -m app.ingest.wikipedia run`)

## 5. Validation

- [x] 5.1 `make setup` from a clean checkout (no Win11 prerequisites). *api venv created and `pip install -e '.[dev]'` succeeds; worker venv requires `uv` for the editable `palimpsest-api` source — pre-existing tooling note.*
- [x] 5.2 `make up` and confirm api comes up healthy with the new env names — note: `make up` MUST succeed without any `llama-server` process running anywhere. *`docker compose up postgres redis api` brings all three containers healthy; `/health` returns 200 with no on-device daemon. Required a one-line fix to `app/logging.py` (`PrintLoggerFactory` → `stdlib.LoggerFactory`) — `add_logger_name` needs a stdlib BoundLogger.*
- [x] 5.3 `curl -X POST http://localhost:8000/llm/chat -d '{"messages":[{"role":"user","content":"hi"}],"complexity":"simple"}'` returns content from the configured `LOCAL_LLM_MODEL`. *Validated end-to-end after the user funded their OpenRouter account and switched models to `moonshotai/kimi-k2.6`. Response: `backend="local"`, `model="moonshotai/kimi-k2.6-20260420"`, `content=" pong"`, latency 1.16s, cost $0.0001248.*
- [x] 5.4 Same call with `"complexity":"complex"` returns content from the configured complex model. *Validated. Response: `backend="openrouter"`, `model="moonshotai/kimi-k2.6-20260420"`, real billed response, 33.9s latency (kimi-k2.6 is an extended-thinking model), cost $0.000128.*
- [x] 5.5 `make test` passes from `apps/api/.venv`. *13/13 pytest tests pass.*
- [x] 5.6 `python -m app.meta.cli seed` writes a `SessionRecord` for this change. *Used `append` (the seed subcommand is hardcoded to the original scaffold record); SessionRecord written to `logs/claude-sessions/2026-04-28.jsonl`.*
- [x] 5.7 Verify the V1 contract: kill no on-device process, set no Win11 firewall rule, end-to-end demo still works. *No `llama-server` running anywhere; `extra_hosts: host-gateway` removed; api dispatches directly to OpenRouter.*
- [ ] 5.8 SSE smoke test: `curl -N http://localhost:8000/agent/ask?q=...` returns `text/event-stream` chunks once §4.2.6 / §4.4.4 land. *Deferred: `/agent/ask` endpoint is part of `initial-palimpsest-scaffold` §9.9 (still pending). This swap-llm-tiers change only specifies it MUST be SSE when implemented; the endpoint itself is built later.*
