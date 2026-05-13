"""Cross-encoder reranker singleton.

Loaded once at startup (when RERANKER_ENABLED or RETRIEVAL_MODE=hybrid_reranked).
Default model: BAAI/bge-reranker-base. CPU-only; ~30ms per pair. Weights are
expected to live in the mounted HF cache at `/cache/huggingface` (same volume
as the `Embedder` singleton), preloaded by the `init-ingest` compose service.

Tests inject a fake `_ModelLike` via the `model=` kwarg so we don't pay the
torch import + weight-load cost in unit tests.
"""

from __future__ import annotations

from typing import Callable, Protocol


class _ModelLike(Protocol):
    """The narrow surface of `sentence_transformers.CrossEncoder` we consume.

    Defined as a Protocol so tests can inject a fake without dragging the
    real dependency in."""

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]: ...


class Reranker:
    """Wraps a cross-encoder model with a stable Palimpsest API."""

    def __init__(self, *, model: _ModelLike) -> None:
        self._model = model

    def rerank(
        self,
        *,
        query: str,
        documents: list[str],
        top_k: int | None = None,
    ) -> list[str]:
        if not documents:
            return []
        pairs = [(query, d) for d in documents]
        scores = self._model.predict(pairs)
        ranked = sorted(zip(documents, scores), key=lambda x: x[1], reverse=True)
        result = [d for d, _ in ranked]
        if top_k is not None:
            result = result[:top_k]
        return result


def _default_factory(model_name: str) -> _ModelLike:
    # Deferred import so unit tests don't pay the torch tax.
    from sentence_transformers import CrossEncoder

    return CrossEncoder(model_name)  # type: ignore[return-value]


def build_reranker(
    model_name: str = "BAAI/bge-reranker-base",
    *,
    model_factory: Callable[[str], _ModelLike] = _default_factory,
) -> Reranker:
    return Reranker(model=model_factory(model_name))
