# README Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the working-log style `README.md` with a concise, GitHub-native pitch and migrate the existing content to an expanded `docs/project-overview.md`.

**Architecture:** Two-file change. `git mv` preserves history when renaming `README.md` → `docs/project-overview.md`. The new `README.md` is written from scratch following the spec's 11-section structure (target 150-250 lines, no Columbia/E6895 framing in body). `docs/project-overview.md` becomes the canonical academic + deep-context document, inheriting the existing content plus four new sections (Project framing, Design decisions locked for V1, annotated per-phase deep-dives, Report & demo). Both files are then run through the `/humanizer` skill.

**Tech Stack:** Markdown · git · `superpowers` and `humanizer` skills. No code or test changes.

**Spec:** [`docs/superpowers/specs/2026-04-29-readme-rewrite-design.md`](../specs/2026-04-29-readme-rewrite-design.md)

---

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `README.md` | rename + recreate | GitHub-native pitch; converts visitor → `make up` or click into deep-dives |
| `docs/project-overview.md` | created via `git mv`, then expanded | Canonical project-context doc: academic framing, full architecture, status, locked design decisions, data sources, deep-dive index |
| `docs/assets/Screenshot_28-4-2026_2088_localhost.jpeg` | read-only reference | Hero image embedded in `README.md` |
| `CLAUDE.md`, `docs/*.md` | read-only reference | Source material for new project-overview sections |

The working tree currently contains unrelated modified/untracked files (frontend work in `apps/web/`, untracked docs in `docs/eval/`, `docs/frontend/`). **Every commit in this plan must `git add` only the specific files named in that step** — never `git add -A` or `git add .`.

---

## Conventions for every task

- Use `git add <exact-paths>` — never `git add -A`.
- Commit message format: `<type>: <subject>` (e.g., `docs: rename README to project-overview`). Conventional commits, no body unless noted.
- The `superpowers` and `humanizer` skill names assume Claude Code; adjust if executing in a different environment.
- All paths in this plan are relative to repo root: `/home/nyavana/columbia/6895/final-project/`.

---

### Task 0: Pre-flight checks

**Files:** none modified

- [ ] **Step 1: Confirm the spec file is present**

```bash
ls docs/superpowers/specs/2026-04-29-readme-rewrite-design.md
```

Expected: file path printed; no "No such file" error.

- [ ] **Step 2: Confirm the hero screenshot exists**

```bash
ls -la docs/assets/Screenshot_28-4-2026_2088_localhost.jpeg
```

Expected: file exists, non-zero size. If missing, STOP and ask the user — the hero image is a hard requirement.

- [ ] **Step 3: Confirm `README.md` is currently at repo root**

```bash
ls README.md && wc -l README.md
```

Expected: file exists, line count near 168.

- [ ] **Step 4: Note the unrelated dirty working tree**

```bash
git status --short
```

Expected: many modified/untracked files unrelated to README work. **Do not `git stash` and do not include these in any commit.** This plan touches only `README.md` and `docs/project-overview.md`.

---

### Task 1: Rename `README.md` to `docs/project-overview.md` (preserve git history)

**Files:**
- Move: `README.md` → `docs/project-overview.md`

- [ ] **Step 1: Run `git mv` (NOT `mv` + `git add`)**

```bash
git mv README.md docs/project-overview.md
```

The `git mv` form is required to preserve git blame / log history on the file. Plain `mv` followed by `git add` may not be detected as a rename depending on similarity threshold.

- [ ] **Step 2: Verify the rename was staged correctly**

```bash
git status --short docs/project-overview.md README.md
```

Expected: `R  README.md -> docs/project-overview.md` (the `R` indicates rename detection). If you see `D  README.md` and `A  docs/project-overview.md` instead, undo with `git restore --staged` and retry with `git mv`.

- [ ] **Step 3: Commit the rename in isolation**

```bash
git commit -m "docs: rename README to docs/project-overview" -- README.md docs/project-overview.md
```

Commit only the rename, before any content changes — this gives `git log --follow` the cleanest history. The `--` separator scopes the commit to those two paths even with the dirty working tree.

- [ ] **Step 4: Verify the commit**

```bash
git log -1 --stat
```

Expected: one commit, one file shown as `R100 README.md → docs/project-overview.md` (or close to 100% similarity).

