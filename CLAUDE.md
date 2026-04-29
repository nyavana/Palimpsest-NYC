# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**Palimpsest NYC** — agentic LLM walking-tour app for Morningside Heights & UWS. Columbia EECS E6895 final project. The codebase is being built end-to-end by Claude Code under a single human reviewer; full session telemetry is captured to `logs/claude-sessions/*.jsonl` for the report's empirical analysis of agentic software engineering. V1 is online-only — every LLM call terminates at OpenRouter; on-device LLM hosting is a v2 swap-in via the same env-driven router-tier URLs.

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

Populate the corpus (one-shot CLI, **after** `make up`):

```bash
docker compose exec api python -m app.ingest.cli osm run
docker compose exec api python -m app.ingest.cli wikipedia run
```

End-to-end smoke test of the agent SSE endpoint:

```bash
curl -N "http://localhost:8000/agent/ask?q=Tell+me+about+a+gothic+cathedral+in+Morningside+Heights"
# Expect SSE frames: turn → tool_call → tool_result → narration → citations → walk → done
```

OpenSpec (spec-driven workflow used for change proposals):

```bash
make spec-list
make spec-show
make spec-validate     # `openspec validate initial-palimpsest-scaffold --strict`
```

## Architecture

Monorepo with three apps under `apps/` and a single root `docker-compose.yml`. The seam between them is the OpenAPI surface in `apps/api` (`/health`, `/llm/chat`, `/agent/ask` SSE, `/internal/metrics`).

### `apps/api` — FastAPI backend (Python 3.12)

Wired in `app/main.py::create_app()` with a single async `lifespan` that builds and stores all long-lived singletons on `app.state`:

- `app.state.llm_router` — cost-aware router (`app/llm/router.py`) with two tiers (`local` and `openrouter`), each with its own circuit breaker (3 fails / 60s window / 30s cooldown). Complexity dispatch: `simple` → local tier, `standard`/`complex` → cloud tier. **In V1 both tiers point at OpenRouter** — the split exists so v2 can repoint `LOCAL_LLM_BASE_URL` at an on-device endpoint without code change. Cache is keyed by canonicalized request hash with TTLs that vary by complexity.
- `app.state.embedder` — `BAAI/bge-small-en-v1.5` sentence-transformer singleton (CPU-only, 384-dim). Weights live in the `hf-cache` volume mounted at `/cache/huggingface`.
- `app.state.db_engine` / `db_session_factory` — async SQLAlchemy 2 over asyncpg. **Schema is owned by `app/db/migrations/*.sql`**, applied by the postgres entrypoint on first volume init in lex order. ORM models in `app/db/models.py` are read-only mirrors — never call `Base.metadata.create_all` in app code paths. Schema changes require `make nuke && make up`.
- `app.state.agent_tool_registry` / `agent_loop_builder` — V1 contract registers **exactly one** tool (`search_places`); any other tool name returns an `unknown_tool` error message back to the LLM and the loop continues.
- `app.state.session_logger` — meta-instrumentation harness (`app/meta/`) that writes per-session jsonl files for the report's cost/cycle-time analysis.

Request flow: `RequestIdMiddleware` binds an `X-Request-ID` to structlog contextvars for the lifetime of the request and clears it on the way out. CORS allow-origins come from `API_CORS_ORIGINS`.

### Agent loop (locked V1 contract)

`apps/api/app/agent/loop.py` drives the conversation. **Critical invariants — do not loosen without a spec change:**

- Hard turn cap of 6. Hitting the cap is a hard failure (`AgentLoopError`).
- The final turn strips the tool surface and adds a "stop searching, emit JSON now" directive, with `response_format=json` and `max_tokens=8192` (vs. 2048 for tool-call turns) — this gives extended-thinking models like `kimi-k2.6` enough budget for both reasoning and the final JSON.
- Terminal response is JSON `{narration, citations[]}` with the **strict five-field citation contract**: `doc_id`, `source_url`, `source_type` ∈ {`wikipedia`, `wikidata`, `osm`}, `span`, `retrieval_turn`. Verified by `app/agent/citations.py::verify_citations` against a `RetrievalLedger` of every doc returned in this conversation.
- One verification retry: on first citation failure, append a corrective user message and re-prompt. If retry also fails, return the response with `verified=False` and a `warning` rather than crashing.
- `run_streamed()` yields `AgentEvent` objects (`turn`, `tool_call`, `tool_result`, `tool_error`, `narration`, `citations`, `warning`, `done`); `run()` is just the consuming wrapper. The SSE route (`app/routes/agent.py`) frames events as `event: <type>\ndata: <json>\n\n` and additionally runs server-side `plan_walk` over cited `place_ids` after `done`, then re-emits a final `done` so the client has a single terminal marker.

### `apps/api/app/ingest` — One-shot ingestion CLI

`python -m app.ingest.cli {wikipedia|osm} run`. Per `swap-llm-tiers-and-lock-mvp-decisions §4.6.1` the worker container only runs a heartbeat loop; ingestion is invoked manually. Sources upsert into `places` + `documents`, with provenance fields (`doc_id`, `source_type`, `source_url`, `source_retrieved_at`, `license`) chosen so a row's provenance becomes its citation with no field renaming. A `RawCache` keeps raw API responses on disk for replay/debugging.

### `apps/web` — React + Vite + TS + MapLibre

`apps/web/src/components/MapView.tsx` consumes a `MapEngine` interface so the concrete engine (MapLibre today, Google Photorealistic 3D Tiles later) is selected from `VITE_MAP_ENGINE` and swappable in a single factory file. Tailwind, ESLint, Prettier preconfigured. Dockerfile builds a static bundle behind nginx (port 80 in container, 5173 on the host).

### `apps/worker` — minimal heartbeat (V1)

Same image as the api (`apps/api/Dockerfile`). `worker.main` runs a heartbeat loop. Real ingestion is the CLI invocation above; this exists so v2 can drop in a scheduler without rebuilding the topology.

## Conventions specific to this repo

- **Schema is migrations-first.** `app/db/models.py` is a typed read-only mirror of the SQL files in `app/db/migrations/`. Never use ORM `create_all`; never write a migration that doesn't have a corresponding ORM update.
- **Citation contract is locked.** All five fields are required and `source_type` is closed-set in V1. Adding a source means adding it to `V1_SOURCE_TYPES` and the system prompt in `agent/loop.py` together.
- **Complexity is the only router knob.** Don't bypass `LLMCache` or hand-pick a backend in caller code. Pass `complexity ∈ {simple, standard, complex}`; the router decides backend, cache TTL, and breaker bookkeeping.
- **Embedding dim is locked at 384.** `EMBEDDING_DIM` constant in `models.py` must track `EMBEDDING_DIM` env. Changing the embedder requires a new migration that drops and recreates the `vector(384)` column.
- **Each Python subproject owns its own venv.** Don't install into system Python — run `make setup` (uses `uv` if available, else stdlib `venv + pip`).
- **Ruff is the formatter and the linter** for Python; line length 100, target py312, strict mypy. Tests skip a few rules (`PLR2004`, `S101`).
- **OpenSpec is the source of truth for proposals.** Active change is `initial-palimpsest-scaffold`; locked decisions live in `swap-llm-tiers-and-lock-mvp-decisions`. Per-phase deep-dives in `docs/`.

## Status quick-reference

Backend MVP is shipped (FastAPI skeleton, LLM router, DB+embeddings, ingestion, agent + walk planner + SSE). Frontend rendering, eval, and final report are the open phases. Treat anything in `openspec/changes/initial-palimpsest-scaffold/tasks.md` marked open as the live to-do list.
