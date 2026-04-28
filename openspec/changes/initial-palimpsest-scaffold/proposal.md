## Why

Palimpsest NYC is a graduate final project for Columbia's EECS E6895 (Advanced Big Data and AI). The goal is an LLM agent that plans agentic walking tours of a bounded slice of New York City (Morningside Heights + Upper West Side for v1), grounding its narration in free, public-domain datasets (Wikipedia/Wikidata, Chronicling America, NYPL Digital Collections, NYC Open Data, OpenStreetMap, MTA GTFS-RT, NOAA). The project has two coupled contributions:

1. **The product** — an end-to-end cloud-native application with a 3D map front-end, a retrieval-augmented LLM agent, and a spatial + temporal data pipeline.
2. **The process** — a case study in agentic software engineering. The entire codebase is implemented by Claude Code under a single human reviewer, with full session telemetry captured from day one so the final report can quantify cost, cycle time, and failure modes of AI-driven delivery.

No proposal submission is required by the course, but the OpenSpec artifacts serve as our internal contract so every subsequent Claude Code session starts with aligned context.

## What Changes

- **ADD** a monorepo scaffold with three apps (`api`, `worker`, `web`) and a root `docker-compose.yml` for local development.
- **ADD** a dual-backend LLM router that transparently dispatches requests between OpenRouter (`openai/gpt-5.4` and `openai/gpt-5.4-mini`) and a locally-hosted `google/gemma-4-26B-A4B-it` running on Win11 via `llama.cpp`'s OpenAI-compatible HTTP server.
- **ADD** a `MapEngine` abstraction on the frontend with a MapLibre + OSM 3D-buildings implementation for v1, and a stubbed `GoogleTilesEngine` ready for later upgrade to Google Photorealistic 3D Tiles.
- **ADD** a meta-instrumentation harness that captures every Claude Code session to `logs/claude-sessions/*.jsonl` (prompt, tokens, dollar cost, files touched, human edit ratio, outcome) so the final report can report empirical agentic-engineering data.
- **ADD** a data ingestion scaffold (Wikipedia/Wikidata first, then Chronicling America, NYPL Digital Collections, OSM, NYC Open Data, MTA GTFS-RT, NOAA) writing into a single Postgres 16 instance with PostGIS and pgvector.
- **ADD** an agent tool surface (`search_places`, `spatial_query`, `historical_lookup`, `current_events`, `plan_walk`) that the LLM agent calls through OpenRouter's function-calling API.
- **DEFER** multimodal image retrieval, cross-session memory, traffic-camera computer vision, and the Google Photorealistic 3D Tiles integration to later changes.

## Capabilities

### New Capabilities

- `llm-router`: cost-aware dispatch across local (llama.cpp/Gemma-4-26B) and cloud (OpenRouter/GPT-5.4) inference, with request caching, telemetry, and a deterministic fallback ladder.
- `map-engine`: frontend abstraction for 3D map rendering with pluggable backends (MapLibre today, Google Photorealistic 3D Tiles later), exposing a minimal stable interface for the app layer.
- `data-ingest`: pipeline that ingests free/public-domain NYC datasets, normalizes them into PostGIS + pgvector, and publishes provenance metadata so every downstream claim can be cited back to its source.
- `agent-tools`: structured tool surface the agent can call to search places, perform spatial queries, retrieve historical documents, fetch live events, and plan constrained walking routes.

### Modified Capabilities

_None. This is the initial change in the project; `openspec/specs/` is empty._

## Impact

- **Filesystem**: creates `apps/api`, `apps/worker`, `apps/web`, `packages/shared`, `logs/`, `docker-compose.yml`, `Makefile`, `.env.example`, `.gitignore`, root `README.md`.
- **Runtime dependencies**: Python 3.12, FastAPI, SQLAlchemy, asyncpg, pgvector, httpx, redis, structlog, pydantic-settings; Node 20, Vite, React 18, TypeScript 5, Tailwind, MapLibre GL JS.
- **External services**: OpenRouter (requires `OPENROUTER_API_KEY`), local `llama-server` on Win11 reachable from WSL2 at `http://host.docker.internal:8080/v1`, Postgres 16 + PostGIS + pgvector in Docker, Redis in Docker.
- **VPS target**: single RackNerd VPS (2 vCPU, 2.5 GB RAM, 45 GB SSD). Raw ingestion archives never land on the VPS; only processed Postgres data (~5-15 GB target) and the API+web containers. Local dev happens on the same WSL2/Win11 box that hosts llama.cpp, so no tunneling is required for development.
- **Licensing**: all v1 data sources are public domain or free/open licenses. Code is original (not forked from WorldMonitor) and can be released under MIT or Apache 2.0 without downstream license friction.