---

### Task 2: Expand `docs/project-overview.md` per spec §6

This task replaces the file's content wholesale. The new content keeps every section that the spec marks "kept verbatim" or "kept as-is" plus four new sections (Project framing, Design decisions locked for V1, annotated per-phase deep-dives, Report & demo). Quickstart and "Try the agent" are removed because they move exclusively to the new `README.md` per spec §5.

**Files:**
- Modify: `docs/project-overview.md`

- [ ] **Step 1: Read the file to comply with the Write tool's "must read first" rule**

Read `docs/project-overview.md` in full (the post-`git mv` content is identical to the pre-rename `README.md`).

- [ ] **Step 2: Write the new content**

Use the Write tool to overwrite `docs/project-overview.md` with the following exact content:

````markdown
# Palimpsest NYC — Project overview

> An agentic LLM walking tour of Morningside Heights & the Upper West Side, grounded in public-domain archives, rendered in 3D.

This document is the canonical project-context companion to the top-level [`README.md`](../README.md). The README is the GitHub-facing pitch; this file is the academic and architectural deep-dive.

---

## Project framing

**Palimpsest NYC** is a graduate final project for **Columbia EECS E6895: Advanced Big Data and AI**.

Palimpsest plans a short walking tour for a bounded slice of NYC and narrates it from free, public-domain data sources — Wikipedia/Wikidata + OpenStreetMap in V1, with Chronicling America, NYPL, NYC Open Data, MTA, NOAA tracked as v2 expansions. Every claim in the narration is cited back to a retrieved source document via a strict five-field citation contract verified at generation time.

The entire codebase is being built end-to-end by Claude Code under a single human reviewer. Full session telemetry is captured to `logs/claude-sessions/*.jsonl` so the final report can quantify the cost, cycle time, and failure modes of agentic software engineering. The project is therefore both a working application and a data-collection apparatus: the application demonstrates a constrained, citation-grounded LLM agent; the telemetry produces an empirical record of how an autonomous coding agent assembled it.

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

**Backend (`apps/api`).** FastAPI + Python 3.12, wired in `app/main.py::create_app()` under a single async `lifespan` that hangs all long-lived singletons off `app.state` (LLM router, embedder, async DB engine, agent tool registry, session logger). Walk through the agent loop at `apps/api/app/agent/loop.py` — it carries the locked V1 contract (hard turn cap of 6, JSON terminal turn, five-field citation verifier, one corrective retry).

**Data layer.** PostgreSQL 16 + PostGIS + pgvector + pg_trgm, with schema owned by `apps/api/app/db/migrations/*.sql` (migrations-first). The `places` and `documents` tables carry 384-dim embeddings produced by a `BAAI/bge-small-en-v1.5` sentence-transformer singleton. Redis is wired for cache and breaker bookkeeping.

**LLM router.** `apps/api/app/llm/router.py` runs two tiers (`local` + `openrouter`) each with a 3-fail / 60s window / 30s cooldown circuit breaker. In V1 both tiers terminate at OpenRouter; v2 will repoint `LOCAL_LLM_BASE_URL` at an on-device endpoint (`llama.cpp`, vLLM, Ollama) without code change. Complexity (`simple` / `standard` / `complex`) is the only knob callers pass — the router decides backend, cache TTL, and breaker bookkeeping.

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
| §13.1-§13.3 / §14 | Live-data sources + VPS deploy | | deferred to v2 |

**Numbers as of milestone 1**: 928 places + 323 documents in postgres, all with 384-dim embeddings. 120 unit tests pass. End-to-end agent run (question → narration → 3 verified citations → ordered walk) validated live with `kimi-k2.6` via OpenRouter.

Full task ledger: [`openspec/changes/initial-palimpsest-scaffold/tasks.md`](../openspec/changes/initial-palimpsest-scaffold/tasks.md).

---

## Design decisions locked for V1

These constraints are load-bearing — relaxing any one of them requires an OpenSpec change, not just a code edit:

