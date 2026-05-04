"""Routing module typed value objects.

These dataclasses describe the wire format the agent and SSE handler emit
for the `walk` frame. The contract is:

  - `Coordinate` is `(lat, lon)` (latitude first) — the agent's existing
    convention from `app/agent/walk.py`.
  - `GeoJSONLineString` follows RFC 7946: `coordinates` is a list of
    `[lon, lat]` pairs (longitude FIRST). All geometries that ride the
    wire are GeoJSON, never encoded polylines (see
    `openspec/changes/agent-route-planning/design.md` §2 for rationale).
  - `RouteResult` carries the full route geometry plus per-leg detail.
    `routing_backend` and `stop_ordering` are telemetry tags so the
    SSE handler / session log can record which path produced this
    result without re-deriving it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypedDict

# (lat, lon) — matches the existing `app/agent/walk.py` convention.
Coordinate = tuple[float, float]


class GeoJSONLineString(TypedDict):
    """RFC 7946 GeoJSON LineString. `coordinates` is `[[lon, lat], ...]`."""

    type: Literal["LineString"]
    coordinates: list[list[float]]


@dataclass(slots=True)
class Step:
    """A single OSRM maneuver, formatted as English step text.

    `geometry` is optional — V1 omits it when OSRM doesn't surface a
    per-step geometry, in which case the per-leg geometry is sufficient
    to render the path.
    """

    instruction: str
    distance_m: int
    duration_s: int
    maneuver_type: str
    geometry: GeoJSONLineString | None = None


@dataclass(slots=True)
class Leg:
    """A leg from stop `from_index` to stop `to_index` along the route."""

    from_index: int
    to_index: int
    distance_m: int
    duration_s: int
    geometry: GeoJSONLineString
    steps: list[Step] = field(default_factory=list)


@dataclass(slots=True)
class RouteResult:
    """The full output of a single `RoutingBackend.route()` call.

    `routing_backend ∈ {"osrm", "haversine_fallback"}` and
    `stop_ordering ∈ {"input_order", "tsp_optimized"}` are telemetry tags
    plumbed all the way to the SSE `walk` frame so the frontend (and the
    session log) can attribute which path produced this result.
    """

    geometry: GeoJSONLineString
    total_distance_m: int
    total_duration_s: int
    legs: list[Leg]
    routing_backend: Literal["osrm", "haversine_fallback"]
    stop_ordering: Literal["input_order", "tsp_optimized"]


class RoutingBackendError(Exception):
    """Raised by `RoutingBackend` implementations on routing failure.

    The `code` is the OSRM-style status (`NoRoute`, `NoSegment`, etc.) or
    one of the synthetic values the OSRM client maps transport-level
    failures onto (`timeout`, `connection_error`). `message` carries
    upstream detail for telemetry; the agent-side fallback path uses
    this to build a structured warning record.
    """

    code: str
    message: str

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
