# README rewrite — design spec

**Date:** 2026-04-29
**Status:** Approved by user
**Scope:** Restructure the project's `README.md` into a GitHub-native pitch and migrate the current README's content into an expanded `docs/project-overview.md`.

---

## 1. Goal

Replace the existing working-log style `README.md` with a concise, GitHub-native pitch that converts a first-time visitor into either a working `make up` or a click into the deep-dive docs. Move all academic framing, status snapshots, and design-decision notes into `docs/project-overview.md`, which becomes the canonical project-context document.

## 2. Non-goals

- No changes to code, tests, OpenSpec proposals, or CLAUDE.md.
- No new screenshots, recordings, or design assets beyond the existing `docs/assets/Screenshot_28-4-2026_2088_localhost.jpeg`.
- No restructuring of the existing dated phase docs (`agent-2026-04-28.md`, `db-and-embeddings-2026-04-28.md`, `ingestion-2026-04-28.md`, `swap-llm-tiers-2026-04-28.md`).

## 3. Audience strategy

The new README serves both external GitHub visitors (recruiters, peers, OSS browsers) and the course reviewer, but the academic framing is explicitly **not** in the README itself — it lives in `docs/project-overview.md`, linked from the README's "Further reading" section. The README itself reads as a polished open-source project README; visitors who want the Columbia E6895 framing or the agentic-build research angle follow one link to get the full context.

## 4. File operations

1. Rename `README.md` → `docs/project-overview.md` using `git mv` to preserve history.
2. Expand `docs/project-overview.md` with the new sections in §6 below.
3. Write a fresh `README.md` from scratch following the structure in §5 below.
4. Run `/humanizer` over both `README.md` and `docs/project-overview.md`.

## 5. New `README.md` structure

Target length: ~150-250 lines. Sections in order:

1. **Title + tagline + license badge.** `# Palimpsest NYC`. Existing tagline ("An agentic LLM walking tour of Morningside Heights & the Upper West Side, grounded in public-domain archives, rendered in 3D"). Single MIT badge sourced from shields.io (`https://img.shields.io/badge/license-MIT-blue.svg`) linked to the local `LICENSE` file. No graduate-project framing here.

2. **Hero screenshot.** `![Palimpsest NYC web UI](docs/assets/Screenshot_28-4-2026_2088_localhost.jpeg)` immediately under the tagline, with a one-sentence caption pointing at the "Ask Palimpsest" panel and the SSE-streamed narration.

3. **Features — 4 bullets.**
   - Plans short walking tours from a free, public-domain archive (Wikipedia/Wikidata + OpenStreetMap)
   - Single-tool agentic loop with a hard turn cap and JSON terminal contract
   - Every claim cited under a strict five-field contract, verified at generation time
   - Server-streamed via SSE; map renders the route with `flyTo` as citations arrive

4. **Quickstart.** Reuse the existing "Quickstart (local Docker)" block: `cp .env.example .env`, `make up`, `make logs`, `curl http://localhost:8000/health`, open `http://localhost:5173`. Tighten surrounding prose; remove the v2 caveat (it lives in project-overview).

5. **Try the agent (SSE demo).** Two-step CLI: populate the corpus (`docker compose exec api python -m app.ingest.cli {osm,wikipedia} run`), then `curl -N "http://localhost:8000/agent/ask?q=..."`. Lists the SSE event types in order (`turn → tool_call → tool_result → narration → citations → walk → done`).

6. **How it works — 3 sentences.** Question → `search_places` tool calls against the postgres+pgvector corpus → JSON-with-citations terminal turn → server-side `plan_walk` over cited place IDs → SSE frames to the client. No diagram inline. Link to `docs/project-overview.md#architecture` for the full diagram and to `docs/agent-2026-04-28.md` for the loop deep-dive.

7. **Tech stack.** Compact 4-line list:
   - **Backend:** FastAPI · Python 3.12 · async SQLAlchemy + asyncpg · PostgreSQL 16 + PostGIS + pgvector + pg_trgm · Redis
   - **Frontend:** React + Vite + TypeScript · MapLibre GL (3D OSM, swap-ready for Google Photorealistic 3D Tiles)
   - **LLM routing:** OpenRouter (two configurable tiers; on-device endpoint is a v2 swap-in)
   - **Embeddings:** `BAAI/bge-small-en-v1.5` (CPU, 384-dim singleton on `app.state`)

8. **Project layout.** 4 single-line entries:
   - `apps/api` — FastAPI backend, agent loop, ingestion CLI
   - `apps/web` — React + Vite SPA with MapLibre map engine
   - `apps/worker` — heartbeat-only in V1; reserved for v2 scheduler
   - `openspec/` — spec-driven change proposals

