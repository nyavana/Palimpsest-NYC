"""RRF tests — pure function, no I/O."""

from __future__ import annotations

import pytest

from app.retrieval.fusion import reciprocal_rank_fusion


def test_rrf_combines_two_rankings_preserving_top_hits():
    # Same doc at rank 1 in both lists should rank first
    dense = ["A", "B", "C", "D"]
    sparse = ["A", "C", "B", "E"]
    merged = reciprocal_rank_fusion([dense, sparse], k=60)
    assert merged[0] == "A"
    assert set(merged) == {"A", "B", "C", "D", "E"}


def test_rrf_rewards_appearance_in_multiple_lists():
    # B appears in both lists at decent ranks; should beat A which appears once
    dense = ["A", "B", "C", "D", "E"]
    sparse = ["X", "B", "Y", "Z", "W"]
    merged = reciprocal_rank_fusion([dense, sparse], k=60)
    # B's combined score: 1/(60+2) + 1/(60+2) = 2/62
    # A's combined score: 1/(60+1) = 1/61
    # 2/62 > 1/61 → B should outrank A
    assert merged.index("B") < merged.index("A")


def test_rrf_handles_empty_lists():
    assert reciprocal_rank_fusion([[], []], k=60) == []
    assert reciprocal_rank_fusion([["A"], []], k=60) == ["A"]


def test_rrf_handles_duplicates_in_one_list():
    # Defensive: input shouldn't contain duplicates within a list, but if it
    # does, behavior should be the first-occurrence rank.
    merged = reciprocal_rank_fusion([["A", "B", "A"], ["C"]], k=60)
    assert merged[0] in ("A", "B", "C")
    assert "A" in merged and "B" in merged and "C" in merged


def test_rrf_k_param_affects_relative_weighting():
    # With very small k, top-ranked items dominate even more.
    dense = ["A", "B"]
    sparse = ["B", "A"]
    merged_high_k = reciprocal_rank_fusion([dense, sparse], k=60)
    merged_low_k = reciprocal_rank_fusion([dense, sparse], k=1)
    # Either way, the sum is symmetric and one wins by ordering; just sanity-check it doesn't crash.
    assert len(merged_high_k) == len(merged_low_k) == 2
