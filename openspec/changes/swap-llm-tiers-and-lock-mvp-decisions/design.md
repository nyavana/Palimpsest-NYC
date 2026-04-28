## Context

Three weeks remain on the EECS E6895 calendar. The Week 1 scaffold is complete but unverified — the smoke checklist in `docs/week-1-scaffold-complete.md` was never run because the Win11 llama-server it depends on was never started. To unblock §10/§11/§12/§9 (the four task groups that together produce a demo-able MVP) we need to:

1. Remove the Win11 daemon as a hard dependency without abandoning the dual-backend architecture that motivates the paper.
2. Pick concrete defaults for the four "TBD" items (embeddings, migration tooling, citation shape, license) so subsequent task groups stop blocking on choice.

OpenRouter now offers `google/gemma-4-31b-it:free` at no marginal cost. That is functionally the same kind of model the Win11 llama-server was running (Gemma-4-IT family), just at a slightly larger parameter count, served over the same OpenAI-compatible HTTP shape. Repointing the router's `simple` tier at it is a one-env-var change — no router code moves.

## Goals / Non-Goals

**Goals:**

- Get every MVP task group (§9, §10, §11, §12) unblocked by stable, env-driven defaults that work without a Win11 daemon.
- Keep the dual-backend router architecture intact so the paper's "cost-aware dispatch" story still holds. The architecture is "two OpenAI-compatible adapters, picked by complexity"; that remains true even when both adapters terminate at OpenRouter in V1.
- Lock decisions that have downstream filesystem consequences (embedding dim → schema column type, migration tool → entrypoint shape) before §10 starts.
- Preserve a clean v2 path for on-device LLM hosting: the architecture supports it, the spec allows it, the V1 deployment just doesn't exercise it.

**Non-Goals:**

- **On-device LLM hosting in V1.** No part of the V1 demo, eval, or deploy path runs an LLM on the dev box, the Win11 host, or the VPS. All V1 LLM calls go to OpenRouter.
- Re-architecting the router. Cache, breaker, telemetry, fallback ladder, public API all stay exactly as written.
- Switching frameworks (no LangChain, no Alembic, no Pinecone). The Week 1 design called these out as deliberate omissions; they remain so.
- Picking the "production" cloud models. The default points at free Gemma for dev; the §13.6 eval will flip to `openai/gpt-5.4-mini`/`openai/gpt-5.4`. Both configurations live in `.env`, switching is a deploy-time concern.

## Decisions

### 1. The `simple` tier is served by an env-configured OpenAI-compatible endpoint

The router's adapter classes (`LlamaCppAdapter`, `OpenRouterAdapter`) already implement the same `async complete(NormalizedRequest) -> NormalizedResponse` interface. The only thing that distinguishes them today is the constructor arg names. We collapse the user-facing concept to **two configurations**, both consumed via env:

- `LOCAL_LLM_BASE_URL` / `LOCAL_LLM_MODEL` / `LOCAL_LLM_API_KEY` — backs the router's `simple` tier.
- `OPENROUTER_BASE_URL` / `OPENROUTER_API_KEY` / `OPENROUTER_STANDARD_MODEL` / `OPENROUTER_COMPLEX_MODEL` — backs `standard` and `complex` tiers.

**For V1, both `LOCAL_LLM_BASE_URL` and `OPENROUTER_BASE_URL` point at `https://openrouter.ai/api/v1`.** The naming "local-tier" is internal router terminology; it does NOT mean network-local in V1. The split exists so the router can run two independent circuit breakers and so v2 can swap one URL to an on-device endpoint without code change.

The `LlamaCppAdapter` class keeps its name (already OpenAI-compatible internally) to minimize churn in already-passing tests; only its constructor params and the env var names it reads are renamed. Existing tests in `tests/test_llm_router.py` use fake adapters injected at the `LLMRouter(...)` boundary and are unaffected.

On-device LLM support is **not removed from the codebase** — the same env vars accept a localhost URL — but it is **not part of V1's documented or tested configuration**. v2 will add it back as a tracked spec change.

### 2. Default model mapping under free-tier dev

| Complexity | Backend | V1 default (free) | V1 eval-mode (paid) |
|---|---|---|---|
| `simple` | local-tier | `google/gemma-4-31b-it:free` | unchanged |
| `standard` | cloud-tier | `google/gemma-4-31b-it:free` | `openai/gpt-5.4-mini` |
| `complex` | cloud-tier | `google/gemma-4-31b-it:free` | `openai/gpt-5.4` |

For §13.6 router cost analysis we set the eval-mode model env vars and re-run the harness. The router code is invariant to the choice. Both columns are V1 — the same OpenRouter endpoint, different model slugs.

