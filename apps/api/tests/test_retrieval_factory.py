"""Factory dispatches on RETRIEVAL_MODE and returns the right retriever class."""

from __future__ import annotations

import pytest

from app.retrieval.dense import DenseRetriever
from app.retrieval.factory import build_retriever
from app.retrieval.hybrid import HybridRetriever


def test_factory_dense_returns_dense_retriever():
    r = build_retriever(mode="dense")
    assert isinstance(r, DenseRetriever)


def test_factory_hybrid_returns_hybrid_retriever():
    r = build_retriever(mode="hybrid")
    assert isinstance(r, HybridRetriever)


def test_factory_hybrid_reranked_raises_without_reranker():
    with pytest.raises(ValueError, match="reranker"):
        build_retriever(mode="hybrid_reranked", reranker=None)


def test_factory_unknown_mode_raises():
    with pytest.raises(ValueError, match="unknown RETRIEVAL_MODE"):
        build_retriever(mode="garbage")
