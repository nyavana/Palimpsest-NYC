"""Embedder error hierarchy."""

from __future__ import annotations


class EmbeddingError(RuntimeError):
    """Base class for embedder failures surfaced to callers."""


class EmbeddingDimMismatchError(EmbeddingError):
    """Configured EMBEDDING_DIM does not match the loaded model's dimension.

    Spec: this is a startup-time fatal — the migrations declare
    `vector(EMBEDDING_DIM)` and a mismatch would corrupt inserts.
    """
