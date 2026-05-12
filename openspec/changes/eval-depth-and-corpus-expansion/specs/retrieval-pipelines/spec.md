## ADDED Requirements

### Requirement: Pluggable retrieval pipeline selected by `RETRIEVAL_MODE`

The API SHALL support three retrieval pipelines selected at process start by the `RETRIEVAL_MODE` environment variable: `dense` (cosine ANN over `places.embedding`), `hybrid` (dense merged with a sparse `pg_trgm` retriever via Reciprocal Rank Fusion, k=60), and `hybrid_reranked` (hybrid output passed through a `BAAI/bge-reranker-base` cross-encoder applied to the top-N candidates). A factory function `app.retrieval.factory.build_retriever(*, mode: str = "dense", reranker=None)` SHALL return the right retriever class for the requested mode and SHALL raise a `ValueError` if the mode is unknown or if `hybrid_reranked` is requested without a reranker singleton. The factory takes ONLY `mode` and `reranker` as keyword arguments; `session` and `embedder` are passed through to the retriever's `.search(...)` call at request time, not bound at construction.

#### Scenario: Process starts with `RETRIEVAL_MODE=dense`
- **WHEN** the API container starts with `RETRIEVAL_MODE=dense` (the default)
- **THEN** the lifespan does NOT load the reranker singleton and the `search_places` tool uses `DenseRetriever`

#### Scenario: Process starts with `RETRIEVAL_MODE=hybrid`
- **WHEN** the API container starts with `RETRIEVAL_MODE=hybrid`
- **THEN** the lifespan does NOT load the reranker singleton, the `search_places` tool uses `HybridRetriever`, and dense + sparse queries are executed in parallel and merged via RRF

#### Scenario: Process starts with `RETRIEVAL_MODE=hybrid_reranked`
- **WHEN** the API container starts with `RETRIEVAL_MODE=hybrid_reranked`
- **THEN** the lifespan loads the `BAAI/bge-reranker-base` singleton from `hf-cache`, the `search_places` tool uses `RerankedRetriever`, and the top-N hybrid candidates are reordered by the cross-encoder

#### Scenario: Unknown retrieval mode at startup
- **WHEN** the API container starts with `RETRIEVAL_MODE=banana`
- **THEN** `build_retriever(mode="banana")` raises `ValueError("unknown RETRIEVAL_MODE: 'banana'")` and the container fails fast at lifespan time, not at first request

#### Scenario: `hybrid_reranked` requested with no reranker singleton
- **WHEN** code calls `build_retriever(mode="hybrid_reranked", reranker=None)`
- **THEN** the factory raises `ValueError("hybrid_reranked mode requires a reranker singleton")` indicating the reranker singleton must be loaded for this mode

### Requirement: All retrievers share a uniform `.search(...)` signature returning `SearchPlaceHit`

Every retriever (`DenseRetriever`, `SparseRetriever`, `HybridRetriever`, `RerankedRetriever`) SHALL expose an `async def search(self, *, session, embedder, query: str, near: tuple[float, float] | None, radius_m: int | None, limit: int) -> list[SearchPlaceHit]` method. `SearchPlaceHit` is the existing dataclass declared in `app.agent.tools.search_places` and SHALL NOT be redefined per-retriever. This signature is the contract between the factory's product and the `search_places` tool / `/internal/retrieve` endpoint.

#### Scenario: Refactor introduces a new field on `SearchPlaceHit` for one retriever only
- **WHEN** a refactor adds a `reranker_score` field returned only by `RerankedRetriever`
- **THEN** `test_retrieval_factory.py` fails with a shape-mismatch assertion before the change can land

#### Scenario: Same query against all three modes returns the same shape
- **WHEN** an integration test issues the same `search_places` call against the three modes
- **THEN** every result list element has the same set of `SearchPlaceHit` fields, even if values (rankings, scores) differ

### Requirement: `search_places` tool-result shape is identical across all three retrieval modes

The `search_places` tool MUST return the same JSON-shaped tool-result regardless of `RETRIEVAL_MODE`. The result schema (field names, field types, nullability, presence of `doc_id`, `source_url`, `source_type`, `name`, `lat`, `lon`, score-or-rank fields) SHALL be byte-equivalent shape across `dense`, `hybrid`, and `hybrid_reranked`. This invariant exists so the agent loop, the citation verifier, the locked V1 contract, and downstream tests do not branch on retrieval mode.

