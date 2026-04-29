## Context

Palimpsest NYC is being built end-to-end by Claude Code with a single human reviewer over a four-week window, targeting an EECS E6895 final project demo. The hardware and service landscape is unusual and shapes most decisions:

- **Development host**: Ubuntu 24.04 on WSL2 running on Windows 11.
- **Local inference**: `llama.cpp` serving `google/gemma-4-26B-A4B-it` on the Win11 side, reachable from WSL containers via `http://host.docker.internal:8080/v1`, bound to 16 GB VRAM on an RTX 4070 Ti Super.
- **Cloud inference**: OpenRouter API (`openai/gpt-5.4` and `openai/gpt-5.4-mini`) with a generous Claude-Code-covered development budget.
- **Production target**: a single RackNerd VPS (2 vCPU, 2.5 GB RAM, 45 GB SSD) that must run Postgres + Redis + API + static web. Raw ingestion archives and local LLM stay on the dev box; only distilled data ships to the VPS.
- **Timeline**: 4 weeks, solo reviewer, Claude as implementer.

The course demands visible demonstration of both "Big Data" (volume / velocity / variety) and "Advanced AI" (non-trivial ML or agentic systems). A plain LLM+map wrapper would fail on the Big Data axis; a pure data pipeline would fail on the AI axis. Our defense on both fronts is the **dual-backend LLM router** plus a **heterogeneous ingestion pipeline** spanning public-domain archives, live NYC feeds, and structured spatial data.

WorldMonitor (`koala73/worldmonitor`) is used as an architectural reference only. No source is forked; patterns are borrowed, not code.

## Goals / Non-Goals

**Goals:**

- Ship a working end-to-end demo by the end of week 4 that runs locally under `docker compose up` with one command.
- Prove a cost-aware dual-backend LLM router can serve both bulk-processing (local Gemma-4) and user-facing narration (cloud GPT-5.4) with measurable $/call and quality deltas.
- Ground every narrative claim the agent makes in a cited source from the ingested corpus (Wikipedia/Wikidata, Chronicling America, NYPL Digital Collections). No uncited facts.
- Keep the frontend 3D map engine behind a strict interface so the v2 upgrade to Google Photorealistic 3D Tiles is a one-file swap, not a rewrite.
- Capture full Claude Code session telemetry from day 1 to enable an "agentic engineering case study" chapter in the final report.
- Make the entire stack self-hostable with `docker compose up` and a single `.env` file so the grader can reproduce the demo.

**Non-Goals:**

- Real-time turn-by-turn navigation (Google Maps solves this; we render a planned route and let users walk it at their own pace).
- Comprehensive NYC coverage. v1 covers Morningside Heights + Upper West Side only.
- Booking, payments, or any transactional integrations.
- Cross-session user memory / long-term personalization. Session-scoped memory only.
- Running local inference on the VPS. The Gemma-4 backend stays on the Win11 dev box; the VPS relies solely on OpenRouter.
- High-availability, horizontal scaling, or multi-region deployment. Single-VPS single-writer is sufficient.
- Forking or reusing WorldMonitor source code. Architectural inspiration only.

## Decisions

### 1. Dual-backend LLM router is a first-class module, not a utility

The router lives at `apps/api/app/llm/router.py` and exposes a single `LLMRouter.chat(request: ChatRequest) -> ChatResponse` interface. It selects a backend by the request's `complexity` field (`simple | standard | complex`) plus runtime signals (queue depth, circuit-breaker state). Every call emits a telemetry record: backend, model, latency, tokens in/out, dollar cost, cache hit, error.

| Complexity | Default backend | Model | Typical use |
|---|---|---|---|
| `simple` | local | `gemma-4-26B-A4B-it` | classification, relevance filters, OCR cleanup, batch tagging, embeddings pre-processing |
| `standard` | cloud | `openai/gpt-5.4-mini` | re-ranking, short answer generation, tool-calling dispatch |
| `complex` | cloud | `openai/gpt-5.4` | narration, walk planning, multi-step agent loops |

