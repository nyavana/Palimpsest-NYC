"""Embedder contract tests.

Use a fake `SentenceTransformer` so the suite does NOT download HF weights
on every run. A separate, slow integration test (gated by env var) exercises
the real model end-to-end.
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np
import pytest

from app.embeddings import Embedder, build_embedder
from app.embeddings.errors import EmbeddingDimMismatchError


class FakeSentenceTransformer:
    """Mimics the small surface of `sentence_transformers.SentenceTransformer`
    that our Embedder actually uses."""

    def __init__(self, model_name_or_path: str, *, dim: int = 384, **_: Any) -> None:
        self.model_name = model_name_or_path
        self._dim = dim

    def get_sentence_embedding_dimension(self) -> int:
        return self._dim

    def encode(  # noqa: PLR0913 - mirrors real signature
        self,
        sentences: list[str],
        *,
        batch_size: int = 32,
        normalize_embeddings: bool = True,
        convert_to_numpy: bool = True,
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        # Deterministic, stable per-text vector: hash → seeded RNG → normalize.
        vecs: list[np.ndarray] = []
        for sentence in sentences:
            seed = int.from_bytes(sentence.encode(), "little") % (2**32)
            rng = np.random.default_rng(seed)
            v = rng.standard_normal(self._dim).astype(np.float32)
            if normalize_embeddings:
                v = v / np.linalg.norm(v)
            vecs.append(v)
        return np.stack(vecs)


# ── Embedder shape ──────────────────────────────────────────────────


def test_default_embedding_dim_is_384() -> None:
    emb = Embedder(model=FakeSentenceTransformer("BAAI/bge-small-en-v1.5"), dim=384)
    out = emb.encode(["The Cathedral of St. John the Divine"])
    assert len(out) == 1
    assert len(out[0]) == 384


def test_returns_python_floats_not_numpy() -> None:
    """Vectors are written to pgvector via SQLAlchemy. Plain floats round-trip
    cleanly; numpy floats sometimes confuse asyncpg codecs."""
    emb = Embedder(model=FakeSentenceTransformer("x"), dim=384)
    vec = emb.encode(["hello"])[0]
    assert all(isinstance(x, float) for x in vec)


def test_vectors_are_l2_normalized() -> None:
    emb = Embedder(model=FakeSentenceTransformer("x"), dim=384)
    vec = emb.encode(["any text"])[0]
    norm = float(np.linalg.norm(vec))
    assert abs(norm - 1.0) <= 1e-5


def test_same_text_two_calls_within_tolerance() -> None:
    emb = Embedder(model=FakeSentenceTransformer("x"), dim=384)
    a = np.array(emb.encode(["repeat"])[0])
    b = np.array(emb.encode(["repeat"])[0])
    assert float(np.max(np.abs(a - b))) <= 1e-5


def test_batched_equals_unbatched_within_tolerance() -> None:
    emb = Embedder(model=FakeSentenceTransformer("x"), dim=384, batch_size=32)
    batched = [np.array(v) for v in emb.encode(["a", "b", "c"])]
    one_at_a_time = [np.array(emb.encode([t])[0]) for t in ("a", "b", "c")]
    for u, v in zip(batched, one_at_a_time, strict=True):
        assert float(np.max(np.abs(u - v))) <= 1e-5


def test_empty_input_returns_empty_list() -> None:
    emb = Embedder(model=FakeSentenceTransformer("x"), dim=384)
    assert emb.encode([]) == []


# ── Dim mismatch guard ──────────────────────────────────────────────


def test_dim_mismatch_at_construction_raises() -> None:
    with pytest.raises(EmbeddingDimMismatchError) as ei:
        Embedder(model=FakeSentenceTransformer("x", dim=512), dim=384)
    msg = str(ei.value)
    assert "384" in msg and "512" in msg


# ── Builder wiring ──────────────────────────────────────────────────


def test_build_embedder_uses_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_embedder reads from EmbeddingsSettings and instantiates a model
    factory. We inject a fake factory to avoid downloading real weights."""
    monkeypatch.setenv("HF_HOME", "/tmp/test-hf-cache")
    captured: dict[str, Any] = {}

    def fake_factory(model_name: str) -> FakeSentenceTransformer:
        captured["model_name"] = model_name
        return FakeSentenceTransformer(model_name)

    from app.config import EmbeddingsSettings

    emb = build_embedder(
        EmbeddingsSettings(model="BAAI/bge-small-en-v1.5", dim=384, batch_size=16),
        model_factory=fake_factory,
    )
    assert captured["model_name"] == "BAAI/bge-small-en-v1.5"
    assert emb.batch_size == 16
    assert emb.dim == 384


# ── Slow integration test (off by default) ─────────────────────────


@pytest.mark.skipif(
    os.environ.get("PALIMPSEST_INTEGRATION") != "1",
    reason="requires PALIMPSEST_INTEGRATION=1 (downloads ~30MB of HF weights)",
)
def test_real_bge_small_model_loads_and_encodes() -> None:
    from app.config import EmbeddingsSettings

    emb = build_embedder(EmbeddingsSettings())
    out = emb.encode(["Cathedral of St. John the Divine, Morningside Heights"])
    assert len(out) == 1
    assert len(out[0]) == 384
    norm = float(np.linalg.norm(np.array(out[0])))
    assert abs(norm - 1.0) <= 1e-5
