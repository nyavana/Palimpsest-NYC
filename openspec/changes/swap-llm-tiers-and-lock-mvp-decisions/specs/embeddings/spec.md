## ADDED Requirements

### Requirement: In-process embedding model

The api SHALL provide a single embedding entry point `Embedder.encode(texts: list[str]) -> list[list[float]]` backed by a `sentence-transformers` model loaded once at api startup and stored on `app.state.embedder`. The model SHALL be `BAAI/bge-small-en-v1.5` by default and SHALL be configurable via the `EMBEDDING_MODEL` env var. No network call to a third-party embedding API is permitted in the default configuration; embeddings MUST be computable end-to-end inside the api container with no external HTTP dependency.

#### Scenario: Embedder is initialized at startup
- **WHEN** the api lifespan completes startup
- **THEN** `app.state.embedder` is a callable `Embedder` instance whose underlying model name equals `EMBEDDING_MODEL`

#### Scenario: Encoding short text returns a 384-dim vector
- **WHEN** `Embedder.encode(["The Cathedral of St. John the Divine"])` is called with the default model
- **THEN** the returned list contains exactly one float vector of length 384

#### Scenario: Default model SHOULD be offline-runnable after first cache fill
- **WHEN** the api container is started with no outbound network access after the first cache fill
- **THEN** `Embedder.encode([...])` should still succeed because model weights are read from the mounted Hugging Face cache; this is a SHOULD (a property of HF caching) and not a hard contract the test harness asserts on every run

### Requirement: Deterministic vector dimension

Embedding vector dimension SHALL be exposed as `EMBEDDING_DIM` (default `384`) and SHALL match the dimension of the column types declared in the database migrations. The migration that introduces `places.embedding` and `documents.embedding` SHALL declare them as `vector(EMBEDDING_DIM)`. If `EMBEDDING_MODEL` is changed, `EMBEDDING_DIM` MUST be updated in the same configuration change and a new migration MUST drop and recreate the column at the new dimension.

#### Scenario: pgvector column type matches embedder output
- **WHEN** the api inserts an embedding into `places.embedding`
- **THEN** the vector length matches the column's declared dimension and Postgres accepts the insert without a cast error

#### Scenario: Mismatched EMBEDDING_DIM is rejected at startup
- **WHEN** the api starts with `EMBEDDING_DIM` set to a value that does not match the loaded model's `get_sentence_embedding_dimension()`
- **THEN** startup fails with a clear error naming both values

### Requirement: Batched and approximately-deterministic encoding

`Embedder.encode` SHALL batch inputs at `EMBEDDING_BATCH_SIZE` (default `32`) and SHALL produce approximately-deterministic output for identical inputs. The embedder MUST set the model into evaluation mode and disable gradient tracking. Outputs SHALL be L2-normalized so cosine similarity equals dot product (matches `bge-small-en-v1.5` recommendation).

"Approximately-deterministic" means **max absolute element-wise difference ≤ 1e-5** between two encodings of identical input within the same process. We do NOT contract for byte-exact reproduction across PyTorch versions, CPU SIMD widths, or process boundaries — sentence-transformers does not guarantee that, and the V1 retrieval use case (cosine similarity for top-k) is robust to noise at this scale.

#### Scenario: Same text encoded twice returns approximately-equal vectors
- **WHEN** `Embedder.encode(["hello"])` is called twice in the same process
- **THEN** the two returned vectors have max absolute element-wise difference ≤ 1e-5

#### Scenario: Batched encoding equals unbatched within tolerance
- **WHEN** `Embedder.encode(["a", "b", "c"])` is called once and `Embedder.encode(["a"])`, `Embedder.encode(["b"])`, `Embedder.encode(["c"])` are called separately
- **THEN** the corresponding output vectors are equal with max absolute element-wise difference ≤ 1e-5

#### Scenario: Vectors are L2-normalized
- **WHEN** `Embedder.encode(["any text"])` is called
- **THEN** the L2 norm of the returned vector is `1.0 ± 1e-5`

### Requirement: Model cache mount

The api container SHALL read and write Hugging Face model weights to a mounted cache directory at `/cache/huggingface` (controlled by env `HF_HOME=/cache/huggingface`). The first run with an empty cache MAY download model weights; subsequent runs SHOULD reuse the cache.

#### Scenario: Second startup reuses cached weights
- **WHEN** the api container is restarted with the same cache volume mounted
- **THEN** model loading completes by reading the mounted cache; an outbound HTTP request to `huggingface.co` is permitted only if the cache content has been invalidated by a model upgrade
