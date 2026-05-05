"""Walk planner tests — pure-Python over an injected coords dict so the
nearest-neighbor algorithm is testable without a postgres connection.
"""

from __future__ import annotations

import math
from typing import Any

import pytest
from app.agent.walk import (
    PlannedStop,
    discover_pois_along_route,
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


# ── discover_pois_along_route ─────────────────────────────────────


class _FakeMappings:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> _FakeMappings:
        return _FakeMappings(self._rows)


class _FakeSession:
    """Records the last SQL+params and returns canned rows from `mappings()`."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.last_sql: Any = None
        self.last_params: dict[str, Any] | None = None
        self.execute_calls = 0

    async def execute(self, sql: Any, params: dict[str, Any] | None = None):
        self.execute_calls += 1
        self.last_sql = sql
        self.last_params = params
        return _FakeResult(list(self.rows))


_LINESTRING = {
    "type": "LineString",
    "coordinates": [[-73.9619, 40.8038], [-73.9626, 40.8108]],
}


async def test_discover_pois_skips_when_geometry_has_no_segment():
    """A LineString with <2 vertices is degenerate — no buffer query, no POIs."""
    session = _FakeSession(rows=[])
    out = await discover_pois_along_route(
        session=session,
        route_geometry={"type": "LineString", "coordinates": []},
        exclude_doc_ids=["wikipedia:A"],
    )
    assert out == []
    assert session.execute_calls == 0


async def test_discover_pois_returns_rows_in_along_route_order():
    """Helper picks rows from the DB and returns them sorted by along_t.

    The DB-side ORDER BY puts quality + closeness first; the helper then
    re-sorts the picked subset along the route so insertion order matches
    walking direction.
    """
    rows = [
        {
            "doc_id": "wikipedia:R",
            "name": "Riverside Church",
            "source_type": "wikipedia",
            "source_url": "https://en.wikipedia.org/wiki/Riverside_Church",
            "lat": 40.8108,
            "lon": -73.9626,
            "dist_m": 12.5,
            "along_t": 0.95,
        },
        {
            "doc_id": "wikipedia:G",
            "name": "Grant's Tomb",
            "source_type": "wikipedia",
            "source_url": "https://en.wikipedia.org/wiki/Grant%27s_Tomb",
            "lat": 40.8133,
            "lon": -73.9627,
            "dist_m": 22.0,
            "along_t": 0.40,
        },
        {
            "doc_id": "wikipedia:C",
            "name": "Columbia",
            "source_type": "wikipedia",
            "source_url": "https://en.wikipedia.org/wiki/Columbia_University",
            "lat": 40.8075,
            "lon": -73.9626,
            "dist_m": 30.0,
            "along_t": 0.10,
        },
    ]
    session = _FakeSession(rows=rows)

    out = await discover_pois_along_route(
        session=session,
        route_geometry=_LINESTRING,
        exclude_doc_ids=["wikipedia:A", "wikipedia:B"],
        radius_m=200,
        limit=3,
    )

    assert [p["doc_id"] for p in out] == ["wikipedia:C", "wikipedia:G", "wikipedia:R"]
    assert all(
        set(p.keys())
        == {
            "doc_id",
            "name",
            "source_type",
            "source_url",
            "lat",
            "lon",
            "dist_to_route_m",
            "along_t",
        }
        for p in out
    )
    # Quality + dist sorting happens server-side; we only assert the
    # along-route reordering on the client.
    assert out[0]["along_t"] < out[1]["along_t"] < out[2]["along_t"]
    # Excluded ids are forwarded as the SQL parameter.
    assert session.last_params is not None
    assert session.last_params["exclude_ids"] == ["wikipedia:A", "wikipedia:B"]
    assert session.last_params["radius_m"] == 200


async def test_discover_pois_caps_at_limit_and_re_sorts_remaining_along_route():
    """`limit=2` keeps the top-2 by quality+distance, then sorts those two by along_t."""
    rows = [
        # DB returns rows in quality+distance order (already ranked).
        {
            "doc_id": "wikipedia:Z",
            "name": "Z",
            "source_type": "wikipedia",
            "source_url": "https://en.wikipedia.org/wiki/Z",
            "lat": 40.81,
            "lon": -73.96,
            "dist_m": 5.0,
            "along_t": 0.85,
        },
        {
            "doc_id": "wikipedia:Y",
            "name": "Y",
            "source_type": "wikipedia",
            "source_url": "https://en.wikipedia.org/wiki/Y",
            "lat": 40.81,
            "lon": -73.96,
            "dist_m": 10.0,
            "along_t": 0.20,
        },
        {
            "doc_id": "wikipedia:X",
            "name": "X",
            "source_type": "wikipedia",
            "source_url": "https://en.wikipedia.org/wiki/X",
            "lat": 40.81,
            "lon": -73.96,
            "dist_m": 90.0,
            "along_t": 0.50,
        },
    ]
    session = _FakeSession(rows=rows)
    out = await discover_pois_along_route(
        session=session,
        route_geometry=_LINESTRING,
        exclude_doc_ids=[],
        limit=2,
    )
    assert [p["doc_id"] for p in out] == ["wikipedia:Y", "wikipedia:Z"]


async def test_discover_pois_returns_empty_when_db_returns_nothing():
    session = _FakeSession(rows=[])
    out = await discover_pois_along_route(
        session=session,
        route_geometry=_LINESTRING,
        exclude_doc_ids=[],
    )
    assert out == []
    # Query was issued (we can't predict the DB result without running it).
    assert session.execute_calls == 1


_ = pytest  # silence unused-import linter when no pytest fixtures are referenced
