# Palimpsest NYC — Project overview

> An agentic LLM walking tour of Morningside Heights & the Upper West Side, grounded in public-domain archives, rendered in 3D.

This document is the canonical project-context companion to the top-level [`README.md`](../README.md). The README is the GitHub-facing pitch; this file is the academic and architectural deep-dive.

---

## Project framing

**Palimpsest NYC** is a graduate final project for **Columbia EECS E6895: Advanced Big Data and AI**.

Palimpsest plans a short walking tour for a bounded slice of NYC and narrates it from free, public-domain data sources: Wikipedia/Wikidata and OpenStreetMap in V1, with Chronicling America, NYPL, NYC Open Data, MTA, and NOAA tracked as v2 expansions. Every claim in the narration is cited back to a retrieved source document via a strict five-field citation contract verified at generation time.

The entire codebase is being built end-to-end by Claude Code under a single human reviewer. Full session telemetry is captured to `logs/claude-sessions/*.jsonl` so the final report can quantify the cost, cycle time, and failure modes of agentic software engineering. So the project does double duty: the application is a constrained, citation-grounded LLM agent, and the telemetry is an empirical record of how an autonomous coding agent put it together.

---

## Architecture

```
 ┌─────────────────────────┐
 │  React + Vite + TS SPA  │   MapEngine interface
 │  MapLibre GL (3D OSM)   │   (swap-ready for Google 3D Tiles)
 └────────────┬────────────┘
              │ HTTPS + SSE
 ┌────────────▼────────────┐
 │   FastAPI  (apps/api)   │
 │   - /health /ready      │
 │   - /llm/chat (router)  │
 │   - /agent/ask (SSE)    │
 │   - /internal/metrics   │
 └────────────┬────────────┘
              │
    ┌─────────┼──────────┐
    │         │          │
 ┌──▼──┐  ┌───▼───┐  ┌──▼──────────┐
 │PG16 │  │Redis  │  │ LLM Router  │
 │+postgis +pgvector   │ OpenRouter  │ ← V1: both tiers
 │+pg_trgm              │ (Gemma-4 / │   terminate at OpenRouter
 └─────┘  └───────┘     │  GPT-5.4)  │   (on-device LLM = v2)
                        └─────────────┘
```

**Frontend (`apps/web`).** React + Vite + TypeScript SPA. The `MapEngine` interface in `apps/web/src/map/` decouples the UI from the concrete map provider; MapLibre GL is the V1 default, and Google Photorealistic 3D Tiles is a v2 swap-in selected by `VITE_MAP_ENGINE`. The `EventSource` consumer in the chat pane streams `/agent/ask` SSE frames and invokes `flyTo` as `citations` and `walk` events arrive.

**Backend (`apps/api`).** FastAPI + Python 3.12, wired in `app/main.py::create_app()` under a single async `lifespan` that hangs all long-lived singletons off `app.state` (LLM router, embedder, async DB engine, agent tool registry, session logger). The agent loop lives at `apps/api/app/agent/loop.py` and carries the locked V1 contract: hard turn cap of 6, JSON terminal turn, five-field citation verifier, one corrective retry.

**Data layer.** PostgreSQL 16 + PostGIS + pgvector + pg_trgm, with schema owned by `apps/api/app/db/migrations/*.sql` (migrations-first). The `places` and `documents` tables carry 384-dim embeddings produced by a `BAAI/bge-small-en-v1.5` sentence-transformer singleton. Redis is wired for cache and breaker bookkeeping.

**LLM router.** `apps/api/app/llm/router.py` runs two tiers (`local` + `openrouter`) each with a 3-fail / 60s window / 30s cooldown circuit breaker. In V1 both tiers terminate at OpenRouter; v2 will repoint `LOCAL_LLM_BASE_URL` at an on-device endpoint (`llama.cpp`, vLLM, Ollama) without code change. Complexity (`simple` / `standard` / `complex`) is the only knob callers pass. The router decides backend, cache TTL, and breaker bookkeeping.

