"""Factory — returns the right retriever for RETRIEVAL_MODE.

Modes:
  - dense:            DenseRetriever (the V1 default)
  - hybrid:           HybridRetriever(dense, sparse) with RRF
  - hybrid_reranked:  RerankedRetriever wrapping a HybridRetriever (Phase 5)

The factory is the SINGLE place that knows about modes; everything downstream
(the agent loop, search_places, the SSE route) is mode-agnostic.
"""

from __future__ import annotations

from typing import Any, Literal

from app.retrieval.dense import DenseRetriever
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.sparse import SparseRetriever

RetrievalMode = Literal["dense", "hybrid", "hybrid_reranked"]


def build_retriever(
    *,
    mode: str = "dense",
    reranker: Any = None,
) -> Any:
    if mode == "dense":
        return DenseRetriever()

    if mode == "hybrid":
        return HybridRetriever(dense=DenseRetriever(), sparse=SparseRetriever())

    if mode == "hybrid_reranked":
        # Imported inside the branch so test_retrieval_factory doesn't drag the
        # reranker module in (which loads a torch model on import in production).
        from app.retrieval.reranked import RerankedRetriever
        if reranker is None:
            raise ValueError("hybrid_reranked mode requires a reranker singleton")
        inner = HybridRetriever(dense=DenseRetriever(), sparse=SparseRetriever())
        return RerankedRetriever(inner=inner, reranker=reranker)

    raise ValueError(f"unknown RETRIEVAL_MODE: {mode!r}")