- **Schema is migrations-first.** `apps/api/app/db/models.py` is a typed read-only mirror of `apps/api/app/db/migrations/*.sql`. ORM `create_all` is never used in app code paths. Schema changes require `make nuke && make up`.
- **Citation contract is closed-set.** Every citation must carry the five fields `doc_id`, `source_url`, `source_type`, `span`, `retrieval_turn`, and `source_type` is restricted to `{wikipedia, wikidata, osm}` in V1. Adding a source means amending `V1_SOURCE_TYPES` and the agent system prompt together.
- **Complexity is the only router knob.** Callers pass `complexity ∈ {simple, standard, complex}`; the router selects backend, cache TTL, and breaker accounting. No caller-side backend selection or cache bypass.
- **Embedding dimension is locked at 384.** The `EMBEDDING_DIM` constant in `models.py` tracks the `EMBEDDING_DIM` env var. Changing the embedder requires a migration that drops and recreates the `vector(384)` column.
- **Each Python subproject owns its own venv.** `apps/api` and `apps/worker` each have their own `.venv`. No system Python installs; `make setup` is the entry point (uses `uv` if available, else stdlib `venv` + `pip`).
- **Hard turn cap of 6 in the agent loop.** Hitting the cap is a hard failure (`AgentLoopError`). The final turn strips the tool surface and forces a JSON terminal response with `max_tokens=8192`.

---

## OpenSpec workflow