#### Scenario: Shape-contract assertion catches a tool-result drift
- **WHEN** the extended `test_agent_search_places.py` runs `search_places` with each `RETRIEVAL_MODE`
- **THEN** the JSON keys at every depth of the tool-result are identical across all three modes

### Requirement: Dense retriever extracted to `app/retrieval/dense.py`

The current pgvector retrieval logic (currently inline in `app/agent/tools/search_places.py` as `PostgresRetriever`) SHALL be extracted into a `DenseRetriever` class in `app/retrieval/dense.py` BEFORE any other retrieval mode is added. The extracted class SHALL preserve the existing SQL, the same score formula `score = max(0.0, min(1.0, 1.0 - distance / 2.0))`, and the same `SearchPlaceHit` return shape. The legacy `PostgresRetriever` name SHALL remain available as a thin subclass-alias of `DenseRetriever` so existing tests and imports continue to work.

#### Scenario: Extraction preserves tool-result shape
- **WHEN** the dense extraction is committed but no other retrieval mode exists
- **THEN** `pytest apps/api/tests/test_agent_search_places.py -v` passes without any test edits

#### Scenario: `PostgresRetriever` import path still works
- **WHEN** existing code imports `PostgresRetriever` from `app.agent.tools.search_places`
- **THEN** the import succeeds and the resolved class is a subclass of `DenseRetriever`

### Requirement: Sparse retriever uses `pg_trgm` over `places.name`

`SparseRetriever` (`app/retrieval/sparse.py`) SHALL implement a `pg_trgm` similarity query against `places.name`, returning the top-K matches as `SearchPlaceHit` objects in the same shape that `DenseRetriever` returns. A `gin_trgm_ops` index on `places.name` SHALL be present (these indexes already live in `0002_places.sql` from V1; no new migration is required for this requirement).

#### Scenario: Trigram similarity returns sensible hits
- **WHEN** the corpus contains a place named "Cathedral of Saint John the Divine" and the query is "saint john divine"
- **THEN** that place appears in the top-3 sparse hits

#### Scenario: Sparse retriever returns the same hit shape as dense
- **WHEN** dense and sparse retrieve the same K hits from the same corpus
- **THEN** the union of `SearchPlaceHit` fields on each row is identical

### Requirement: Hybrid retrieval merges dense and sparse via Reciprocal Rank Fusion (k=60)

`HybridRetriever` (`app/retrieval/hybrid.py`) SHALL run `DenseRetriever` and `SparseRetriever` concurrently and merge their ranked lists using Reciprocal Rank Fusion with constant `k=60` per Cormack et al. 2009. The RRF score for document `d` SHALL be `Σ 1 / (k + rank_i(d))` summed across the ranked lists that contain `d`. The fusion logic SHALL live in `app/retrieval/fusion.py` as a pure function with no I/O.

#### Scenario: Document present in both lists ranks higher than document present in one
- **WHEN** doc A is rank 5 in both dense and sparse, doc B is rank 1 in dense only
- **THEN** doc A scores `2 / (60 + 5) ≈ 0.0308`, doc B scores `1 / (60 + 1) ≈ 0.0164`; doc A ranks higher in the fused list

#### Scenario: Empty sparse list does not break hybrid
- **WHEN** the sparse retriever returns no hits for the query
- **THEN** `HybridRetriever` returns the dense list ordering unchanged

#### Scenario: Hybrid retrieval result shape matches dense
- **WHEN** `HybridRetriever.search(...)` returns a list of hits
- **THEN** each hit is a `SearchPlaceHit` with the same fields as the dense path

### Requirement: Reranker is a singleton conditionally loaded in lifespan

The `BAAI/bge-reranker-base` cross-encoder SHALL be loaded as a singleton on `app.state.reranker` in `app/main.py` lifespan ONLY when `settings.retrieval_mode == "hybrid_reranked"` OR `settings.reranker_enabled` is `True`. The singleton SHALL load from `hf-cache` mounted at `/cache/huggingface` so subsequent `make up` invocations do not re-download weights. The `Reranker` class SHALL expose `def rerank(query: str, candidates: list[RetrievalHit], top_k: int) -> list[RetrievalHit]`.

#### Scenario: Dense mode does not load the reranker
- **WHEN** the container starts with `RETRIEVAL_MODE=dense`
- **THEN** `app.state.reranker` is `None` and the container's startup latency is unchanged from V1

