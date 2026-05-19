# Deployment guide

This guide is the operator's reference for running Palimpsest NYC end-to-end. It covers the published-image quick path, image pinning, the full environment-variable reference, day-to-day operations, building from source, the OSRM routing graph, and troubleshooting.

For the high-level product description and the four-command quick-start, see the [README](../README.md).

---

## 1. Quick deploy with published images

The `docker-compose.prod.yml` at the repo root pulls three images from GitHub Container Registry (`ghcr.io/nyavana/palimpsest-{api,web,postgres}`) plus the public `redis:7-alpine` image. No local build is required.

**Prerequisites**

- Docker with the `compose` v2 plugin
  - macOS / Windows: [Docker Desktop](https://www.docker.com/products/docker-desktop/)
  - Linux: [Docker Engine](https://docs.docker.com/engine/install/); confirm `docker compose version` works
- An OpenRouter API key from [openrouter.ai/keys](https://openrouter.ai/keys) (optional — leave blank for BYOK)
- ~2 GB of free disk for images and corpus

**Steps**

```bash
git clone https://github.com/nyavana/Palimpsest-NYC.git
cd Palimpsest-NYC

cp .env.prod.example .env       # or .env.example for a hands-off dev preview
chmod 600 .env                  # holds the DB password and any OpenRouter key
# edit .env: set OPENROUTER_API_KEY=sk-or-v1-... (or leave blank for BYOK),
# generate POSTGRES_PASSWORD (≥32 random chars; see .env.prod.example header)

docker login ghcr.io            # one-time, PAT with `read:packages`
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

Verify:

```bash
docker compose -f docker-compose.prod.yml ps
curl http://localhost:8000/health      # {"status":"ok","version":"0.1.0"}
```

Open <http://localhost:5173> in a browser. The first start downloads the `bge-small-en-v1.5` embedding weights (~130 MB) into a named volume; later starts skip this.

**Populate the corpus** (one-time, ~30 seconds):

```bash
docker compose -f docker-compose.prod.yml exec api python -m app.ingest.cli osm run
docker compose -f docker-compose.prod.yml exec api python -m app.ingest.cli wikipedia run
```

Both ingestors are idempotent and short-circuit when their `places.source_type` partition is already populated.

> **Routing note.** `docker-compose.prod.yml` now ships with `osrm-prepare` + `osrm` (pinned to `v5.25.0` — the upstream Docker Hub repo has not published a newer tag since 2021). On first up, `osrm-prepare` builds the routing graph from `infra/osrm/extract.osm.pbf` (~15–30 min on a 2 vCPU box) and the runtime `osrm` service comes up after. The graph is gitignored — run `make extract` to fetch it, see [§6](#6-osrm-routing-graph).

---

## 1.5 Hardening (production)

`docker-compose.prod.yml` already bakes in: no `:latest` images, no host-published debug ports, `read_only` rootfs with explicit tmpfs, `cap_drop:[ALL]` with minimal `cap_add`, `no-new-privileges`, per-service mem/pids limits, log rotation, and nginx running non-root on 8080. The host-side pieces (`.env` perms, UFW Cloudflare-IP allowlist, prod env defaults) are installed via `make` and a one-time installer script.

**Production checklist** (run on the host after the cutover):

```bash
chmod 600 .env                          # also done by `make harden-perms`
make harden                             # perms + firewall, idempotent
sudo bash infra/host/install.sh         # systemd timer for weekly CF refresh
make verify-harden                      # read-only spot checks
```

The host-side pieces installed by `infra/host/install.sh`:

| Path | Purpose |
|---|---|
| `/usr/local/sbin/refresh-cf-ufw` | Pulls `cloudflare.com/ips-v{4,6}`, rewrites the UFW allowlist for 80/443. Anti-lockout guard refuses to run if port 22 isn't ALLOW/LIMIT. |
| `/etc/systemd/system/refresh-cf-ufw.{service,timer}` | Weekly refresh, `OnCalendar=Sun 03:17 UTC`, `Persistent=true`. |

**APP_ENV gating.** When `APP_ENV=production` is set in `.env`, FastAPI suppresses `/docs`, `/redoc`, and `/openapi.json` so they're not reachable via the public `/api/*` proxy. Dev/staging/test keep Swagger.

**Dev → prod cutover.** The first switch from the dev compose to this prod compose rotates the postgres password and preserves both data volumes (`palimpsest-postgres-data` and `palimpsest-osrm-data` — both named identically in dev and prod compose) across the swap. Run it from the host repo root:

```bash
bash infra/host/cutover.sh              # dry-run, prints the procedure
bash infra/host/cutover.sh --execute    # actually do it
```

The script prompts before each destructive step. See [docs/runbooks/cutover.md](runbooks/cutover.md) for the full procedure, verification, and rollback paths.

**Backups.** Not configured in this PR. Postgres data is on the `palimpsest-postgres-data` named volume (~73 MB at time of writing); follow-up PR will add `restic` + a daily timer + an offsite repo. Until then, take a manual dump before any risky operation:

```bash
docker exec palimpsest-postgres pg_dumpall -U palimpsest > pre-change-$(date -u +%Y%m%dT%H%M%SZ).sql
chmod 600 pre-change-*.sql
```

---

## 2. Image pinning

The default `${PALIMPSEST_TAG}` in `docker-compose.prod.yml` is `0.1.0` (no floating `latest` in prod). To deploy a different release, pin a semver tag:

```bash
PALIMPSEST_TAG=v0.1.0 docker compose -f docker-compose.prod.yml pull
PALIMPSEST_TAG=v0.1.0 docker compose -f docker-compose.prod.yml up -d
```

Or persist it in `.env`:

```bash
echo "PALIMPSEST_TAG=v0.1.0" >> .env
```

Available tags published by `.github/workflows/docker-publish.yml`:

| Trigger | Tags |
|---|---|
| Push to `main` | `latest`, `sha-<short>` |
| Push of git tag `v*` | `v0.1.0`, `0.1.0`, `0.1`, `latest` |
| Pull request into `main` | `pr-<N>` and `sha-<short>` (verification only — does not move `latest`) |
| `workflow_dispatch` | Manual rebuild |

**Image inventory**

| Image | Purpose |
|---|---|
| `ghcr.io/nyavana/palimpsest-api` | FastAPI backend, agent loop, ingestion CLI. The worker reuses this image with a different command. |
| `ghcr.io/nyavana/palimpsest-web` | React SPA built into nginx; routes `/api/*` to the api service over the compose network. |
| `ghcr.io/nyavana/palimpsest-postgres` | PostGIS 16 + pgvector + pg_trgm, V1 migrations baked into `/docker-entrypoint-initdb.d`. |

The api image is ~760 MB uncompressed. `torch` is pulled from the CPU-only PyTorch index, so none of the CUDA payload ships. The OpenRouter key is read from your host's `.env` at container start and never enters the image; published images have been audited for `.env` and OpenRouter key signatures and are clean.

---

## 3. Environment variables

Copy `.env.example` to `.env` and adjust. The full reference:

### Application

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | Logging / behavior gate |
| `LOG_LEVEL` | `INFO` | structlog level |

### LLM — cloud tier (OpenRouter)

| Variable | Default | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | _(empty)_ | **If set:** every visitor uses your key. **If blank:** BYOK mode — each visitor supplies credentials via the in-app Settings panel and the `X-LLM-Credentials` header on `POST /agent/ask`. In BYOK mode `GET /config` returns `byok_required=true` and `POST /llm/chat` returns 503. |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenRouter API root |
| `OPENROUTER_STANDARD_MODEL` | `google/gemma-4-31b-it:free` | Standard-complexity routing |
| `OPENROUTER_COMPLEX_MODEL` | `google/gemma-4-31b-it:free` | Complex-complexity routing |

### LLM — local tier (OpenAI-compatible, V1 also points at OpenRouter)

| Variable | Default | Purpose |
|---|---|---|
| `LOCAL_LLM_BASE_URL` | `https://openrouter.ai/api/v1` | The router's `simple` tier. The two-tier split exists so V2 can repoint this at an on-device endpoint without code change. |
| `LOCAL_LLM_MODEL` | `google/gemma-4-31b-it:free` | Simple-complexity model |
| `LOCAL_LLM_API_KEY` | _(empty)_ | Key for the local tier (often the same as `OPENROUTER_API_KEY`) |

### LLM router cache + circuit breaker

| Variable | Default | Purpose |
|---|---|---|
| `LLM_CACHE_TTL_SIMPLE_S` | `86400` | Cache TTL for `simple` responses (24h) |
| `LLM_CACHE_TTL_STANDARD_S` | `21600` | Standard (6h) |
| `LLM_CACHE_TTL_COMPLEX_S` | `3600` | Complex (1h) |
| `LLM_CB_FAIL_THRESHOLD` | `3` | Failures per window before breaker opens |
| `LLM_CB_WINDOW_S` | `60` | Failure-count window |
| `LLM_CB_COOLDOWN_S` | `30` | Open-state cooldown |

### Embeddings

| Variable | Default | Notes |
|---|---|---|
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | **Locked.** Changing requires a schema migration that drops and recreates the `vector(384)` column. |
| `EMBEDDING_DIM` | `384` | **Locked.** Must match `EMBEDDING_DIM` constant in `app/db/models.py`. |
| `EMBEDDING_BATCH_SIZE` | `32` | Ingest-time batch size |

### Retrieval

| Variable | Default | Notes |
|---|---|---|
| `RETRIEVAL_MODE` | `dense` | One of `dense`, `hybrid`, `hybrid_reranked`. `hybrid` fuses pgvector embedding + `pg_trgm` name similarity via RRF (k=60). `hybrid_reranked` adds a cross-encoder over the top-N fused candidates. |
| `RERANKER_MODEL` | `BAAI/bge-reranker-base` | Cross-encoder model |
| `RERANKER_ENABLED` | `false` | Auto-true when `RETRIEVAL_MODE=hybrid_reranked` |

### Database

| Variable | Default |
|---|---|
| `POSTGRES_USER` | `palimpsest` |
| `POSTGRES_PASSWORD` | `devpassword` (**change for production** — use ≥32 random chars; `make harden-cutover` rotates it as part of the dev→prod migration) |
| `POSTGRES_DB` | `palimpsest` |
| `POSTGRES_HOST` | `postgres` |
| `POSTGRES_PORT` | `5432` |

### Redis & API

| Variable | Default |
|---|---|
| `REDIS_URL` | `redis://redis:6379/0` |
| `API_HOST` | `0.0.0.0` |
| `API_PORT` | `8000` |
| `API_CORS_ORIGINS` | `http://localhost:5173,http://localhost:8080` (comma-separated; **add your production origin**) |
| `API_WORKERS` | `2` |

### Agent

| Variable | Default | Notes |
|---|---|---|
| `AGENT_MAX_TURNS` | `6` | Hard cap — hitting it raises `AgentLoopError`. |
| `META_SESSION_LOG_DIR` | `/app/logs/claude-sessions` | Per-session telemetry (jsonl) |

### Frontend (build-time)

| Variable | Default | Notes |
|---|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8000` | API root the SPA targets. Set this for production deployments. |
| `VITE_MAP_ENGINE` | `maplibre` | Set to `google` to opt into the Photorealistic 3D Tiles engine (requires `VITE_GOOGLE_MAP_TILES_API_KEY`). |
| `VITE_GOOGLE_MAP_TILES_API_KEY` | _(empty)_ | Optional Google 3D Tiles key |

### Compose-level

| Variable | Default | Notes |
|---|---|---|
| `PALIMPSEST_TAG` | `latest` | Pin published images to a release (see [§2](#2-image-pinning)). |

---

## 4. Day-to-day operations

All commands run from the repo root with the same `-f docker-compose.prod.yml` flag.

**Tail logs**

```bash
docker compose -f docker-compose.prod.yml logs -f --tail 100
# single service:
docker compose -f docker-compose.prod.yml logs -f api
```

**Stop without losing data**

```bash
docker compose -f docker-compose.prod.yml down
```

The corpus, embedder cache, and Redis state live in named volumes (`palimpsest-postgres-data`, `palimpsest-hf-cache`, `palimpsest-redis-data`). Bring everything back with `up -d`.

**Update to a newer release**

```bash
git pull
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

`up -d` recreates only the containers whose images changed.

**Open a shell inside a container**

```bash
docker compose -f docker-compose.prod.yml exec api bash
docker compose -f docker-compose.prod.yml exec postgres psql -U palimpsest -d palimpsest
```

**Inspect the corpus**

```bash
docker compose -f docker-compose.prod.yml exec postgres \
  psql -U palimpsest -d palimpsest \
  -c "SELECT source_type, count(*) FROM places GROUP BY source_type;"
```

**Wipe everything (drops the corpus too)**

```bash
docker compose -f docker-compose.prod.yml down -v
```

You will need to re-run the two ingestion CLIs after this.

---

## 5. Build from source

For development against the project — modifying the agent loop, schema, or web bundle — use the dev compose at the repo root. Requires Docker plus `uv` (or Python 3.12 + `venv`) and Node 20+ on the host.

```bash
cp .env.example .env
make setup       # creates .venv in apps/api and apps/worker, npm install in apps/web
make up          # build all images locally and start
make logs        # tail container logs
curl http://localhost:8000/health
open http://localhost:5173
```

Other Make targets:

| Target | Action |
|---|---|
| `make dev` | Up attached (live logs in foreground) |
| `make down` | Stop containers, preserve volumes |
| `make nuke` | Stop and drop volumes — required after schema changes |
| `make ps` | Service status |
| `make api-shell` | `bash` inside the api container |
| `make db-shell` | `psql` inside postgres |
| `make fmt` | `ruff format` + `prettier` |
| `make lint` | `ruff check` + `eslint` |
| `make test` | `pytest` in `apps/api` |

**Schema is migrations-first.** The schema is owned by `apps/api/app/db/migrations/*.sql`, applied by the postgres entrypoint on first volume init in lexicographic order. `app/db/models.py` is a read-only ORM mirror — never call `Base.metadata.create_all` in app code paths. Adding or changing a migration requires `make nuke && make up` to drop the postgres volume and re-apply the SQL.

---

## 6. OSRM routing graph

`plan_walk` calls an in-network OSRM service for street-following walking routes. Two compose services back this, both present in the dev `docker-compose.yml` but **not in `docker-compose.prod.yml`**:

- **`osrm-prepare`** — one-shot. On first start it runs `osrm-extract -p foot.lua && osrm-partition && osrm-customize` against `infra/osrm/extract.osm.pbf` and writes the prepared graph to a named volume. Idempotent: skips on subsequent boots once `extract.osrm.cnbg` is present.
- **`osrm`** — runtime, serving `http://osrm:5000` on the compose network using `osrm-routed --algorithm mld`. Pinned to `osrm/osrm-backend:v5.25.0`.

The OSM extract `infra/osrm/extract.osm.pbf` (~100 MB, currently the Manhattan-wide bbox) **is committed to the repo**, so `osrm-prepare` runs end-to-end without any external download on `make up`.

**Widening the bbox.** Replace `infra/osrm/extract.osm.pbf` with a new extract (BBBike URL or Geofabrik clip with `osmium`), then `make nuke && make up`. See [`infra/osrm/README.md`](../infra/osrm/README.md) for the refresh procedure.

**Fallback.** If `osrm` is unreachable at request time, `plan_walk` falls back to a haversine straight-line route with `routing_backend="haversine_fallback"` rather than failing the request. The frontend renders this as a dashed muted path.

---

## 7. Troubleshooting

**First start is slow.** The api container downloads `bge-small-en-v1.5` (~130 MB) into the `palimpsest-hf-cache` volume on the first boot. Watch progress with `docker compose -f docker-compose.prod.yml logs -f api`. Later starts are instant.

**`/agent/ask` returns 503 immediately.** You're in BYOK mode (`OPENROUTER_API_KEY` is blank) and the request did not carry an `X-LLM-Credentials` header. Either set the operator key, or use the in-app Settings panel to configure credentials, or include the header on `curl` calls (see the README's API section).

**OpenRouter quota exhausted.** Free-tier models throttle. Either upgrade the key on [openrouter.ai/keys](https://openrouter.ai/keys), or flip `OPENROUTER_STANDARD_MODEL` / `OPENROUTER_COMPLEX_MODEL` to a paid model.

**Empty corpus after `up -d`.** The published-image compose (`docker-compose.prod.yml`) does **not** include the `init-ingest` one-shot service that the dev compose runs. Populate manually:

```bash
docker compose -f docker-compose.prod.yml exec api python -m app.ingest.cli osm run
docker compose -f docker-compose.prod.yml exec api python -m app.ingest.cli wikipedia run
```

**Schema looks wrong / migration was added.** Drop the postgres volume:

```bash
docker compose -f docker-compose.prod.yml down -v
docker compose -f docker-compose.prod.yml up -d
```

Then re-run the ingestion CLIs above.

**Routes render as straight dashed lines.** The `osrm` service isn't reachable — either you're on `docker-compose.prod.yml` (which omits it) or `osrm-prepare` hasn't finished. Check the `routing_backend` field on the `walk` SSE frame.

**CORS error in the browser.** Add the page's origin to `API_CORS_ORIGINS` (comma-separated) and restart the api container.

**Port already in use.** Override the host port in the compose file or stop the conflicting service. Defaults: `5173` (web), `8000` (api), `5432` (postgres), `6379` (redis).