### 3. Embeddings: bge-small-en-v1.5, 384-dim, in-process

`sentence-transformers` loads `BAAI/bge-small-en-v1.5` at api startup into a singleton on `app.state.embedder`. CPU inference; ~30 ms/sentence; batch size 32 (env-configurable); deterministic via fixed seed.

Implication for §10: the `places.embedding` and `documents.embedding` columns are `vector(384)`, not `vector(768)`. The `0001_init.sql` migration enables `vector` extension; the `0002_places.sql` migration declares the column type literally as `vector(384)`.

The in-process model means the api container loads ~30 MB of weights at startup. We mount a host volume `/cache/huggingface` to avoid re-downloading on every container rebuild; first run downloads, subsequent runs read from cache.

If §11 ingestion volumes ever blow past CPU embedding throughput, we can flip to a worker-side embedding job without changing the column type or the spec contract.

### 4. DB migrations: plain SQL files, two execution paths

We do not use Alembic. Migration files live at `apps/api/app/db/migrations/NNNN_name.sql`, applied in lexicographic order. There are exactly two execution surfaces:

- **Init-time migrations** (`0001_init.sql`, `0002_places.sql`): mounted into the postgres container via `docker-entrypoint-initdb.d` and run on first DB volume creation. Required because they enable extensions and create base tables.
- **Subsequent migrations** (`0003_*.sql` and beyond): applied by the api on startup via a one-shot `psql -v ON_ERROR_STOP=1 -f` for each file not present in a `schema_migrations(filename text primary key, applied_at timestamptz not null default now())` ledger table.

Idempotency: the api process owns the ledger and the apply step; concurrent api workers do not race because the migrator runs once per process before uvicorn binds.

Reversibility: not supported in v1. Migrations are forward-only. Recovery is via a fresh dev volume, or via `pg_dump` rollback for production.

### 5. Citation JSON contract (locked)

The locked field-by-field contract lives in `specs/agent-tools/spec.md` (MODIFIED requirement "Citation contract enforced at generation time"). Summary: every narration response is a JSON object with `narration: string` and `citations: Citation[]`, where each `Citation` has the five required fields `doc_id`, `source_url`, `source_type`, `span`, `retrieval_turn`. The verifier rules and per-field semantics are specified there so the contract has exactly one source of truth. The same `source_type` enum values are reused by the data-ingest provenance record (see Decision §3 in the modified `data-ingest` spec) — provenance and citation share field names so a row's provenance becomes its citation with no field renaming.

### 6. License: MIT

The repository's code is original (no WorldMonitor fork; data sources are public-domain or permissive). MIT is the simplest license that imposes no obligations on downstream readers, matches the OSM/Wikipedia ecosystem ethos, and satisfies the course's "publishable artifact" requirement. The copyright holder is the user (Columbia EECS E6895 student); year is 2026.

### 7. V1 LLM-callable tool surface = single tool (`search_places`)

V1 reduces the agent's tool surface to **one tool**, `search_places(query, near, radius_m)`. The remaining tools sketched in earlier drafts (`spatial_query`, `historical_lookup`, `current_events`, `plan_walk`) are deferred to v2.

`plan_walk` is **not removed from the system** — it becomes server-side machinery. After the agent emits its final response with `citations[]` referencing N place_ids, the server runs a deterministic PostGIS routing pass to produce an ordered walking route, which the frontend renders. The LLM never sees the routing tool. This avoids two problems at once: (a) the free Gemma model's tool-calling fidelity at >1 tool is unproven and a one-tool agent loop is robust to "did the model produce a clean tool call" failures; (b) the agent can't accidentally produce an inefficient walk by ignoring the routing tool — there is no routing tool to ignore.

Trade-off: a one-tool agent reads less "agentic" on stage than a multi-tool one. Mitigation: the agent loop still runs multiple turns of `search_places` (broad query, then narrowed query) to demonstrate iterative retrieval, and the demo narration explicitly shows the routing pass as a server-side step. v2 re-introduces `plan_walk` as a callable tool when there's a stronger model available or when the agent needs to choose between thematically distinct walks.

### 8. `/agent/ask` transport = SSE, not WebSocket

V1 streams narration tokens over Server-Sent Events. Rationale:

- The channel is server→client only; client→server is a single one-shot question per request.
- SSE handler in FastAPI is ~half the code of a WS handler (`StreamingResponse(media_type="text/event-stream")` + an async generator).
- Browser `EventSource` auto-reconnects; WS reconnect is hand-rolled.
- nginx proxy config for SSE is `proxy_buffering off`; for WS it's the upgrade-header dance, which fails silently if misconfigured.
- The only V1 capability that benefits from WS bidirectional traffic — mid-stream interrupt — is explicitly out of V1 scope. WS comes back in v2 if the agent grows interactive controls.

