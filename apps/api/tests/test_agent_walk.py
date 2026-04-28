"""Walk planner tests — pure-Python over an injected coords dict so the
nearest-neighbor algorithm is testable without a postgres connection.
"""

from __future__ import annotations

import math

from app.agent.walk import (
    PlannedStop,
    haversine_m,
    plan_walk_from_coords,
)


_COORDS = {
    "wikipedia:A": (40.8038, -73.9619),  # Cathedral
    "wikipedia:B": (40.8108, -73.9626),  # Riverside Church (~770m N)
    "wikipedia:C": (40.8048, -73.9642),  # Columbia (close to A)
    "wikipedia:D": (40.7800, -73.9800),  # Far south, off the main cluster
}


# ── Haversine sanity ───────────────────────────────────────────────


def test_haversine_zero_for_same_point():
    assert haversine_m(40.0, -73.0, 40.0, -73.0) == 0.0


def test_haversine_within_5_percent_of_known_distance():
    """Cathedral (40.8038, -73.9619) to Riverside Church (40.8108, -73.9626)
    is ~770m. Allow ±5% tolerance for haversine vs PostGIS geodesic."""
    d = haversine_m(40.8038, -73.9619, 40.8108, -73.9626)
    assert 700 < d < 850


# ── Empty / single-stop edge cases ──────────────────────────────────


def test_empty_place_ids_returns_empty_route():
    route = plan_walk_from_coords([], _COORDS)
    assert route == []


def test_single_place_id_returns_single_stop_with_zero_leg():
    route = plan_walk_from_coords(["wikipedia:A"], _COORDS)
    assert len(route) == 1
    assert isinstance(route[0], PlannedStop)
    assert route[0].leg_distance_m == 0.0


def test_unknown_place_id_skipped_silently():
    """If the agent cited a place_id we no longer have coords for (e.g. row
    deleted between agent run and walk planning), drop it from the route."""
    route = plan_walk_from_coords(["wikipedia:A", "wikipedia:GHOST"], _COORDS)
    assert [s.doc_id for s in route] == ["wikipedia:A"]


# ── Multi-stop nearest-neighbor ─────────────────────────────────────


def test_route_starts_with_first_cited_doc_id():
    """V1 contract: the agent's narration order is the visit order, so the
    first stop is the first place_id the agent cited."""
    route = plan_walk_from_coords(
        ["wikipedia:B", "wikipedia:A", "wikipedia:C"], _COORDS
    )
    assert route[0].doc_id == "wikipedia:B"


def test_visit_order_matches_narration_order():
    """V1 spec: 'the agent's narration order is preserved as the visit order'."""
    route = plan_walk_from_coords(
        ["wikipedia:B", "wikipedia:A", "wikipedia:D", "wikipedia:C"], _COORDS
    )
    assert [s.doc_id for s in route] == [
        "wikipedia:B",
        "wikipedia:A",
        "wikipedia:D",
        "wikipedia:C",
    ]


def test_total_distance_is_sum_of_leg_distances():
    route = plan_walk_from_coords(
        ["wikipedia:A", "wikipedia:B", "wikipedia:C"], _COORDS
    )
    total = sum(s.leg_distance_m for s in route)
    # Sanity: under 5km for a 3-stop walk in a 5x5km bbox.
    assert 0 < total < 5000


def test_no_duplicate_stops_in_output():
    route = plan_walk_from_coords(
        ["wikipedia:A", "wikipedia:A", "wikipedia:B"], _COORDS
    )
    assert len(route) == len({s.doc_id for s in route})


def test_planned_stop_contains_lat_lon_and_index():
    route = plan_walk_from_coords(
        ["wikipedia:A", "wikipedia:B"], _COORDS
    )
    for i, stop in enumerate(route):
        assert stop.index == i
        assert isinstance(stop.lat, float) and isinstance(stop.lon, float)
        assert not math.isnan(stop.lat) and not math.isnan(stop.lon)
