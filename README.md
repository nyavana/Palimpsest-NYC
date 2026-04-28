# Palimpsest NYC

> An agentic LLM walking tour of Morningside Heights & the Upper West Side, grounded in public-domain archives, rendered in 3D.

A graduate final project for **Columbia EECS E6895: Advanced Big Data and AI**.

Palimpsest plans a short walking tour for a bounded slice of NYC and narrates it from free, public-domain data sources — Wikipedia/Wikidata + OpenStreetMap in V1, with Chronicling America, NYPL, NYC Open Data, MTA, NOAA tracked as v2 expansions. Every claim in the narration is cited back to a retrieved source document via a strict five-field citation contract verified at generation time.

The entire codebase is being built end-to-end by Claude Code under a single human reviewer. Full session telemetry is captured to `logs/claude-sessions/*.jsonl` so the final report can quantify the cost, cycle time, and failure modes of agentic software engineering.

---

## Architecture at a glance

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

Full design: [`openspec/changes/initial-palimpsest-scaffold/design.md`](./openspec/changes/initial-palimpsest-scaffold/design.md)

---

## Quickstart (local Docker)

Prereqs: Docker (with `compose` v2), `uv` (or Python 3.12 + `venv`), Node 20+. **No on-device LLM host required** — V1 routes every LLM call through OpenRouter, so all you need is an `OPENROUTER_API_KEY`. On-device LLM hosting is tracked as a v2 swap-in via the same env vars.

```bash
# 1. configure environment
cp .env.example .env
# edit .env to set OPENROUTER_API_KEY

# 2. bring the stack up
make up

# 3. follow logs
make logs

# 4. hit health check
curl http://localhost:8000/health
# → {"status":"ok"}

# 5. open the frontend
open http://localhost:5173
```

To stop everything:

```bash
make down
```

---

## Try the agent (backend SSE demo)

Once `make up` brings the stack up, populate the corpus once and ask the agent
a walking-tour question.

```bash
# 1. Populate the 5km² Morningside Heights + UWS corpus (~30s total)
docker compose exec api python -m app.ingest.cli osm run
docker compose exec api python -m app.ingest.cli wikipedia run

# 2. Ask the agent a question; watch SSE events stream live
curl -N "http://localhost:8000/agent/ask?q=Tell+me+about+a+gothic+cathedral+in+Morningside+Heights"
```

You should see a sequence of `event: turn`, `event: tool_call`,
`event: tool_result` frames as the agent iterates `search_places`,
followed by `event: narration`, `event: citations`, `event: walk`
(ordered route with leg distances), and a terminal `event: done`.

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

## On-device LLM (v2)

V1 is **online-only**: every LLM call goes to OpenRouter. The router still has two configurable tiers (`LOCAL_LLM_*` and `OPENROUTER_*`) so v2 can repoint the local-tier base URL at an on-device endpoint (`llama.cpp`, vLLM, Ollama, etc.) without touching code. This work is deferred to v2 — see `openspec/changes/swap-llm-tiers-and-lock-mvp-decisions/proposal.md`.

---

## OpenSpec

This project uses [OpenSpec](https://github.com/fission-ai/openspec) for spec-driven development. The active change is `initial-palimpsest-scaffold` — see `openspec/changes/initial-palimpsest-scaffold/` for the proposal, design, tasks, and capability specs.

```bash
openspec list
openspec show initial-palimpsest-scaffold
openspec status --change initial-palimpsest-scaffold
```

---

## Status

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
| §13.1-§13.3 / §14 | Live-data sources + VPS deploy | | deferred to v2 |

**Numbers as of milestone 1**: 928 places + 323 documents in postgres,
all with 384-dim embeddings. 120 unit tests pass. End-to-end agent run
(question → narration → 3 verified citations → ordered walk) validated
live with `kimi-k2.6` via OpenRouter.

Per-phase deep-dives in [`docs/`](./docs):

- [`docs/swap-llm-tiers-2026-04-28.md`](./docs/swap-llm-tiers-2026-04-28.md) — V1 MVP lock-down (LLM router rename, embedding model, citation contract, license)
- [`docs/db-and-embeddings-2026-04-28.md`](./docs/db-and-embeddings-2026-04-28.md) — §10 schema + ORM + embedder
- [`docs/ingestion-2026-04-28.md`](./docs/ingestion-2026-04-28.md) — §11 Wikipedia + OSM ingestion
- [`docs/agent-2026-04-28.md`](./docs/agent-2026-04-28.md) — §9 / §12.1-4 agent + SSE

Full task ledger: `openspec/changes/initial-palimpsest-scaffold/tasks.md`.

---

## Licenses

All v1 data sources are free / public-domain. Code is released under the **MIT License** — see [`LICENSE`](./LICENSE).

- Wikipedia / Wikidata — CC BY-SA
- Chronicling America — public domain
- NYPL Digital Collections — public domain / CC (filtered)
- OpenStreetMap — ODbL
- NYC Open Data — CC0 (varies by dataset)
- MTA GTFS-RT — open data
- NOAA Weather API — public domain