If V1 ships SSE and v2 wants WS, swapping is a half-day refactor on each side. The spec wording ("agent streams narration as it's generated") is transport-agnostic; only the implementation differs.

### 9. db-migrations: single execution surface for V1

V1 collapses to one migration runner: the postgres image's built-in `docker-entrypoint-initdb.d` mechanism. All `.sql` files at `apps/api/app/db/migrations/` are mounted there and execute in lex order on first volume creation. Schema changes during V1 development require `docker compose down -v && docker compose up postgres` to re-init. This is acceptable because V1 has no persistent production data — any "real" corpus is re-ingested from `raw/` cache in minutes.

The runtime startup applier (with `schema_migrations` ledger, idempotent re-application, advisory lock) is a v2 concern, gated on having a deployed instance with persistent data that can't tolerate a volume drop.

## Risks / Trade-offs

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| OpenRouter rate-limits the free Gemma slug mid-development and dev grinds to a halt | Medium | Medium | Cache TTLs already absorb most repeat traffic. If we hit the wall, flip `OPENROUTER_*_MODEL` to a paid slug (`openai/gpt-5.4-mini`) — same provider, same env shape, no infra change. The on-device fallback is v2-only. |
| `google/gemma-4-31b-it:free` slug is not stable on OpenRouter and gets renamed | Low | Low | All references are env-driven; a slug rename is a one-line `.env` edit, not a code change. |
| 384-dim vs 768-dim retrieval quality is meaningfully worse for our corpus and we don't catch it until §11 | Low | Medium | Bge-small is the published recommendation for short-text retrieval at <512 tokens; if §11 evaluation shows weak P@5 we can swap to bge-base (768-dim) by re-running an embedding-only migration. The schema is forward-only but the vector column can be dropped+rewritten cheaply at v1 corpus size. |
| Plain-SQL migrations get unwieldy if the schema churns more than expected | Low | Low | We have eight migrations of headroom (§10.3, §10.4, plus six more before the v1 demo) before this becomes a problem. If it does, switching to Alembic is a one-time porting job, not a re-architecture. |
| Citation contract locks too early and a real source we ingest doesn't fit the shape | Low | Medium | The V1 `source_type` enum (`wikipedia | wikidata | osm`) is small on purpose; v2 source additions extend the enum via spec change, not by editing rows. |
| Free Gemma's tool-calling fidelity is much worse than GPT-5.4-mini and the agent loop misbehaves on `simple` complexity | Medium | Medium | V1's tool-calling is `complexity="standard"` over the same OpenRouter free Gemma slug, single-tool only (Decision §7). If tool-calling fidelity remains an issue, eval mode flips `OPENROUTER_STANDARD_MODEL` to `openai/gpt-5.4-mini` with one env var. |
| Single-tool agent reads as less "agentic" to the grader | Low | Low | The agent loop demonstrates iterative retrieval (multi-turn `search_places` with refinement). The demo script calls out the server-side routing pass as a deliberate post-processing step rather than hiding it. v2 re-introduces multi-tool dispatch when narratively justified. |
| SSE doesn't support mid-stream interrupt for the demo | Low | Low | V1 has no interrupt feature; agent runs to completion. If a stretch goal needs interrupt, swapping SSE→WS is a half-day refactor on both sides. |
| Volume-drop migration workflow is friction during dev | Medium | Low | V1 dev resets the volume on schema change. The api README documents the `docker compose down -v` step. v2 adds the runtime applier when persistent data is in play. |

## Migration Plan

1. Land this OpenSpec change (proposal/design/tasks/specs — including MODIFIED `agent-tools` and `data-ingest` deltas).
2. Update `.env.example` and `apps/api/app/config.py` to use `LOCAL_LLM_*` names pointing at OpenRouter; the existing `apps/api/app/llm/router.py` builder is updated to read the renamed env vars.
3. Add `LICENSE` (MIT).
4. Update `tasks.md` of `initial-palimpsest-scaffold` so §10 references `vector(384)` and the SQL-only migration shape; rewrite §11.5 with the locked embedding model; rewrite §11.x ingest tasks to use the renamed `source_type` field.
5. Run the Week 1 smoke checklist end to end against OpenRouter only. Capture results to a `SessionRecord`.
6. Open §10 (DB schema) as the active task group.

## Open Questions

None. All Week-1 "TBD" items have a chosen V1 default. On-device LLM hosting is explicitly deferred to v2 with no V1 work pending.
