"""Reranker singleton — wraps a cross-encoder. Behavior tested with a fake
model so we don't load torch in unit tests."""

from __future__ import annotations

from typing import Any

import pytest

from app.embeddings.reranker import Reranker


class _FakeCrossEncoder:
    """Returns scores that match doc index (lower-indexed = higher score)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        self.calls.append(("predict", [p[1] for p in pairs]))
        # Reverse the order: docs at the END of the pairs list should rank higher.
        return [float(i) for i, _ in enumerate(pairs)]


def test_reranker_orders_by_predicted_score_descending() -> None:
    reranker = Reranker(model=_FakeCrossEncoder())
    docs = ["doc-A", "doc-B", "doc-C"]
    reranked = reranker.rerank(query="q", documents=docs)
    # FakeCrossEncoder gives scores [0, 1, 2] → desc order [C, B, A]
    assert reranked == ["doc-C", "doc-B", "doc-A"]


def test_reranker_truncates_to_top_k() -> None:
    reranker = Reranker(model=_FakeCrossEncoder())
    docs = ["a", "b", "c", "d", "e"]
    reranked = reranker.rerank(query="q", documents=docs, top_k=2)
    assert len(reranked) == 2


def test_reranker_handles_empty_documents() -> None:
    reranker = Reranker(model=_FakeCrossEncoder())
    assert reranker.rerank(query="q", documents=[]) == []