**Fallback ladder**: if local is unreachable or circuit-broken, `simple` silently upgrades to `gpt-5.4-mini`. If OpenRouter is unreachable, `simple` stays local and `standard/complex` surface an explicit error (we do not downgrade user-facing narration to a small local model without consent).

**Caching**: Redis-keyed by SHA-256 of the normalized request (`model + messages + temperature + tool schema`). TTL 24h for simple, 6h for standard, 1h for complex. Cache hits still emit a telemetry record with `cached: true`.

### 2. Postgres is the single source of truth

Rather than introduce a vector DB + graph DB + time-series DB + GIS DB, we use **one Postgres 16 instance** with three extensions:

- `postgis` — spatial indexes for POI / place / route queries
- `pgvector` — embedding columns for semantic retrieval (`halfvec`/`vector(768)`)
- `pg_trgm` — fuzzy text matching for OCR'd historical text

Rationale: the VPS has 2.5 GB RAM. Running one well-tuned Postgres is drastically easier than juggling three services. A single `places` table with a `geog geography` column, a `content` text column, and an `embedding vector(768)` column covers ~90% of queries. Separate `documents` table holds historical sources with FKs back to `places` for provenance.

### 3. MapEngine interface is contract-locked from day 1

The frontend imports `MapEngine` only. Concrete engines live in `apps/web/src/map/engines/`. The v1 `MaplibreEngine` uses MapLibre GL JS with an OSM tile source and the `maplibre-gl-basic-buildings-3d` style for extruded 3D buildings. The stub `GoogleTilesEngine` is a typed file that throws on every method. A factory at `apps/web/src/map/index.ts` picks the engine based on `import.meta.env.VITE_MAP_ENGINE` (`maplibre` | `google-3d`).

No React component may import MapLibre types directly. A lint rule in `apps/web/eslint.config.js` enforces this.

### 4. The meta-instrumentation harness runs before any product feature

`apps/api/app/meta/session_log.py` writes one JSONL record per Claude Code session:

```json
{
  "session_id": "2026-04-11T01:22:33Z-a1b2",
  "started_at": "2026-04-11T01:22:33Z",
  "ended_at": "2026-04-11T01:47:18Z",
  "goal": "scaffold fastapi backend",
  "prompt_tokens": 12034,
  "completion_tokens": 8501,
  "cost_usd": 0.21,
  "files_touched": ["apps/api/app/main.py", "apps/api/pyproject.toml"],
  "human_edits_after": 3,
  "outcome": "success",
  "notes": "router health check wired up"
}
```

