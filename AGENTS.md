# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project

**Palimpsest NYC** — agentic LLM walking-tour app for Morningside Heights & UWS. Columbia EECS E6895 final project. The codebase is being built end-to-end by Codex under a single human reviewer; full session telemetry is captured to `logs/Codex-sessions/*.jsonl` for the report's empirical analysis of agentic software engineering. V1 is online-only — every LLM call terminates at OpenRouter; on-device LLM hosting is a v2 swap-in via the same env-driven router-tier URLs.

## Common commands

Bring up / tear down the full Docker stack (postgres+postgis+pgvector, redis, api, worker, web):

```bash
make up           # build and start detached
make dev          # start attached with live logs
make logs         # tail container logs
make down         # stop containers (volumes preserved)
make nuke         # stop AND drop volumes — required after schema changes (see below)
make ps
make api-shell    # bash inside the api container
make db-shell     # psql inside the postgres container
```

Run from the published images (no local build):

```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
# pin a release: PALIMPSEST_TAG=v0.1.0 docker compose -f docker-compose.prod.yml up -d
```

The three images live at `ghcr.io/nyavana/palimpsest-{api,web,postgres}` and are published by `.github/workflows/docker-publish.yml` on push to `main`, on `v*` tags, on PRs into `main` (PR builds tagged with `sha-<short>` only — they don't move `latest`), and on manual `workflow_dispatch`.

Local Python dev (each subproject owns its own `.venv`; prefer `uv`):

```bash
make setup                            # creates .venv in apps/api and apps/worker, npm install in apps/web
source apps/api/.venv/bin/activate    # activate api venv for interactive work
```

Quality:

```bash
make fmt          # ruff format (py) + prettier (web)
make lint         # ruff check (py) + eslint (web)
make test         # pytest in apps/api
# single-test forms (run from apps/api/ with .venv active):
pytest tests/test_agent_loop.py -q
pytest tests/test_agent_loop.py::test_some_specific_case -q
```

Frontend-only (run inside `apps/web/`):

```bash
npm run dev        # vite dev server on :5173
npm run build      # tsc -b && vite build
npm run typecheck
npm run lint
```

Corpus ingestion is automatic. The `init-ingest` compose service preloads the embedder weights into `hf-cache` and runs OSM + Wikipedia ingest on first `make up`; both checks short-circuit if `places` already has rows for that `source_type`, so re-up cycles stay fast. `make nuke && make up` drops the postgres volume and forces re-ingestion — that's the path you take after touching `app/ingest/*` (for example, expanding OSM tags). The CLI form remains available as a manual override:

```bash
docker compose exec api python -m app.ingest.cli osm run
docker compose exec api python -m app.ingest.cli wikipedia run
```

End-to-end smoke test of the agent SSE endpoint (V1.1: POST + JSON body):

```bash
curl -N -X POST -H "Content-Type: application/json" \
  -d '{"q":"Tell me about a gothic cathedral in Morningside Heights"}' \
  http://localhost:8000/agent/ask
# Expect SSE frames: turn → tool_call → tool_result → narration → citations → [walk?] → done
# `history` is an optional list of {role, content} prior user/assistant turns;
# tool/system messages stay server-owned and are rejected if posted by clients.

# BYOK mode (no OPENROUTER_API_KEY in .env): pass the user's credentials in
# X-LLM-Credentials, base64(JSON({api_key, model, base_url?})):
HEADER=$(printf '%s' '{"api_key":"sk-...","model":"openai/gpt-5.4-mini"}' | base64 -w0)
curl -N -X POST -H "Content-Type: application/json" -H "X-LLM-Credentials: $HEADER" \
  -d '{"q":"..."}' http://localhost:8000/agent/ask
```

OpenSpec (spec-driven workflow used for change proposals):

```bash
make spec-list
make spec-show          # currently shows initial-palimpsest-scaffold
make spec-validate      # currently validates initial-palimpsest-scaffold
openspec show eval-depth-and-corpus-expansion
openspec validate eval-depth-and-corpus-expansion --strict
```

## Architecture

Monorepo with three apps under `apps/`, a static marketing landing page under `site/` (plain HTML/CSS/JS, no build), and a single root `docker-compose.yml`. The seam between the apps is the OpenAPI surface in `apps/api` (`/health`, `/llm/chat`, `/agent/ask` SSE, `/food/discover`, `/internal/metrics`).

Compose lifecycle: `postgres` → `init-ingest` (one-shot, preloads embedder + ingests if tables empty) → `api` (gated on `init-ingest: service_completed_successfully`); `osrm-prepare` → `osrm`; `worker` (heartbeat) and `web` start in parallel.

### `apps/api` — FastAPI backend (Python 3.12)

Wired in `app/main.py::create_app()` with a single async `lifespan` that builds and stores all long-lived singletons on `app.state`:

- `app.state.llm_router` — cost-aware router (`app/llm/router.py`) with two tiers (`local` and `openrouter`), each with its own circuit breaker (3 fails / 60s window / 30s cooldown). Complexity dispatch: `simple` → local tier, `standard`/`complex` → cloud tier. **In V1 both tiers point at OpenRouter** — the split exists so v2 can repoint `LOCAL_LLM_BASE_URL` at an on-device endpoint without code change. Cache is keyed by canonicalized request hash with TTLs that vary by complexity. **BYOK (V1.1):** when `OPENROUTER_API_KEY` is unset, this singleton is `None` and `app.state.byok_required` is `True`. `/agent/ask` then requires an `X-LLM-Credentials` header carrying base64(JSON({api_key, model, base_url?})), and the route builds a per-request router via `LLMRouter.with_user_credentials(...)` (or `build_byok_router(...)` when no singleton exists). The per-request router has fresh breakers and a no-op cache so a user's bad key cannot trip shared state.
- `app.state.embedder` — `BAAI/bge-small-en-v1.5` sentence-transformer singleton (CPU-only, 384-dim). Weights live in the `hf-cache` volume mounted at `/cache/huggingface`.
- `app.state.db_engine` / `db_session_factory` — async SQLAlchemy 2 over asyncpg. **Schema is owned by `app/db/migrations/*.sql`**, applied by the postgres entrypoint on first volume init in lex order. ORM models in `app/db/models.py` are read-only mirrors — never call `Base.metadata.create_all` in app code paths. Schema changes require `make nuke && make up`.
- `app.state.agent_tool_registry` / `agent_loop_builder` — registers **two tools**: `search_places` (retrieval) and `plan_walk` (LLM-callable OSM-graph router, chosen by the LLM only for tour/route queries); any other tool name returns an `unknown_tool` error message back to the LLM and the loop continues.
- `app.state.session_logger` — meta-instrumentation harness (`app/meta/`) that writes per-session jsonl files for the report's cost/cycle-time analysis.

Request flow: `RequestIdMiddleware` binds an `X-Request-ID` to structlog contextvars for the lifetime of the request and clears it on the way out. CORS allow-origins come from `API_CORS_ORIGINS`.

### Agent loop (locked V1 contract)

`apps/api/app/agent/loop.py` drives the conversation. **Critical invariants — do not loosen without a spec change:**

- Hard turn cap of 7. Hitting the cap is a hard failure (`AgentLoopError`).
- The final turn strips the tool surface and adds a "stop searching, emit JSON now" directive, with `response_format=json` and `max_tokens=8192` (vs. 2048 for tool-call turns) — this gives extended-thinking models like `kimi-k2.6` enough budget for both reasoning and the final JSON.
- Terminal response is JSON `{narration, citations[]}` with the **strict five-field citation contract**: `doc_id`, `source_url`, `source_type` ∈ {`wikipedia`, `wikidata`, `osm`}, `span`, `retrieval_turn`. Verified by `app/agent/citations.py::verify_citations` against a `RetrievalLedger` of every doc returned in this conversation.
- One verification retry: on first citation failure, append a corrective user message and re-prompt. If retry also fails, return the response with `verified=False` and a `warning` rather than crashing.
- `run_streamed()` yields `AgentEvent` objects (`turn`, `tool_call`, `tool_result`, `tool_error`, `narration`, `citations`, `warning`, `done`); `run()` is just the consuming wrapper. The SSE route (`app/routes/agent.py`) frames events as `event: <type>\ndata: <json>\n\n` and if the agent called `plan_walk` during the conversation, the SSE handler relays the tool's most recent successful result as the `walk` frame after `citations` and before the terminal `done`; otherwise no `walk` frame is emitted (informational queries no longer trigger a default 1-stop walk).
- `plan_walk` auto-enriches its route by calling `app/agent/walk.py::discover_pois_along_route()` and splicing the matches into the response under `discovered_stops[]`; this happens server-side inside the tool, so the agent does not need to ask for it.
- `/agent/ask` accepts a multi-turn `history: [{role, content}, ...]` in the JSON body. The `ConversationHistoryMessage` schema deliberately rejects tool/system roles — those stay server-owned.

### `/food/discover` — structured place picker

`POST /food/discover` (in `app/routes/places.py`) is the second user-facing route. It runs a hybrid lexical+vector search over `places` filtered to OSM food amenities (`restaurant|cafe|fast_food|bar|pub|bakery|ice_cream` plus `shop=bakery|coffee`) and returns a list of selectable candidates. The frontend uses it for "I want coffee near Columbia"-style prompts; the locked `/agent/ask` JSON contract is intentionally untouched (see `docs/food-discovery/README.md` for the design rationale and the chat-pane intent routing).

### `apps/api/app/ingest` — Ingestion (auto on first up, CLI on demand)

`python -m app.ingest.cli {wikipedia|osm} run` is the manual entry point. The same code is invoked automatically by `app/ingest/init_runner.py` inside the `init-ingest` compose service when the corresponding `places.source_type` partition is empty — so a fresh `make up` ends with a populated corpus without any manual CLI step. Sources upsert into `places` + `documents`, with provenance fields (`doc_id`, `source_type`, `source_url`, `source_retrieved_at`, `license`) chosen so a row's provenance becomes its citation with no field renaming. The `RawCache` key includes a digest of the actual Overpass query text (not just the bbox), so changing the OSM tag set invalidates the cache automatically.

### `apps/web` — React + Vite + TS + MapLibre

`apps/web/src/components/MapView.tsx` consumes a `MapEngine` interface so the concrete engine (MapLibre today, Google Photorealistic 3D Tiles later) is selected from `VITE_MAP_ENGINE` and swappable in a single factory file (`src/map/`). Tailwind, ESLint, Prettier preconfigured. Dockerfile builds a static bundle behind nginx (port 80 in container, 5173 on the host).

The SSE consumer lives in `src/state/sse.ts` (fetch + ReadableStream POST against `/agent/ask` since V1.1) and `src/state/useAgentSession.ts`; UI surfaces are split into `ChatPane`, `Composer`, `NarrationStream`, `CitationList` / `CitationCard`, `WalkTimeline`, `WarningBanner`, the BYOK `SettingsModal` + `SettingsButton`, and (food side flow) `FoodCandidateList` / `FoodCandidateCard` driven by `useFoodDiscovery`. Citation cards, walk stops, and food candidates all share one focus model via `TourFocusContext` — clicking any of them moves the same map marker, and the map calls back through the same context. The map and chat panes share state via `MapEngineContext`, and citations drive `flyTo` as they arrive on the wire — there is no client-side route planning, the SSE `walk` frame is authoritative. Per-session LLM credentials live in `src/state/llmCredentials.ts` (sessionStorage only, never localStorage) and are encoded into the `X-LLM-Credentials` header by `openAgentStream`.

### `apps/worker` — minimal heartbeat (V1)

Same image as the api (`apps/api/Dockerfile`). `worker.main` runs a heartbeat loop. Real ingestion is the CLI invocation above; this exists so v2 can drop in a scheduler without rebuilding the topology.

## Conventions specific to this repo

- **Schema is migrations-first.** `app/db/models.py` is a typed read-only mirror of the SQL files in `app/db/migrations/`. Never use ORM `create_all`; never write a migration that doesn't have a corresponding ORM update.
- **Citation contract is locked.** All five fields are required and `source_type` is closed-set in V1. Adding a source means adding it to `V1_SOURCE_TYPES` and the system prompt in `agent/loop.py` together.
- **Complexity is the only router knob.** Don't bypass `LLMCache` or hand-pick a backend in caller code. Pass `complexity ∈ {simple, standard, complex}`; the router decides backend, cache TTL, and breaker bookkeeping.
- **Embedding dim is locked at 384.** `EMBEDDING_DIM` constant in `models.py` must track `EMBEDDING_DIM` env. Changing the embedder requires a new migration that drops and recreates the `vector(384)` column.
- **Retrieval mode is selected once at lifespan-time.** `settings.retrieval_mode` (`dense` / `hybrid` / `hybrid_reranked`) drives `apps/api/app/retrieval/factory.py::build_retriever`. The same retriever instance is bound to `app.state.retriever_for_internal` so `/internal/retrieve` and the agent's `SearchPlacesTool` share one pipeline — this is what makes the Phase 4/5 eval ablation honest. Don't hand-pick a retriever in caller code, and don't add per-request mode toggles; the shape-contract test (`tests/test_agent_search_places.py::test_search_places_result_shape_is_identical_across_modes`) enforces that the tool result is byte-identical across modes.
- **Each Python subproject owns its own venv.** Don't install into system Python — run `make setup` (uses `uv` if available, else stdlib `venv + pip`).
- **Ruff is the formatter and the linter** for Python; line length 100, target py312, strict mypy. Tests skip a few rules (`PLR2004`, `S101`).
- **OpenSpec is the source of truth for proposals.** Active changes are `initial-palimpsest-scaffold` (V1) and `eval-depth-and-corpus-expansion` (V1.5, complete on 2026-05-12 — see `manhattan-100-eval-complete` tag); locked V1 decisions live in `swap-llm-tiers-and-lock-mvp-decisions`. The route-planning amendment lives in `openspec/changes/archive/2026-05-05-agent-route-planning/`. Per-phase deep-dives in `docs/`.
- **`AGENTS.md` is the Codex-flavored mirror of `CLAUDE.md`.** Substantive changes in either file should land in the other too — they drift easily otherwise.
- **OSRM extract is committed.** `infra/osrm/extract.osm.pbf` (~100 MB, currently the MH+UWS bbox) lives in-repo, so `osrm-prepare` runs end-to-end on `make up` without the BBBike download in the `make extract` target. Widening the bbox means re-extracting and replacing this file. V1.5 corpus expansion deferred this (design risk R8 in `docs/superpowers/specs/2026-05-12-eval-depth-and-corpus-expansion-design.md`); long routes outside the MH+UWS bbox may fail until the extract is widened to match the corpus.

## Status quick-reference

V1 has shipped (commit `e1bc76d`) and continues to accrete features on `main`: FastAPI skeleton, two-tier LLM router, DB + 384-dim embeddings, auto-run Wikipedia + OSM ingestion, two-tool agent loop (`search_places` + `plan_walk`) with along-route POI auto-discovery, citation verifier, SSE endpoint with multi-turn history, React frontend with `flyTo` + shared `TourFocusContext`, BYOK credentials, food discovery side flow, per-session telemetry harness, and a static marketing landing page in `site/`.

**V1.5 shipped 2026-05-12** on `worktree-eval-depth-and-corpus-expansion` (tag `manhattan-100-eval-complete`). Three orthogonal capability blocks landed end-to-end:

- **Manhattan-wide corpus expansion** — `SCOPE_BBOX` widened to Manhattan island; current corpus is **12,858 OSM + 492 Wikipedia places + 456 Wikipedia documents** (verify with `docker compose exec postgres psql -U palimpsest -d palimpsest -c 'SELECT source_type, count(*) FROM places GROUP BY source_type;'`). Re-extract `infra/osrm/extract.osm.pbf` if widening further.
- **Hybrid + reranked retrieval behind `RETRIEVAL_MODE`** — `dense` (V1 default), `hybrid` (dense + `pg_trgm` name similarity via RRF k=60), `hybrid_reranked` (`hybrid` + `BAAI/bge-reranker-base` cross-encoder over the top-N). `apps/api/app/retrieval/factory.py::build_retriever` is the single dispatch point; the reranker singleton is loaded conditionally in the lifespan (`settings.reranker_enabled` or `RETRIEVAL_MODE=hybrid_reranked`). The dense + sparse branches in `HybridRetriever` are **serialized** under a shared `AsyncSession` (SQLAlchemy's no-concurrent-ops-per-session invariant); the test in `apps/api/tests/test_agent_search_places.py::test_search_places_result_shape_is_identical_across_modes` asserts the tool-result is byte-identical across modes so the locked SSE schema doesn't drift.
- **Above-the-API eval harness** — pre-registered 95-question Manhattan bank (tag `eval/manhattan-100-v1`), LLM-judge over OpenRouter (`docs/eval/scripts/judge_run.py`, pinned to `openai/gpt-5.4-mini` in this run), 5-row ablation table at `docs/eval/results/ablation_table.md`, per-region/per-source CSVs + PNGs, accuracy-vs-latency Pareto, GRR table for out-of-scope subset. Full methodology and caveats in `docs/eval/manhattan-100-results.md`. The locked V1 contract (7-turn cap, JSON terminal, five-field citations, one corrective retry, SSE event names) was not relaxed.

V2 work (on-device LLM endpoint, additional live data sources, VPS deploy + scheduler in `apps/worker`) remains deferred.

For the architecture diagram and dated deep-dives, see `docs/project-overview.md`, the dated phase notes (`docs/agent-2026-04-28.md`, `docs/db-and-embeddings-2026-04-28.md`, `docs/ingestion-2026-04-28.md`, `docs/swap-llm-tiers-2026-04-28.md`, `docs/route-planning-2026-05-04.md`), the food side flow (`docs/food-discovery/README.md`), the V1 evaluation artifacts (`docs/eval/v1-eval-report.md`, `docs/eval/v1-router-comparison.md`, harness in `docs/eval/scripts/run_eval.py`), and the V1.5 evaluation summary (`docs/eval/manhattan-100-results.md`).
