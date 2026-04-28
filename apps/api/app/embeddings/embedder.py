"""Embedder — thin wrapper around a sentence-transformers model.

Per `embeddings/spec.md`:
- Single entry point: `Embedder.encode(texts) -> list[list[float]]`
- L2-normalized output (cosine == dot for `bge-small-en-v1.5`)
- Approximately-deterministic (≤1e-5 max abs diff intra-process)
- Batched at `EMBEDDING_BATCH_SIZE`
- Vector dim verified against `EMBEDDING_DIM` at construction

The model is loaded once and shared across requests via `app.state.embedder`.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol

from app.config import EmbeddingsSettings
from app.embeddings.errors import EmbeddingDimMismatchError


class _ModelLike(Protocol):
    """The narrow subset of `SentenceTransformer` we consume.

    Defined as a Protocol so tests can inject a fake without dragging the
    real dependency in."""

    def get_sentence_embedding_dimension(self) -> int: ...

    def encode(  # noqa: PLR0913 - mirrors upstream signature
        self,
        sentences: list[str],
        *,
        batch_size: int = 32,
        normalize_embeddings: bool = True,
        convert_to_numpy: bool = True,
        show_progress_bar: bool = False,
    ) -> Any: ...


class Embedder:
    """Wraps a sentence-transformers model with a stable Palimpsest API."""

    def __init__(
        self,
        *,
        model: _ModelLike,
        dim: int,
        batch_size: int = 32,
    ) -> None:
        actual = model.get_sentence_embedding_dimension()
        if actual != dim:
            raise EmbeddingDimMismatchError(
                f"EMBEDDING_DIM={dim} does not match loaded model dim {actual}; "
                f"either update EMBEDDING_DIM and the migration column type "
                f"to vector({actual}), or pick a model whose dim is {dim}."
            )
        self._model = model
        self.dim = dim
        self.batch_size = batch_size

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        arr = self._model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        # arr is np.ndarray of shape (N, dim). Convert to nested list of plain
        # Python floats so asyncpg/pgvector codecs don't trip on numpy scalars.
        return [[float(x) for x in row] for row in arr]


def _default_factory(model_name: str) -> _ModelLike:
    # Deferred import so unit tests can avoid the heavy torch/transformers
    # tree on every collection.
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)  # type: ignore[return-value]


def build_embedder(
    settings: EmbeddingsSettings,
    *,
    model_factory: Callable[[str], _ModelLike] = _default_factory,
) -> Embedder:
    return Embedder(
        model=model_factory(settings.model),
        dim=settings.dim,
        batch_size=settings.batch_size,
    )
