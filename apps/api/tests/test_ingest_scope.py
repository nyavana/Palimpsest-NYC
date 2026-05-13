"""Scope-bbox tests. Locks the Manhattan-wide bbox so accidental shrinking
trips a test rather than silently scoping ingestion smaller."""

from __future__ import annotations

from app.ingest.scope import SCOPE_BBOX, SCOPE_VERSION


def test_bbox_covers_manhattan_extremes():
    # Lower Manhattan landmarks
    assert SCOPE_BBOX.contains(40.7060, -74.0090)   # Battery Park area
    assert SCOPE_BBOX.contains(40.7484, -73.9857)   # Empire State
    # Upper Manhattan / Inwood
    assert SCOPE_BBOX.contains(40.8676, -73.9213)   # Inwood Hill Park
    # Brooklyn / Queens just outside Manhattan should NOT be in
    assert not SCOPE_BBOX.contains(40.6782, -73.9442)  # Prospect Park
    assert not SCOPE_BBOX.contains(40.7282, -73.7949)  # Forest Hills


def test_scope_version_bumped_for_manhattan():
    # Bumped from "v1-morningside-uws" to "v2-manhattan"
    assert SCOPE_VERSION == "v2-manhattan"
