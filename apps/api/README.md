# Palimpsest API

FastAPI backend for Palimpsest NYC. Hosts the LLM router, the agent tool loop, ingestion entry points, and the meta-instrumentation endpoints.

## Local setup (venv)

```bash
# from repo root
make setup-api
source apps/api/.venv/bin/activate
uvicorn app.main:app --reload
```

## Layout

```
app/
├── main.py             # FastAPI factory + lifespan
├── config.py           # pydantic-settings
├── logging.py          # structlog setup
├── llm/                # LLM router capability
│   ├── models.py
│   ├── router.py
│   ├── adapters.py
│   ├── cache.py
│   └── telemetry.py
├── agent/              # agent loop + tools
│   ├── loop.py
│   └── tools/
├── ingest/             # data ingestion pipelines
├── meta/               # meta-instrumentation harness
├── db/                 # SQLAlchemy models + migrations
└── routes/             # HTTP routers
```

## Environment

All configuration loaded via `pydantic-settings` from environment variables. See the root `.env.example` for the canonical list.

Key vars the router reads:

| Var | Purpose |
|---|---|
| `OPENROUTER_API_KEY` | Required. OpenRouter key (used by both tiers in V1). |
| `OPENROUTER_BASE_URL` | Cloud-tier endpoint. Default `https://openrouter.ai/api/v1`. |
| `OPENROUTER_STANDARD_MODEL` / `OPENROUTER_COMPLEX_MODEL` | Models for `standard` and `complex` complexities. |
| `LOCAL_LLM_BASE_URL` | Local-tier endpoint. V1 default points at OpenRouter; v2 may point at an on-device server. |
| `LOCAL_LLM_MODEL` | Model slug for the `simple` complexity tier. |
| `LOCAL_LLM_API_KEY` | Bearer token for the local-tier endpoint. |
| `EMBEDDING_MODEL` / `EMBEDDING_DIM` / `EMBEDDING_BATCH_SIZE` | sentence-transformers embedding singleton (V1: `BAAI/bge-small-en-v1.5`, 384-dim). |