9. **Roadmap.** Two grouped lists.
   - **V1 shipped:** monorepo + docker-compose, FastAPI skeleton, two-tier LLM router, DB schema + embeddings, Wikipedia + OSM ingestion (928 places, 323 docs), single-tool agent + citation verifier, server-side walk planner, SSE endpoint, frontend EventSource + map markers.
   - **V2 planned:** on-device LLM endpoint, live data sources (Chronicling America, NYPL, NYC Open Data, MTA, NOAA), VPS deploy, scheduler in `apps/worker`.

10. **Further reading.** Bulleted links:
    - `docs/project-overview.md` — full project context, academic framing, status snapshot, locked design decisions
    - `docs/agent-2026-04-28.md` · `docs/db-and-embeddings-2026-04-28.md` · `docs/ingestion-2026-04-28.md` · `docs/swap-llm-tiers-2026-04-28.md` — phase deep-dives
    - `openspec/changes/initial-palimpsest-scaffold/` — active OpenSpec change

11. **License.** One sentence: code is MIT (see `LICENSE`); data sources are public-domain or open licenses — full table in `docs/project-overview.md`.

## 6. Expanded `docs/project-overview.md` structure

Inherits the current `README.md` content; the rename via `git mv` preserves git history. Sections in order after the rewrite:

1. **Project framing (new, expanded — 2-3 paragraphs).** Columbia EECS E6895 final project. The agentic-build angle promoted from a passing line to a real section: the codebase is being written end-to-end by Claude Code under a single human reviewer, with full per-session telemetry captured to `logs/claude-sessions/*.jsonl` for the report's empirical analysis of agentic software engineering (cost, cycle time, failure modes).

2. **Architecture (deep).** Full ASCII diagram from the current README, plus one short paragraph per layer (LLM router, agent loop, ingestion, frontend) with links to the phase docs.

3. **Status as of milestone 1.** Lifted directly from the current README's Status table, including the "928 places + 323 documents, 120 unit tests, end-to-end run validated with `kimi-k2.6`" numbers.

4. **Design decisions locked for V1 (new).** Distilled from `CLAUDE.md` "Conventions specific to this repo":
   - Schema is migrations-first; ORM models are read-only mirrors.
   - Citation contract is locked: 5 required fields, closed-set `source_type`.
   - Complexity is the only router knob (`simple`/`standard`/`complex`).
   - Embedding dim locked at 384.
   - Each Python subproject owns its own `.venv`.

5. **OpenSpec workflow.** Existing section, lightly expanded with links to the active change and the locked-decisions change.

6. **On-device LLM (v2).** Existing v2 swap-in note, kept verbatim.

7. **Local Python dev.** Existing `make setup` / venv-per-subproject section, kept verbatim.

8. **Data sources & licenses.** Existing license table, kept as-is.

9. **Per-phase deep-dives.** Existing list, with a one-line "what this doc covers" annotation beside each entry.

10. **Report & demo (planned).** New short section: final report and 30s demo video are tracked as §13.7 / §13.8 — placeholder note pointing at the openspec tasks file.

## 7. `/humanizer` pass

Run `/humanizer` over both files after they are written:

1. New `README.md` — pitch prose is the primary risk surface for AI-isms (inflated symbolism, three-of-a-kind lists, em-dash overuse).
2. `docs/project-overview.md` — even though it inherits hand-written content, the new "Project framing" and "Design decisions locked for V1" sections are AI-authored and need the same scrub.

Apply `/humanizer` to each file independently so the rule of three, em-dash, and AI-vocabulary fixes are scoped per-file rather than averaged across both.

## 8. Acceptance criteria

- `README.md` is between 150 and 250 lines.
- `README.md` contains, in order: title, tagline, hero screenshot, features, quickstart, agent SSE demo, "How it works", tech stack, project layout, roadmap, further reading, license.
- `README.md` has no "graduate final project" / Columbia / E6895 mentions in its body — those mentions live exclusively in `docs/project-overview.md`.
- `docs/project-overview.md` exists, was created by `git mv`, and includes the 10 sections in §6.
- The hero screenshot path `docs/assets/Screenshot_28-4-2026_2088_localhost.jpeg` resolves and renders.
- Both files have been processed through `/humanizer`.
- All relative links in both files resolve (no broken paths).

## 9. Risks and mitigations

- **Risk:** `git mv` not used, history is lost. **Mitigation:** Implementation plan must call `git mv` explicitly, not `mv` + `git add`.
- **Risk:** `/humanizer` over-edits the technical sections (quickstart commands, SSE event names, env-var names). **Mitigation:** Run `/humanizer` and review its diff; reject any change that touches a code block, command, or identifier.
- **Risk:** Status numbers in `docs/project-overview.md` go stale. **Mitigation:** This is acceptable — the doc is dated by its own "as of milestone 1" framing. Future status changes update this doc, not the README.
- **Risk:** Hero screenshot filename has spaces or unusual characters that break markdown rendering. **Mitigation:** Verified — filename is `Screenshot_28-4-2026_2088_localhost.jpeg`, no spaces, safe in markdown image syntax.
