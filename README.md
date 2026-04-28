# Palimpsest NYC

> An agentic LLM walking tour of Morningside Heights & the Upper West Side, grounded in public-domain archives, rendered in 3D.

A graduate final project for **Columbia EECS E6895: Advanced Big Data and AI**.

Palimpsest plans a short walking tour for a bounded slice of NYC and narrates it from free historical and live data sources — Wikipedia/Wikidata, Chronicling America, NYPL Digital Collections, OpenStreetMap, NYC Open Data, MTA GTFS-RT, and NOAA. Every claim in the narration is cited back to a retrieved source document.

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

**Week 1** — scaffolding foundation: monorepo, docker-compose, FastAPI skeleton, LLM router, MapEngine abstraction, meta-instrumentation harness.

See `openspec/changes/initial-palimpsest-scaffold/tasks.md` for the full plan.

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