Logs never go to git (they're in `.gitignore`). The harness also exposes a `/internal/metrics` JSON endpoint for local dashboards. This is the data that powers the agentic-engineering chapter of the final report.

### 5. Data ingestion is staged, not streamed, with local-first heavy lifting

The dev box ingests, cleans, embeds, and filters the raw archives. Only distilled rows and small artifacts (images) make it to the VPS Postgres. Chronicling America raw ZIPs never touch production; we run them through local Gemma-4 on the Win11 box to produce ~200K "distilled article" rows that include cleaned text, resolved coordinates, dates, and embeddings.

Stage layout:

```
raw/     → dev-box only, not committed, not on VPS
bronze/  → parquet on dev-box, partitioned by {source, year}
silver/  → Postgres on dev-box for local dev
gold/    → Postgres on VPS, dump/restored from silver via pg_dump
```

### 6. Agent loop uses native OpenRouter tool-calling, not a framework

No LangChain, no LangGraph, no PydanticAI for the core agent. We use OpenRouter's OpenAI-compatible `tools` parameter directly. Rationale: for the final report, we want to describe exactly what the agent does — frameworks hide the interesting parts.

The loop is ~150 lines of Python: build messages, call LLM with tools, if tool call then dispatch to handler, append result, repeat with a hard turn cap (default 6). Handlers are plain async functions in `apps/api/app/agent/tools/`.

### 7. Citations are mandatory at generation time, not post-hoc

When the agent generates narration, the prompt contract requires it to output a JSON structure like:

```json
{
  "narration": "The Cathedral of St. John the Divine was begun in 1892...",
  "citations": [
    {"doc_id": "wikipedia:Cathedral_of_Saint_John_the_Divine", "span": "1-2"},
    {"doc_id": "chronicling-america:nytribune:1892-12-27:p3", "span": "1"}
  ]
}
```

A verifier pass checks that every citation points to a document actually retrieved in this turn, and that the narration's claims map to at least one citation per sentence (best-effort). Narrations that fail verification are re-generated once, then surfaced with a visible uncertainty warning.

### 8. Frontend visual design runs through the `/ui-ux-pro-max:ui-ux-pro-max` skill before any component is written

The frontend has been a typed scaffold (Vite + React + TS + Tailwind + MapEngine) since Week 1, but no opinionated UI exists yet — `App.tsx`, `ChatPane.tsx`, and `MapView.tsx` are minimal wiring. Hand-rolling Tailwind on top of that scaffold reliably produces a generic LLM-app aesthetic (gray cards, muted accents, default Inter, neutral spacing) that will not read well in an EECS E6895 demo.

The `/ui-ux-pro-max:ui-ux-pro-max` skill encapsulates a curated design system (50+ styles, 161 palettes, 57 font pairings, 99 UX guidelines, 25 chart types) tuned for the React + Tailwind stack already locked in. We make it the **mandatory first step** of any frontend visual work — not a polish pass at the end:

1. **Plan/design** — invoke the skill with `action: design`, `stack: React + Tailwind`, `product: agentic walking-tour app`. The skill returns a brief covering layout, palette, typography, components, and interaction primitives.
2. **Persist** — the brief is committed to `docs/frontend/ui-design-brief.md` and the chosen tokens to `apps/web/src/styles/tokens.ts` so subsequent sessions and the final report can reference what was decided and why.
3. **Implement** — components are built against the brief, importing only the `MapEngine` interface for map work (per Decision 3) and only the token module for visual choices.
4. **Review** — invoke the skill again with `action: review` over the implemented surface; address severity ≥ medium findings before the task closes.

Tasks §12.5.1–12.5.4 encode this workflow. `apps/web/eslint.config.js` and the existing MapEngine boundary remain authoritative for code-level constraints; the skill governs visual and UX choices, not architecture.

## Risks / Trade-offs

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Local Gemma-4 unreachable from WSL containers due to Win11 firewall / Hyper-V NAT | Medium | High (week 1 blocker) | Document `netsh` firewall rule + bind to `0.0.0.0`; fall back to cloud for all complexities with a visible banner |
| Chronicling America ingest exceeds dev-box disk budget | Medium | Medium | Filter at download: only NY papers 1850–1950 via LCCN allowlist; stream-process ZIPs without retaining |
| OpenRouter tool-calling API quirks break the agent loop | Medium | High | Adapter pattern + integration test against a recorded transcript; JSON-mode fallback if `tools` breaks |
| VPS memory pressure (Postgres + Redis + API compete for 2.5 GB) | High | High | Tune `shared_buffers=384MB`, `work_mem=16MB`; cap API workers to 2; Redis `maxmemory 192mb allkeys-lru`; defer to week-4 deploy |
| Map-engine abstraction leaks MapLibre types into React components | Medium | High (v2 rewrite) | ESLint rule forbidding `maplibre-gl` imports outside `apps/web/src/map/engines/`; CI check |
| Citation verifier produces false positives that block narration | Low | Medium | Best-effort verification with a single retry; surface warning, never hard-block |
| Meta-log format churns and invalidates cost analysis data | Low | High (half the report) | Version the JSONL schema (`schema_version` field); add a tiny migration tool; freeze format after week 1 |
| Google 3D Tiles upgrade path is wishful thinking | Low | Low | Week 2 integration spike (2-hour timebox) to confirm CesiumJS + Google tiles works against current MapEngine interface |
| Solo reviewer bandwidth is exhausted before Claude's output | Medium | High | Hard WIP limit: one task group in flight at a time; tasks.md enforced as sequential queue |
| Professor grades down for using Claude Code to build everything | Very Low | Catastrophic | Permission was obtained in advance; entire process is documented as a first-class contribution |