Full design: [`openspec/changes/initial-palimpsest-scaffold/design.md`](../openspec/changes/initial-palimpsest-scaffold/design.md).

---

## Status as of milestone 1

**Backend MVP complete and demo-ready** (as of 2026-04-28).

| Phase | Spec | What | Status |
|---|---|---|---|
| §1-§8 | scaffold | Monorepo, docker-compose, FastAPI skeleton, LLM router, map engine, meta harness | ✓ shipped |
| §10 | DB schema + embeddings | postgis + pgvector + pg_trgm; `places` + `documents` tables with `vector(384)`; `BAAI/bge-small-en-v1.5` singleton on app.state | ✓ shipped |
| §11 | Ingestion | Wikipedia/Wikidata (492 places + 323 docs) + OSM Overpass (436 places); 100% embedding coverage | ✓ shipped |
| §9 / §12.1-§12.4 | Agent + walk planner + SSE | Single-tool agent (`search_places`); locked five-field citation verifier; server-side `plan_walk`; `/agent/ask` SSE endpoint | ✓ shipped |
| §12.5 | Frontend rendering | React `EventSource` consumer with map markers + flyTo | ⏳ next |
| §13.4 / §13.6 | Eval + cost analysis | 5 hand-graded walks; ~10-walk free-vs-paid model comparison | ⏳ next |
| §13.7 / §13.8 | Final report + 30s demo video | | ⏳ next |
| post-§14 | Docker image publishing | Three images on ghcr.io (`palimpsest-{api,web,postgres}`), built and pushed by GitHub Actions on `main` and `v*` tags | ✓ shipped |
| §13.1-§13.3 / §14 | Live-data sources + hosted VPS demo | | deferred to v2 |

**Numbers as of milestone 1**: 928 places + 323 documents in postgres, all with 384-dim embeddings. 120 unit tests pass. End-to-end agent run (question → narration → 3 verified citations → ordered walk) validated live with `kimi-k2.6` via OpenRouter.

Full task ledger: [`openspec/changes/initial-palimpsest-scaffold/tasks.md`](../openspec/changes/initial-palimpsest-scaffold/tasks.md).

## Status as of milestone 2 — V1.5 (2026-05-12)

**Shipped on `worktree-eval-depth-and-corpus-expansion`, tag `manhattan-100-eval-complete`.** Three orthogonal capability blocks; the locked V1 contract (7-turn cap, JSON terminal, five-field citations, one corrective retry, SSE event names) was not relaxed.

| Phase | What | Status |
|---|---|---|
| 0 | Eval harness scaffold (3 baselines: vanilla / naive_rag / palimpsest; LLM-judge; aggregate; `/internal/retrieve` + `/internal/documents/by_ids`) | ✓ shipped |
| 1 | Manhattan-wide corpus expansion (`SCOPE_BBOX` widened; automatic re-ingest on `make nuke && make up`) | ✓ shipped |
| 2 | Pre-registered 95-question Manhattan bank with categories.yaml (tagged `eval/manhattan-100-v1`) | ✓ shipped |
| 3 | Run + judge + aggregate 3 baseline systems on 95Q | ✓ shipped |
| 4 | Hybrid retrieval (`DenseRetriever`, `SparseRetriever`, RRF fusion, `HybridRetriever`, factory + `RETRIEVAL_MODE` flag, shape-contract test, hybrid eval row) | ✓ shipped |
| 5 | `BAAI/bge-reranker-base` cross-encoder reranker (`RerankedRetriever`, lifespan wiring conditional on `RETRIEVAL_MODE=hybrid_reranked` or `RERANKER_ENABLED`, reranked eval row) | ✓ shipped |
| 6 | Per-region + per-source breakdowns (CSVs + bar-chart PNGs), accuracy-vs-latency Pareto, GRR table on out-of-scope subset, methodology summary | ✓ shipped |
| — | OSRM extract resize for Manhattan bbox | deferred per design risk R8 |
| — | Cohen's κ hand-grading on 20-question calibration set | deferred per session preference; `kappa` cell in ablation table is `null` |

