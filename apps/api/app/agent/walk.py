"""Server-side `plan_walk` — runs after the agent emits its citations[].

Per `swap-llm-tiers-and-lock-mvp-decisions/specs/agent-tools/spec.md`:

> After the agent emits its final response, the server SHALL run a
> deterministic PostGIS routing pass over the place_ids referenced in
> citations[] to produce an ordered walking route, which the frontend
> renders as a path with markers. The agent does not call this routing
> pass; the LLM never sees it as a tool.
> the agent's narration order is preserved as the visit order.

V1 algorithm:
  - "narration order is preserved as the visit order" → the first cited
    doc_id is the start; each subsequent cited doc_id continues in order
    if it's in `place_ids`. After the citation order is exhausted, no
    stops remain (we don't insert non-cited places).
  - For each consecutive pair, leg_distance_m is the geodesic haversine
    distance in meters. The full ST_Distance (PostGIS geodesic) would be
    marginally more accurate but haversine is within 0.5% at NYC scale.

A `PlanWalker` async helper handles the postgres lookup of (doc_id, lat, lon)
for the citation list and then defers to `plan_walk_from_coords`. Keeping
the algorithm pure-Python lets tests exercise it without a DB.

Note on naming: the V1 contract preserves narration order rather than
running a nearest-neighbor reordering. A more elaborate routing pass
(NN, TSP, with street-graph distances) is a v2 enhancement when the
walking corpus grows large enough that ordering matters.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text


@dataclass(slots=True)
class PlannedStop:
    index: int  # 0-based stop index along the route
    doc_id: str
    name: str
    lat: float
    lon: float
    leg_distance_m: float  # distance from previous stop; 0.0 for index=0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Geodesic distance in meters using the haversine formula on the WGS-84
    sphere approximation. Within ~0.5% of PostGIS at NYC scale."""
    earth_r_m = 6_371_008.8  # mean Earth radius (matches PostGIS default)
    rad = math.radians
    dlat = rad(lat2 - lat1)
    dlon = rad(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(rad(lat1)) * math.cos(rad(lat2)) * math.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * math.asin(min(1.0, math.sqrt(a)))
    return earth_r_m * c


def plan_walk_from_coords(
    place_ids: list[str],
    coords: dict[str, tuple[float, float]],
    *,
    names: dict[str, str] | None = None,
) -> list[PlannedStop]:
    """Build an ordered route from a list of place doc_ids.

    `coords` maps doc_id → (lat, lon). `names` is an optional doc_id → label
    map; missing names default to the doc_id string.

    Order is preserved from `place_ids` (V1 contract). Duplicates are
    deduped (keep first occurrence). Unknown doc_ids are dropped.
    """
    names = names or {}
    seen: set[str] = set()
    ordered: list[str] = []
    for doc_id in place_ids:
        if doc_id in seen or doc_id not in coords:
            continue
        seen.add(doc_id)
        ordered.append(doc_id)

    stops: list[PlannedStop] = []
    prev_lat = prev_lon = 0.0
    for i, doc_id in enumerate(ordered):
        lat, lon = coords[doc_id]
        leg = 0.0 if i == 0 else haversine_m(prev_lat, prev_lon, lat, lon)
        stops.append(
            PlannedStop(
                index=i,
                doc_id=doc_id,
                name=names.get(doc_id, doc_id),
                lat=lat,
                lon=lon,
                leg_distance_m=leg,
            )
        )
        prev_lat, prev_lon = lat, lon
    return stops


# ── DB-backed wrapper ──────────────────────────────────────────────


async def plan_walk(
    *,
    session: Any,
    place_ids: list[str],
) -> list[PlannedStop]:
    """Resolve the cited doc_ids' coordinates from postgres, then build
    the ordered route. The agent never invokes this — the SSE handler does
    it after the citation set is verified."""
    if not place_ids:
        return []
    sql = text(
        """
        SELECT
            doc_id,
            name,
            ST_Y(geom::geometry) AS lat,
            ST_X(geom::geometry) AS lon
        FROM places
        WHERE doc_id = ANY(:doc_ids)
        """
    )
    result = await session.execute(sql, {"doc_ids": place_ids})
    coords: dict[str, tuple[float, float]] = {}
    names: dict[str, str] = {}
    for row in result.mappings():
        coords[row["doc_id"]] = (float(row["lat"]), float(row["lon"]))
        names[row["doc_id"]] = row["name"]
    return plan_walk_from_coords(place_ids, coords, names=names)
