"""Routing backend public surface.

Re-exports the names callers (the `plan_walk` tool, the SSE handler,
the lifespan) consume so internal layout — `osrm.py`, `steps.py`,
`types.py` — can shift without rippling through importers.
"""

from __future__ import annotations

from app.routing.osrm import OsrmBackend, RoutingBackend
from app.routing.types import (
    GeoJSONLineString,
    Leg,
    RouteResult,
    RoutingBackendError,
    Step,
)

__all__ = [
    "GeoJSONLineString",
    "Leg",
    "OsrmBackend",
    "RouteResult",
    "RoutingBackend",
    "RoutingBackendError",
    "Step",
]