**Numbers as of milestone 2**: 12,858 OSM + 492 Wikipedia places + 456 Wikipedia documents in postgres (Manhattan island bbox). Final 5-row ablation in `docs/eval/results/ablation_table.md`: palimpsest-hybrid-reranked CCR=0.755 [0.678, 0.818], vs vanilla 0.068, naive_rag 0.856. Methodology, caveats (v2 CCR rubric, citation-frame doc_id harvesting, LLMCache warm-up, hybrid serialization, judge self-grading risk) and reproducibility recipe in [`docs/eval/manhattan-100-results.md`](eval/manhattan-100-results.md).

Full task ledger: [`openspec/changes/eval-depth-and-corpus-expansion/tasks.md`](../openspec/changes/eval-depth-and-corpus-expansion/tasks.md).

---

## Design decisions locked for V1

These constraints are load-bearing. Relaxing any one of them requires an OpenSpec change, not just a code edit.

- **Schema is migrations-first.** `apps/api/app/db/models.py` is a typed read-only mirror of `apps/api/app/db/migrations/*.sql`. ORM `create_all` is never used in app code paths. Schema changes require `make nuke && make up`.
- **Citation contract is closed-set.** Every citation must carry the five fields `doc_id`, `source_url`, `source_type`, `span`, `retrieval_turn`, and `source_type` is restricted to `{wikipedia, wikidata, osm}` in V1. Adding a source means amending `V1_SOURCE_TYPES` and the agent system prompt together.
- **Complexity is the only router knob.** Callers pass `complexity ∈ {simple, standard, complex}`; the router selects backend, cache TTL, and breaker accounting. No caller-side backend selection or cache bypass.
- **Embedding dimension is locked at 384.** The `EMBEDDING_DIM` constant in `apps/api/app/db/models.py` is hardcoded to match the `vector(384)` column type and the `BAAI/bge-small-en-v1.5` embedder's output dimension. Changing the embedder requires a migration that drops and recreates the `vector(384)` column and bumps this constant in lockstep.
- **Each Python subproject owns its own venv.** `apps/api` and `apps/worker` each have their own `.venv`. No system Python installs; `make setup` is the entry point (uses `uv` if available, else stdlib `venv` + `pip`).
- **Hard turn cap of 6 in the agent loop.** Hitting the cap is a hard failure (`AgentLoopError`). The final turn strips the tool surface and forces a JSON terminal response with `max_tokens=8192`.

---

## OpenSpec workflow