#### Scenario: `hybrid_reranked` mode loads the reranker from the cache volume
- **WHEN** the container starts with `RETRIEVAL_MODE=hybrid_reranked` and `hf-cache` contains `BAAI/bge-reranker-base`
- **THEN** the model is loaded from the cache without a network call to Hugging Face

### Requirement: `/internal/retrieve` exposes one-shot retrieval to the naive-RAG baseline

`POST /internal/retrieve` SHALL accept `{"query": str, "top_k": int (default 8), "bbox": optional}` and return a list of retrieval hits using the SAME retriever instance as `search_places` (`app.state.retriever_for_internal`). It SHALL NOT run the agent loop, SHALL NOT verify citations, and SHALL NOT stream. The endpoint SHALL be mounted under `/internal` to signal "service-to-service, not a public API."

#### Scenario: Naive-RAG baseline calls `/internal/retrieve`
- **WHEN** the naive-RAG baseline POSTs `{"query": "cathedral", "top_k": 8}` to `/internal/retrieve`
- **THEN** the endpoint returns 8 hits using the process's active retrieval mode

#### Scenario: `/internal/retrieve` and `search_places` share one retrieval implementation
- **WHEN** the same query is sent to `/internal/retrieve` and to `search_places` via the agent loop
- **THEN** the retrieval results (before any agent re-ranking) are identical

### Requirement: `/internal/documents/by_ids` enriches grader-side body excerpts

`POST /internal/documents/by_ids` SHALL accept `{"doc_ids": list[str]}` (length 1–64) and return `{"documents": [{"doc_id": str, "body_excerpt": str}, ...]}` preserving input order. `body_excerpt` is the first `BODY_EXCERPT_MAX_CHARS` of the joined `documents.body` row for that `doc_id`. Unknown doc_ids SHALL be returned with `body_excerpt: ""` (empty string) rather than being skipped silently. The endpoint SHALL NOT return `source_url` or `source_type` — those fields are already carried in the SSE `tool_result` frames the grader is enriching.

#### Scenario: Unknown doc_id is returned with an empty body excerpt
- **WHEN** the grader requests an unknown id alongside known ids
- **THEN** the response includes the unknown id at its original position with `body_excerpt: ""` and the known ids carry their excerpts

#### Scenario: Output preserves input order
- **WHEN** the grader requests `["c", "a", "b"]`
- **THEN** the response's `documents` array has `doc_id` values in that exact order

### Requirement: `RETRIEVAL_MODE` is passed through `docker-compose.yml` from the shell

`docker-compose.yml` SHALL declare `RETRIEVAL_MODE: ${RETRIEVAL_MODE:-dense}` and `RERANKER_ENABLED: ${RERANKER_ENABLED:-false}` in the `api` service's `environment:` block. The default values SHALL match the V1 status quo so `make up` with no shell vars is unchanged.

#### Scenario: Mode env var reaches the container
- **WHEN** the host runs `RETRIEVAL_MODE=hybrid docker compose up -d --force-recreate api`
- **THEN** `docker compose exec api env | grep RETRIEVAL_MODE` prints `RETRIEVAL_MODE=hybrid`

#### Scenario: Default mode is `dense`
- **WHEN** the host runs `docker compose up -d` with no `RETRIEVAL_MODE` in the shell
- **THEN** the api container reports `RETRIEVAL_MODE=dense`

### Requirement: Configuration surface for retrieval modes

`apps/api/app/config.py` SHALL expose pydantic settings entries `retrieval_mode: str` (default `"dense"`, alias `RETRIEVAL_MODE`), `reranker_model: str` (default `"BAAI/bge-reranker-base"`, alias `RERANKER_MODEL`), and `reranker_enabled: bool` (default `False`, alias `RERANKER_ENABLED`). The set of valid `retrieval_mode` values is enforced by `build_retriever()` raising `ValueError` rather than by pydantic-side `Literal` typing — this keeps the config surface forward-compatible with new modes without a config-class edit, while the factory remains the single point of truth for which modes are real. `.env.example` SHALL document each of these alongside the existing variables.

#### Scenario: Invalid `RETRIEVAL_MODE` is caught at lifespan time
- **WHEN** the container starts with `RETRIEVAL_MODE=banana`
- **THEN** pydantic accepts the string but the lifespan's `build_retriever(mode=settings.retrieval_mode)` call raises `ValueError("unknown RETRIEVAL_MODE: 'banana'")` and the container fails fast before serving requests
