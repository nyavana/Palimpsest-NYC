"""In-process sentence embeddings for the Palimpsest corpus.

V1 model: `BAAI/bge-small-en-v1.5` (384-dim, locked in
`swap-llm-tiers-and-lock-mvp-decisions`). Loaded once at api startup and
attached to `app.state.embedder`. CPU-only; weights live in the mounted
HF cache (`/cache/huggingface`).
"""

from app.embeddings.embedder import Embedder, build_embedder

__all__ = ["Embedder", "build_embedder"]