This project uses [OpenSpec](https://github.com/fission-ai/openspec) for spec-driven development. Two changes are tracked:

- **Active:** [`openspec/changes/initial-palimpsest-scaffold/`](../openspec/changes/initial-palimpsest-scaffold/): proposal, design, tasks, and capability specs for the V1 build.
- **Locked decisions:** [`openspec/changes/swap-llm-tiers-and-lock-mvp-decisions/`](../openspec/changes/swap-llm-tiers-and-lock-mvp-decisions/): captures the V1 decisions that are deliberately frozen (LLM router rename, embedding model, citation contract, license).

Inspect changes locally (make targets wrap the openspec CLI):

```bash
make spec-list      # → openspec list
make spec-show      # → openspec show initial-palimpsest-scaffold
make spec-validate  # → openspec validate initial-palimpsest-scaffold --strict
```

---

## On-device LLM (v2)

V1 is **online-only**: every LLM call goes to OpenRouter. The router still has two configurable tiers (`LOCAL_LLM_*` and `OPENROUTER_*`) so v2 can repoint the local-tier base URL at an on-device endpoint (`llama.cpp`, vLLM, Ollama, etc.) without touching code. This work is deferred to v2 — see [`openspec/changes/swap-llm-tiers-and-lock-mvp-decisions/proposal.md`](../openspec/changes/swap-llm-tiers-and-lock-mvp-decisions/proposal.md).

---

## Local Python dev (outside Docker)

Every Python subproject uses an isolated virtual environment. No system Python installs.

```bash
# one-time setup — creates .venv in each apps/api, apps/worker subproject
make setup

# activate the api venv for interactive work
source apps/api/.venv/bin/activate
```

---

## Deployment

V1 has two paths:

- **Run from published images.** `docker-compose.prod.yml` pulls `ghcr.io/nyavana/palimpsest-{api,web,postgres}:${PALIMPSEST_TAG:-latest}`. No Python or Node toolchain on the host. The api image is around 760 MB uncompressed (CPU-only torch wheel); postgres ships with the V1 migrations baked into `/docker-entrypoint-initdb.d`. See the [Quickstart in README](../README.md#quickstart) for the exact commands.
- **Build from source.** `make up` builds the same three images locally from the Dockerfiles in `apps/api/`, `apps/web/`, and `docker/postgres/`. Use this when developing against the project.

Image publishing is automated. [`.github/workflows/docker-publish.yml`](../.github/workflows/docker-publish.yml) runs three matrix jobs (api, web, postgres) on push to `main`, on `v*` tags, on PRs into `main` (verification only — no `latest` move), and on manual `workflow_dispatch`. Auth uses the built-in `GITHUB_TOKEN`. Layer caching is `type=gha`. Platforms is `linux/amd64`; arm64 is a one-line addition once amd64 is proven.

A hosted demo on a VPS or PaaS is still v2 work — V1 expects the grader to bring the stack up locally with one of the two paths above.

---

## Data sources & licenses

All V1 data sources are free or public-domain. Code is released under the **MIT License**; see [`LICENSE`](../LICENSE).

- **Wikipedia / Wikidata** — CC BY-SA
- **Chronicling America** — public domain
- **NYPL Digital Collections** — public domain / CC (filtered)
- **OpenStreetMap** — ODbL
- **NYC Open Data** — CC0 (varies by dataset)
- **MTA GTFS-RT** — open data
- **NOAA Weather API** — public domain

---

## Per-phase deep-dives

The phase notes in [`docs/`](.) are dated snapshots written at the end of each milestone:

- [`swap-llm-tiers-2026-04-28.md`](swap-llm-tiers-2026-04-28.md): V1 MVP lock-down covering the LLM router rename, embedding model selection, locked citation contract, and license decision.
- [`db-and-embeddings-2026-04-28.md`](db-and-embeddings-2026-04-28.md): §10 schema, ORM, and the `BAAI/bge-small-en-v1.5` embedder singleton.
- [`ingestion-2026-04-28.md`](ingestion-2026-04-28.md): §11 Wikipedia/Wikidata and OSM Overpass ingestion, including the raw-cache replay layer.
- [`agent-2026-04-28.md`](agent-2026-04-28.md): §9 / §12.1-4 agent loop, citation verifier, server-side `plan_walk`, and the `/agent/ask` SSE endpoint.
- [`eval/manhattan-100-results.md`](eval/manhattan-100-results.md): V1.5 5-system ablation, per-region + per-source breakdowns, Pareto figure, GRR table, and the methodology caveats (v2 CCR rubric, LLMCache warm-up, judge self-grading risk).

---

## Report & demo (planned)

The course deliverables tracked in [`openspec/changes/initial-palimpsest-scaffold/tasks.md`](../openspec/changes/initial-palimpsest-scaffold/tasks.md):

- **§13.7, Final report.** Quantifies cost, cycle time, and failure modes of the agentic build using the per-session telemetry in `logs/claude-sessions/*.jsonl`.
- **§13.8, 30-second demo video.** Captures an end-to-end walking-tour query: question, narration, citations, and walk overlay on the map.

Both ship before the course submission deadline; this section will be updated with links once the artifacts are produced.
