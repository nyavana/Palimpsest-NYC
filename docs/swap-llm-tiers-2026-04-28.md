# swap-llm-tiers-and-lock-mvp-decisions — Implementation Notes (2026-04-28)

OpenSpec change: `openspec/changes/swap-llm-tiers-and-lock-mvp-decisions/`
Progress: **58/59 tasks complete** (§5.8 SSE smoke deferred — endpoint built under `initial-palimpsest-scaffold` §9.9).

## What this change accomplishes

V1 is now **online-only**. Every LLM call terminates at OpenRouter. The Win11 `llama-server` host is no longer part of the V1 contract. The router's two-tier architecture survives intact so v2 can repoint the local-tier base URL at an on-device endpoint without code change.

Four "TBD" Week-1 items are locked:
- **embeddings**: `BAAI/bge-small-en-v1.5`, 384-dim, CPU sentence-transformers in the api container
- **migrations**: plain SQL files in `apps/api/app/db/migrations/`, mounted into postgres via `docker-entrypoint-initdb.d` (no Alembic, no runtime applier)
- **citation contract**: `doc_id`, `source_url`, `source_type`, `span`, `retrieval_turn` — `span` opaque to verifier
- **license**: MIT

V1 agent surface reduces to a single LLM-callable tool (`search_places`); `plan_walk` becomes server-side post-processing; `/agent/ask` streams over SSE instead of WebSocket.

## Code changes

| File | Change |
|---|---|
| `apps/api/app/config.py` | Renamed `LlamaCppSettings` → `LocalLLMSettings`; env prefix `LLAMA_CPP_` → `LOCAL_LLM_`; defaults point at OpenRouter free Gemma. Added `EmbeddingsSettings` block (`EMBEDDING_MODEL`/`DIM`/`BATCH_SIZE`). |
| `apps/api/app/main.py` | Lifespan reads `settings.local_llm.*` and passes `local_*` kwargs to `build_llm_router`. |
| `apps/api/app/llm/router.py` | `build_llm_router` parameter names: `llama_cpp_*` → `local_*`. Module docstring updated to describe the V1 = OpenRouter-on-both-tiers reality. |
| `apps/api/app/logging.py` | Pre-existing bug fix (required to start the api): `PrintLoggerFactory` → `stdlib.LoggerFactory`. The previous config used `structlog.stdlib.add_logger_name` which expects a stdlib BoundLogger and crashed on startup with `AttributeError: 'PrintLogger' object has no attribute 'name'`. |
| `docker-compose.yml` | Header comment rewritten (no Win11 host). `extra_hosts: host.docker.internal:host-gateway` removed from api and worker services. |
| `README.md` | Architecture diagram updated (SSE instead of WS, OpenRouter-only). Quickstart prereqs no longer mention `llama-server`. "Windows-side llama.cpp host" section replaced with a one-paragraph "On-device LLM (v2)" pointer. |
| `apps/api/README.md` | Env-var table covering `OPENROUTER_*`, `LOCAL_LLM_*`, `EMBEDDING_*`. |
| `openspec/changes/initial-palimpsest-scaffold/tasks.md` | §6.5 (heartbeat-only, APScheduler→v2), §9.x (single-tool surface, server-side `plan_walk`, SSE not WS), §10.x (vector(384), init-time migrations, embeddings module §10.5), §11.x (Wikipedia + OSM only), §12.x (SSE), §13.x (V1 = qualitative review of 5 walks, others→v2), §14.x (deferred to v2). |
| `openspec/changes/swap-llm-tiers-and-lock-mvp-decisions/specs/data-ingest/spec.md` | Strict-validate fix: added SHALL to "Staged ingestion" requirement body. |

## Validation outcomes (§5)

| Task | Result |
|---|---|
| 5.1 `make setup` (no Win11) | api venv: ✓. Worker `pip install` requires `uv` due to local path source for `palimpsest-api` — pre-existing tooling caveat, not introduced here. |
| 5.2 `make up` healthy with new env | ✓ `docker compose up postgres redis api` starts all three healthy; `/health` returns `{"status":"ok","version":"0.1.0"}`. No `llama-server` process exists anywhere. |
| 5.3 `/llm/chat` simple | ✓ **End-to-end validated** with `moonshotai/kimi-k2.6` after the user funded their OpenRouter account. `backend="local"`, `content=" pong"`, latency 1.16s, cost $0.0001248. |
| 5.4 `/llm/chat` complex | ✓ **End-to-end validated**. `backend="openrouter"`, real billed response, latency 33.9s (kimi-k2.6 is an extended-thinking model that spends tokens reasoning), cost $0.000128. Cache works correctly: a same-prompt simple call followed by a complex call hits the cache because the model slug matches in this config. |
| 5.5 `make test` from venv | ✓ 13/13 pytest tests pass. |
| 5.6 SessionRecord for this change | ✓ written to `logs/claude-sessions/2026-04-28.jsonl` via `app.meta.cli append`. (The `seed` subcommand is hardcoded to the original scaffold record, so `append` was used with appropriate fields.) |
| 5.7 V1 contract | ✓ no on-device process, no firewall rule, no `extra_hosts` escape hatch — the api dispatches directly to OpenRouter. |
| 5.8 SSE smoke | **Deferred** — `/agent/ask` endpoint is `initial-palimpsest-scaffold` §9.9 (still pending). This change only locks the contract that the endpoint MUST be SSE when built. |

## Note on kimi-k2.6 (current local-tier model)

`moonshotai/kimi-k2.6` is an **extended-thinking** model — it consumes completion tokens during internal reasoning before producing the visible response. Side-effects to keep in mind:

- Set `max_tokens` generously (≥256 for narration, ≥64 for terse replies). Tight token caps will return `content=null` because the budget runs out during the thinking phase.
- Latency for `complex` calls is much higher (~30-40s observed) than for parameter-equivalent non-thinking models. Consider whether the user-perceived narration latency is acceptable; the SSE transport (§9.9 / §12.4) hides this somewhat by streaming reasoning + tokens as they arrive.
- For ingestion-time bulk NLP (`complexity="simple"`), the latency is the cost: 1-2s per Wikipedia article filter call adds up. May be worth pinning `LOCAL_LLM_MODEL` to a non-thinking model (e.g., a Gemma-4 paid slug) for ingestion specifically.

## What unblocks next

With this change merged, the four MVP task groups can start:

- **§10** (db schema): clear migration mechanism + `vector(384)` column type pinned
- **§11** (ingestion): `source_type` enum locked to `wikipedia | wikidata | osm`; embeddings model fixed
- **§9** (agent): tool surface = `search_places` only; SSE transport locked
- **§12** (walk planner): server-side post-processing pattern locked

## Out-of-scope work flagged (not done in this change)

- Worker venv tooling: works under `uv`, not under stock `pip` — the worker's `[tool.uv.sources]` block sources `palimpsest-api` from a local path. Optional follow-up: install `uv` in the project README's prereqs, or add a `pip`-compatible `[project.optional-dependencies]` editable install path.
- The `seed` subcommand in `app/meta/cli.py` is hardcoded to write the original scaffold's first record. Follow-up could parametrize it by change name.