This project uses [OpenSpec](https://github.com/fission-ai/openspec) for spec-driven development. Two changes are tracked:

- **Active:** [`openspec/changes/initial-palimpsest-scaffold/`](../openspec/changes/initial-palimpsest-scaffold/) — proposal, design, tasks, and capability specs for the V1 build.
- **Locked decisions:** [`openspec/changes/swap-llm-tiers-and-lock-mvp-decisions/`](../openspec/changes/swap-llm-tiers-and-lock-mvp-decisions/) — captures the V1 decisions that are deliberately frozen (LLM router rename, embedding model, citation contract, license).

Inspect changes locally:

```bash
openspec list
openspec show initial-palimpsest-scaffold
openspec status --change initial-palimpsest-scaffold
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

## Data sources & licenses

All V1 data sources are free / public-domain. Code is released under the **MIT License** — see [`LICENSE`](../LICENSE).

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

- [`swap-llm-tiers-2026-04-28.md`](swap-llm-tiers-2026-04-28.md) — V1 MVP lock-down: LLM router rename, embedding model selection, locked citation contract, license decision.
- [`db-and-embeddings-2026-04-28.md`](db-and-embeddings-2026-04-28.md) — §10 schema, ORM, and the `BAAI/bge-small-en-v1.5` embedder singleton.
- [`ingestion-2026-04-28.md`](ingestion-2026-04-28.md) — §11 Wikipedia/Wikidata + OSM Overpass ingestion, including the raw-cache replay layer.
- [`agent-2026-04-28.md`](agent-2026-04-28.md) — §9 / §12.1-4 agent loop, citation verifier, server-side `plan_walk`, and the `/agent/ask` SSE endpoint.

---

## Report & demo (planned)

The course deliverables tracked in [`openspec/changes/initial-palimpsest-scaffold/tasks.md`](../openspec/changes/initial-palimpsest-scaffold/tasks.md):

- **§13.7 — Final report.** Quantifies cost, cycle time, and failure modes of the agentic build using the per-session telemetry in `logs/claude-sessions/*.jsonl`.
- **§13.8 — 30-second demo video.** Captures an end-to-end walking-tour query: question → narration → citations → walk overlay on the map.

Both ship before the course submission deadline; this section will be updated with links once the artifacts are produced.
````

- [ ] **Step 3: Verify the file is well-formed**

```bash
wc -l docs/project-overview.md
head -1 docs/project-overview.md
```

Expected: line count between 200 and 300; first line is `# Palimpsest NYC — Project overview`.

- [ ] **Step 4: Verify all relative links resolve**

```bash
# Strip code blocks, then extract markdown links pointing to relative paths.
awk 'BEGIN{f=1} /^```/{f=1-f; next} f' docs/project-overview.md \
  | grep -oE '\]\(\.\./?[^)]+\)' \
  | sed 's/](\(.*\))/\1/' \
  | while read p; do
      target="docs/$p"
      target_clean=$(realpath -m --relative-to=. "$target")
      if [ -e "$target_clean" ]; then
        echo "OK: $p -> $target_clean"
      else
        echo "MISSING: $p -> $target_clean"
      fi
    done
```

Expected: every line begins with `OK:`. If any begin with `MISSING:`, fix the link in `docs/project-overview.md` and re-run.

- [ ] **Step 5: Stage and commit only this file**

```bash
git add docs/project-overview.md
git commit -m "docs: expand project-overview with framing, design decisions, deep-dive index" -- docs/project-overview.md
```

- [ ] **Step 6: Verify the commit**

```bash
git log -1 --stat
```

Expected: one file changed (`docs/project-overview.md`), no unrelated files included.

---

### Task 3: Write the new `README.md` from scratch

**Files:**
- Create: `README.md`

- [ ] **Step 1: Confirm `README.md` is absent at repo root before writing**

```bash
test ! -e README.md && echo "absent (good)" || echo "PRESENT - investigate"
```

Expected: `absent (good)`. If `PRESENT`, Task 1's `git mv` did not run; STOP and re-do Task 1.

- [ ] **Step 2: Write the new file**

Use the Write tool to create `README.md` with the following exact content:

````markdown
# Palimpsest NYC

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> An agentic LLM walking tour of Morningside Heights & the Upper West Side, grounded in public-domain archives, rendered in 3D.

![Palimpsest NYC web UI](docs/assets/Screenshot_28-4-2026_2088_localhost.jpeg)

*The "Ask Palimpsest" panel on the right streams a citation-grounded narration over Server-Sent Events while the map flies between cited places on the left.*

Palimpsest plans a short walking tour for a bounded slice of NYC and narrates it from free, public-domain sources — Wikipedia/Wikidata and OpenStreetMap. Every claim the agent makes is cited under a strict five-field contract that is verified at generation time, so the narration cannot reference a place the agent did not actually retrieve.

The bounded slice is by design: the corpus covers roughly 5km² around Morningside Heights and the Upper West Side, populated from Wikipedia, Wikidata, and the OSM Overpass API. Within that footprint the agent runs a single-tool retrieval loop with a hard 6-turn cap, a JSON terminal contract, and one corrective retry. The loop's narrowness is what makes the citation guarantees enforceable.

## Features

The four properties below are design constraints, not aspirational goals — they are enforced in code:

- Plans short walking tours from a free, public-domain archive (Wikipedia/Wikidata + OpenStreetMap).
- Single-tool agentic loop with a hard turn cap and a JSON terminal contract.
- Every claim cited under a strict five-field contract, verified at generation time.
- Server-streamed via SSE; the map renders the route with `flyTo` as citations arrive.

## Quickstart

Prereqs: Docker (with `compose` v2), `uv` (or Python 3.12 + `venv`), Node 20+. You will need an `OPENROUTER_API_KEY`.

Bring up the full stack — Postgres + PostGIS + pgvector, Redis, the FastAPI API, the heartbeat worker, and the React web app — with a single command:

```bash
# 1. configure environment
cp .env.example .env
# edit .env to set OPENROUTER_API_KEY

# 2. bring the stack up
make up

# 3. follow logs
make logs

# 4. hit the health check
curl http://localhost:8000/health
# → {"status":"ok"}

# 5. open the frontend
open http://localhost:5173
```

To stop everything: `make down`.

Note: schema changes require `make nuke && make up`, because the schema is owned by `apps/api/app/db/migrations/*.sql` and is applied by the postgres entrypoint on first volume init. ORM `create_all` is never used in app code paths.

## Try the agent

Once the stack is up, populate the corpus once and ask the agent a walking-tour question:

```bash
# 1. populate the 5km² Morningside Heights + UWS corpus (~30s total)
docker compose exec api python -m app.ingest.cli osm run
docker compose exec api python -m app.ingest.cli wikipedia run

# 2. ask the agent a question; watch SSE events stream live
curl -N "http://localhost:8000/agent/ask?q=Tell+me+about+a+gothic+cathedral+in+Morningside+Heights"
```

Re-running ingestion is idempotent — rows are upserted by their stable provenance keys.

The SSE stream emits the following frames in order:

| event | when |
|---|---|
| `turn` | each LLM turn boundary |
| `tool_call` | the agent invokes `search_places` |
| `tool_result` | matched documents come back from postgres |
| `narration` | terminal JSON payload with the prose |
| `citations` | terminal JSON payload with the cited documents |
| `walk` | server-side `plan_walk` over the cited place IDs |
| `done` | terminal marker after walk planning |

## How it works

The agent runs as a streamed multi-turn loop:

1. **Question in.** The user question hits `/agent/ask` over SSE.
2. **Search.** The agent dispatches `search_places` calls against a postgres+pgvector corpus, blending vector similarity (384-dim `bge-small`) with `pg_trgm` text search.
3. **Terminate.** Within a hard cap of 6 turns the loop emits a JSON terminal response: `{narration, citations[]}` under a strict five-field contract (`doc_id`, `source_url`, `source_type`, `span`, `retrieval_turn`).
4. **Verify.** A retrieval ledger checks every citation against documents actually returned in the conversation; one corrective retry on failure.
5. **Plan walk.** A server-side `plan_walk` step orders the cited place IDs into a route with leg distances.
6. **Stream to client.** Each stage emits an SSE frame; the React client renders narration and triggers `flyTo` on the map as frames arrive.

The loop is intentionally narrow: exactly one tool, exactly one terminal response shape, no branching after citations are verified. That narrowness is what makes each invariant easy to test in isolation and easy to reason about when something fails.

For the architecture diagram and the agent loop deep-dive, see [`docs/project-overview.md`](docs/project-overview.md) and [`docs/agent-2026-04-28.md`](docs/agent-2026-04-28.md).

## Tech stack

The stack splits into four layers; each was chosen so v2 can swap one piece without touching the others:

- **Backend:** FastAPI · Python 3.12 · async SQLAlchemy + asyncpg · PostgreSQL 16 + PostGIS + pgvector + pg_trgm · Redis.
- **Frontend:** React + Vite + TypeScript · MapLibre GL (3D OSM, swap-ready for Google Photorealistic 3D Tiles).
- **LLM routing:** OpenRouter, behind a two-tier router with circuit breakers; on-device endpoint is a v2 swap-in.
- **Embeddings:** `BAAI/bge-small-en-v1.5` (CPU, 384-dim singleton on `app.state`).

## Project layout

Three apps under `apps/`, plus an OpenSpec workflow at the root. Each app has its own Dockerfile and runs independently in `docker-compose.yml`:

- **`apps/api`** — FastAPI backend.

  Hosts `/agent/ask` (SSE), `/llm/chat`, the agent loop, the citation verifier, the walk planner, and the `python -m app.ingest.cli` ingestion CLI.

- **`apps/web`** — React + Vite + TypeScript SPA.

  MapLibre GL is the default map engine; the `MapEngine` interface keeps Google Photorealistic 3D Tiles a swap-in away.

- **`apps/worker`** — heartbeat-only in V1.

  Same image as `apps/api`. The topology exists so v2 can drop in a scheduler without rebuilding.

- **`openspec/`** — spec-driven change proposals.

  Active change is `initial-palimpsest-scaffold`; locked V1 decisions live in `swap-llm-tiers-and-lock-mvp-decisions`.

## Roadmap

V1 ships the smallest end-to-end system that answers a citation-grounded walking-tour question. V2 widens the data sources and adds deployment surface:

**V1 — shipped:**

- Monorepo + docker-compose
- FastAPI skeleton + two-tier LLM router with circuit breakers
- DB schema + embeddings (PostGIS + pgvector + pg_trgm; 384-dim)
- Wikipedia + OSM ingestion (928 places, 323 documents)
- Single-tool agent + five-field citation verifier + server-side walk planner
- SSE endpoint, frontend EventSource consumer, map markers + `flyTo`
- Per-session telemetry harness for cost / cycle-time / failure-mode analysis

**V2 — planned:**

- On-device LLM endpoint via the same env-driven router tier
- Live data sources: Chronicling America, NYPL, NYC Open Data, MTA, NOAA
- VPS deploy + scheduler in `apps/worker`

## Further reading

The deep-dives below are dated snapshots — each describes the system as of the date in the filename.

- [`docs/project-overview.md`](docs/project-overview.md) — full project context, architecture, status snapshot, locked design decisions.
- [`docs/agent-2026-04-28.md`](docs/agent-2026-04-28.md) — agent loop, citation verifier, SSE endpoint.
- [`docs/db-and-embeddings-2026-04-28.md`](docs/db-and-embeddings-2026-04-28.md) — schema + ORM + embedder.
- [`docs/ingestion-2026-04-28.md`](docs/ingestion-2026-04-28.md) — Wikipedia + OSM ingestion.
- [`docs/swap-llm-tiers-2026-04-28.md`](docs/swap-llm-tiers-2026-04-28.md) — V1 MVP lock-down (LLM router rename, embedding model, citation contract, license).
- [`openspec/changes/initial-palimpsest-scaffold/`](openspec/changes/initial-palimpsest-scaffold/) — active OpenSpec change.

## License

Code is MIT — see [`LICENSE`](LICENSE). Data sources are public-domain or open-licensed; the full table lives in [`docs/project-overview.md`](docs/project-overview.md).
````

- [ ] **Step 3: Verify line count is in range**

```bash
wc -l README.md
```

Expected: between 150 and 250 (inclusive). The target content above lands near 165. If it falls outside the range, stop and resolve before proceeding.

- [ ] **Step 4: Verify the hero image path resolves**

```bash
test -f docs/assets/Screenshot_28-4-2026_2088_localhost.jpeg && echo "OK" || echo "MISSING"
```

Expected: `OK`.

- [ ] **Step 5: Verify no Columbia / E6895 / academic framing leaked into the README body**

```bash
grep -nE -i 'columbia|e6895|graduate|academic|final project' README.md || echo "clean"
```

Expected: `clean`. (The string must NOT appear anywhere in the README body. The new README references the project-overview document, but never names the course or the academic framing.) If a match is found, edit the README to remove the leaked framing, then re-run.

- [ ] **Step 6: Verify all relative links resolve**

```bash
awk 'BEGIN{f=1} /^```/{f=1-f; next} f' README.md \
  | grep -oE '\]\([^)#][^)]*\)' \
  | sed 's/](\(.*\))/\1/' \
  | grep -v '^https\?://' \
  | while read p; do
      if [ -e "$p" ]; then
        echo "OK: $p"
      else
        echo "MISSING: $p"
      fi
    done
```

Expected: every line begins with `OK:`. If any line begins with `MISSING:`, fix the link in `README.md` and re-run.

- [ ] **Step 7: Stage and commit only this file**

```bash
git add README.md
git commit -m "docs: rewrite README as a GitHub-native project pitch" -- README.md
```

- [ ] **Step 8: Verify the commit**

```bash
git log -1 --stat
```

Expected: one file changed (`README.md`), no unrelated files included.

---

### Task 4: Run `/humanizer` over the new `README.md`

**Files:**
- Modify: `README.md`

The `humanizer` skill detects AI-writing patterns (inflated symbolism, em-dash overuse, rule of three, AI vocabulary, vague attributions, negative parallelisms, etc.) and proposes edits.

**Critical guardrail.** The skill's edits must NOT touch:

- Code blocks (anything between triple backticks).
- Inline code (anything between single backticks): file paths, command names, identifier names, env-var names, event names like `tool_call`, table headers like `| event | when |`.
- Link targets (the part inside `]( ... )`) — relative paths and external URLs.
- Heading text — leave H1/H2/H3 wording unchanged so the spec's section-by-section structure is preserved.
- The shields.io badge URL.

The skill may rewrite *prose* paragraphs, captions, bullets, and table cells that contain only natural language.

- [ ] **Step 1: Invoke the humanizer skill**

Use the Skill tool with `skill="humanizer"`. The skill will load and present its rewriting guidance.

- [ ] **Step 2: Read the current `README.md` content**

Use the Read tool on `README.md`. Apply the humanizer guidance to natural-language sections only.

Concrete patterns to look for in this specific file:

- **Em-dash overuse.** The current draft uses several em-dashes (`—`) in feature bullets and the License section. Replace some with periods or commas where the dash is decorative rather than load-bearing.
- **Rule of three.** The opening paragraph ("Wikipedia/Wikidata + OpenStreetMap" is fine; check that bullet lists don't all default to threes-of-things).
- **Vague attribution.** The "How it works" intro uses "The agent runs as a streamed multi-turn loop" — keep, it is concrete.
- **AI vocabulary.** Watch for words like *seamlessly*, *robust*, *leverage*, *delve*, *underscore*, *elevate*. The current draft uses none of these intentionally; reject any humanizer suggestion that introduces them while "rewriting".
- **Filler phrases.** Watch for "It is worth noting that", "In order to", "At the end of the day".

- [ ] **Step 3: Apply edits via the Edit tool**

For each prose change the humanizer recommends, use the Edit tool with exact `old_string` / `new_string` pairs. Skip recommendations that touch code blocks, inline code, link targets, or heading text per the guardrail above.

- [ ] **Step 4: Re-verify acceptance criteria after edits**

```bash
wc -l README.md
grep -nE -i 'columbia|e6895|graduate|academic|final project' README.md || echo "clean"
test -f docs/assets/Screenshot_28-4-2026_2088_localhost.jpeg && echo "image OK" || echo "image MISSING"
```

Expected: line count still in [150, 250]; `clean`; `image OK`.

- [ ] **Step 5: Stage and commit only this file**

```bash
git add README.md
git commit -m "docs: humanize README prose" -- README.md
```

If the humanizer pass produced no changes, skip the commit and move on.

---

### Task 5: Run `/humanizer` over `docs/project-overview.md`

**Files:**
- Modify: `docs/project-overview.md`

Apply the same guardrails as Task 4, with one addition: the **ASCII architecture diagram** (lines beginning with `┌`, `│`, `└`, `▼`, etc.) is structural content, not prose — never edit it. The status table's content is empirical fact (place counts, document counts, model name); never paraphrase.

- [ ] **Step 1: Invoke the humanizer skill**

Use the Skill tool with `skill="humanizer"`. (If still loaded from Task 4, you may proceed directly to Step 2.)

- [ ] **Step 2: Read the current `docs/project-overview.md`**

Use the Read tool on `docs/project-overview.md`. Apply the humanizer guidance to prose sections only.

The newly-written sections (most likely to need rewriting): **Project framing** (3 paragraphs), **Architecture** per-layer descriptions (4 paragraphs), **Design decisions locked for V1** (bullet body text), **Per-phase deep-dives** (annotation lines), **Report & demo (planned)**.

The inherited sections — **Status as of milestone 1**, **OpenSpec workflow** body, **On-device LLM (v2)**, **Local Python dev**, **Data sources & licenses** — are already hand-written and have been in the repo for weeks. Do not rewrite them unless a clear AI-ism appears.

- [ ] **Step 3: Apply edits via the Edit tool**

For each prose change, use Edit with exact `old_string` / `new_string` pairs. Skip recommendations that touch:
- The ASCII architecture diagram
- Code blocks (triple-backtick fences)
- Inline code: file paths, command names, identifier names, env-var names
- Link targets
- The status table
- Bullet items in **Data sources & licenses** (they are factual license labels, not prose)
- Heading text

- [ ] **Step 4: Re-verify links still resolve**

```bash
awk 'BEGIN{f=1} /^```/{f=1-f; next} f' docs/project-overview.md \
  | grep -oE '\]\(\.\./?[^)]+\)' \
  | sed 's/](\(.*\))/\1/' \
  | while read p; do
      target=$(realpath -m --relative-to=. "docs/$p")
      [ -e "$target" ] && echo "OK: $p" || echo "MISSING: $p"
    done
```

Expected: every line begins with `OK:`.

- [ ] **Step 5: Stage and commit only this file**

```bash
git add docs/project-overview.md
git commit -m "docs: humanize project-overview prose" -- docs/project-overview.md
```

If the humanizer pass produced no changes, skip the commit.

---

### Task 6: Final verification

**Files:** none modified

Run the full acceptance-criteria checklist from spec §8.

- [ ] **Step 1: README line count in [150, 250]**

```bash
wc -l README.md
```

- [ ] **Step 2: README contains all 11 required sections in the correct order**

```bash
grep -nE '^## ' README.md
```

Expected output (in this order, after the title and intro):
```
## Features
## Quickstart
## Try the agent
## How it works
## Tech stack
## Project layout
## Roadmap
## Further reading
## License
```

(Title, hero screenshot, and intro paragraph live above the first `##` heading and don't show up in this grep.)

- [ ] **Step 3: README contains no Columbia / E6895 / academic framing**

```bash
grep -nE -i 'columbia|e6895|graduate|academic|final project' README.md || echo "clean"
```

Expected: `clean`.

- [ ] **Step 4: project-overview.md exists and was created via rename**

```bash
test -f docs/project-overview.md && echo "file exists"
git log --follow --diff-filter=R --oneline -- docs/project-overview.md | head -1
```

Expected: `file exists`; one rename commit shown.

- [ ] **Step 5: project-overview.md contains all 10 required sections**

```bash
grep -nE '^## ' docs/project-overview.md
```

Expected (in this order):
```
## Project framing
## Architecture
## Status as of milestone 1
## Design decisions locked for V1
## OpenSpec workflow
## On-device LLM (v2)
## Local Python dev (outside Docker)
## Data sources & licenses
## Per-phase deep-dives
## Report & demo (planned)
```

- [ ] **Step 6: Hero screenshot path resolves from README**

```bash
grep -oE 'docs/assets/[^)]+' README.md | while read p; do
  test -e "$p" && echo "OK: $p" || echo "MISSING: $p"
done
```

Expected: `OK: docs/assets/Screenshot_28-4-2026_2088_localhost.jpeg`.

- [ ] **Step 7: All relative links in README resolve**

```bash
awk 'BEGIN{f=1} /^```/{f=1-f; next} f' README.md \
  | grep -oE '\]\([^)#][^)]*\)' \
  | sed 's/](\(.*\))/\1/' \
  | grep -v '^https\?://' \
  | while read p; do
      [ -e "$p" ] && echo "OK: $p" || echo "MISSING: $p"
    done
```

Expected: every line begins with `OK:`.

- [ ] **Step 8: Both files have a humanizer commit (or a documented skip)**

```bash
git log --oneline -- README.md docs/project-overview.md | head -10
```

Expected commit history (newest at top):
1. `docs: humanize project-overview prose` (or skipped per Task 5 step 5)
2. `docs: humanize README prose` (or skipped per Task 4 step 5)
3. `docs: rewrite README as a GitHub-native project pitch`
4. `docs: expand project-overview with framing, design decisions, deep-dive index`
5. `docs: rename README to docs/project-overview`

If a humanize commit was skipped because the pass produced no changes, note that explicitly when reporting completion.

- [ ] **Step 9: Visual sanity check**

Render `README.md` in a markdown previewer (GitHub web, VS Code preview, or `glow README.md`). Confirm:
- The hero screenshot displays.
- The MIT badge displays.
- The SSE event table renders cleanly.
- The Project layout bullets show their two-paragraph structure.

If any visual element fails, diagnose (likely a relative-path or image-syntax issue) and patch with a follow-up commit.

- [ ] **Step 10: Report completion**

Summarize for the user:
- Final line counts for both files.
- Final commit list for the two files (output of Step 8).
- Whether each humanizer pass produced changes.
- Any acceptance criterion that was not strictly met and why.

---

## Risks recap (from spec §9)

- **`git mv` not used.** Mitigated by Task 1 Step 2 verification.
- **`/humanizer` over-edits technical content.** Mitigated by the Task 4 / Task 5 guardrails listing exactly which content is off-limits.
- **Status numbers go stale.** Accepted — the doc is dated "as of milestone 1".
- **Hero screenshot filename has unsafe characters.** Verified clean in Task 0 Step 2.
- **Unrelated dirty working tree gets pulled into a commit.** Mitigated by always using `git add <exact-paths>` and the `--` path-scoped commit form.

---

## Self-review notes

(Reviewed against spec on 2026-04-29.)

- **Spec coverage:** Every section in spec §5 (new README) and §6 (project-overview) maps to specific exact content in Task 2 / Task 3. Acceptance criteria from §8 are all enforced in Task 6 verification steps.
- **Placeholder scan:** No "TBD", "TODO", "implement later", or "fill in details" — every step has a concrete command and/or exact content.
- **Type / identifier consistency:** Section headings, file paths, command names match between the spec, the README, and the project-overview.
- **One ambiguity carried from spec:** The MIT badge's `LICENSE` link target uses a repo-root-relative path (`LICENSE`), which is correct for `README.md` (at repo root) but would be `../LICENSE` from `docs/project-overview.md`. Both files use the right relative form in the Task 2 / Task 3 content.
