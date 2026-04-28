# §10 — Database schema + embeddings (2026-04-28)

OpenSpec change: `initial-palimpsest-scaffold` §10.1-§10.5 (locked under
`swap-llm-tiers-and-lock-mvp-decisions`).

## What landed

| Path | Purpose |
|---|---|
| `apps/api/app/db/migrations/0001_init.sql` | Enables `postgis`, `vector`, `pg_trgm` extensions. |
| `apps/api/app/db/migrations/0002_places.sql` | Creates `source_type_enum` (`wikipedia | wikidata | osm`), `places`, `documents`. Embedding columns are `vector(384)`. Indexes: GIST on geom, GIN trgm on names/bodies, ivfflat on embeddings, btree on source_type. |
| `apps/api/app/db/migrations/README.md` | "How to add a migration" — forward-only, dev-time `make nuke` workflow. |
| `apps/api/app/db/__init__.py` | (empty marker for the module). |
| `apps/api/app/db/engine.py` | `build_engine` + `build_session_factory`. asyncpg dialect, pool_pre_ping, pool_size=10, expire_on_commit=False. |
| `apps/api/app/db/models.py` | `Base`, `SourceType` enum, `Place` and `Document` ORM classes. `EMBEDDING_DIM=384` constant matches the migration. Spec rule enforced: no `metadata.create_all()` anywhere in app code. |
| `apps/api/app/embeddings/__init__.py` | Public exports (`Embedder`, `build_embedder`). |
| `apps/api/app/embeddings/embedder.py` | Thin `Embedder` over `SentenceTransformer`, batched, L2-normalized, dim-checked at construction. |
| `apps/api/app/embeddings/errors.py` | `EmbeddingError` / `EmbeddingDimMismatchError`. |
| `apps/api/app/main.py` | Lifespan now wires the engine, session factory, and embedder singleton onto `app.state`. |
| `apps/api/Dockerfile` | Pre-creates `/cache/huggingface` with `app:app` ownership so the named volume inherits non-root permissions. |
| `apps/api/pyproject.toml` | Added `sentence-transformers>=3.0.0`, `huggingface_hub>=0.24.0`, `geoalchemy2>=0.15.0`. Removed `alembic` (V1 uses init-time SQL only). |
| `docker-compose.yml` | postgres `volumes`: now mounts `./apps/api/app/db/migrations` → `/docker-entrypoint-initdb.d:ro`. api `volumes`: adds `hf-cache:/cache/huggingface`; api `environment`: `HF_HOME=/cache/huggingface`. New named volume `palimpsest-hf-cache`. |
| `docker/postgres/initdb/001-extensions.sql` | **Removed** — replaced by `apps/api/app/db/migrations/0001_init.sql` (single source of truth per spec). |

## Tests added

- `tests/test_db_engine.py` (3) — engine/session-factory wiring, DSN built from settings.
- `tests/test_db_models.py` (6) — column shapes, unique/nullable contracts, embedding dim==384, source_type enum locked, no `metadata.create_all` call site in app code.
- `tests/test_embeddings.py` (8 + 1 skipped) — fake-model-driven contract tests: dim==384, plain-float output, L2-normalized, deterministic intra-process, batched ≈ unbatched, empty input, dim mismatch error, builder wiring. The 1 skipped test downloads the real `BAAI/bge-small-en-v1.5` weights and runs only when `PALIMPSEST_INTEGRATION=1`.

`make test` is now **31 passed, 1 skipped**.

## Docker validation

Brought up postgres + redis + api against a fresh volume:

```
$ docker compose up -d postgres redis api
$ docker logs palimpsest-postgres | grep -E "running|CREATE"
running /docker-entrypoint-initdb.d/0001_init.sql
CREATE EXTENSION (postgis, vector, pg_trgm)
running /docker-entrypoint-initdb.d/0002_places.sql
CREATE TABLE / CREATE INDEX (places, documents, ivfflat × 2, gist, gin_trgm × 2, btree × 2, triggers × 2)
PostgreSQL init process complete; ready for start up.
```

Schema confirmed via `psql`:

```
\dt        →  documents | places | spatial_ref_sys
SELECT enum_range(NULL::source_type_enum);
           →  {wikipedia,wikidata,osm}
\d+ places →  embedding | vector(384)
              indexes: ivfflat (embedding vector_cosine_ops, lists=100),
                       gist (geom), gin (name gin_trgm_ops),
                       btree (source_type), unique (doc_id)
```

API startup:

```
embedder.loading model=BAAI/bge-small-en-v1.5
Loading SentenceTransformer model from BAAI/bge-small-en-v1.5.
Loading weights: 100%|██████████| 199/199
embedder.ready dim=384
Application startup complete.
```

`/health` returns 200; `/llm/chat` returns real billed responses through the kimi-k2.6 wiring.

## Pre-existing issues flagged (out of scope)

- `apps/web/Dockerfile` references `apps/web/` from a context that's already `apps/web/`. `docker compose up web` fails. Not blocking the api/db/embedder validation. To fix: change `COPY apps/web/ ./` to `COPY . ./` (and similar) in the web Dockerfile.
- `sentence-transformers` 5.x emits a `FutureWarning` for `get_sentence_embedding_dimension` (renamed to `get_embedding_dimension`). The Embedder still works on every released sentence-transformers version. We can swap the call when the next deprecation cycle closes; for now the warning is benign.

## What unblocks next

- **§9** (agent surface): `search_places` tool can now query `places.embedding` for semantic top-k, then geom for distance, with `place_id` as the agent-visible key.
- **§11** (ingestion): Wikipedia + OSM ingestors can write directly into `places`/`documents`, populate `embedding` via `app.state.embedder`, and emit citation-shaped provenance with no field renaming.
- **§12** (walk planner): server-side PostGIS routing pass over `place_ids` returned in `citations[]`.
