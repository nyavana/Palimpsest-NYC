"""Reciprocal Rank Fusion.

Cormack, Clarke, Buettcher (2009): combine multiple ranked lists into a single
list by summing 1/(k + rank) across lists. k=60 is the canonical default.

Pure function — no I/O — easy to test deterministically.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Hashable, Sequence, TypeVar

T = TypeVar("T", bound=Hashable)


def reciprocal_rank_fusion(rankings: Sequence[Sequence[T]], *, k: int = 60) -> list[T]:
    """Fuse multiple ranked lists with RRF.

    Args:
        rankings: each element is an ordered sequence (best first).
        k: smoothing constant. Higher k means top-rank dominance decays slower.

    Returns:
        A single ranked list of unique items in descending fused-score order.
    """
    scores: dict[T, float] = defaultdict(float)
    seen_in_list: set[tuple[int, T]] = set()
    for list_idx, ranking in enumerate(rankings):
        for rank, item in enumerate(ranking, start=1):
            key = (list_idx, item)
            if key in seen_in_list:
                continue
            seen_in_list.add(key)
            scores[item] += 1.0 / (k + rank)

    return sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
