"""OSRM HTTP routing backend.

V1's only `RoutingBackend` implementation. Targets a containerized OSRM
instance (`osrm/osrm-backend:v5.27.1`) reachable at `OSRM_BASE_URL`. The
client branches between two OSRM endpoints based on stop count:

  - 2 stops → `/route/v1/foot/{coords}` (shortest path).
  - 3-8 stops → `/trip/v1/foot/{coords}` (TSP, with `source=first` and
    `destination=last` pinning the agent's narrative anchors).

The client issues exactly one HTTP request per `route()` call. We do
NOT hold a long-lived `httpx.AsyncClient` so the lifespan can construct
and store this backend without owning a connection pool — for tests we
accept an injected client via the `client` parameter.

GeoJSON geometry is passed through untouched (`geometries=geojson`); see
`openspec/changes/agent-route-planning/design.md` §2 for the rationale
on why we use GeoJSON LineString rather than encoded polyline as the
wire format.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

import httpx

from app.routing.steps import format_step, should_keep_step
from app.routing.types import (
    Coordinate,
    GeoJSONLineString,
    Leg,
    RouteResult,
    RoutingBackendError,
    Step,
)

_FOOT_ROUTE_PATH = "/route/v1/foot/{coords}"
_FOOT_TRIP_PATH = "/trip/v1/foot/{coords}"

_MAX_STOPS = 8
_MIN_STOPS = 2

# HTTP status threshold above which we surface a synthetic
# `upstream_5xx` RoutingBackendError rather than parsing the body.
_HTTP_5XX_THRESHOLD = 500


@runtime_checkable
class RoutingBackend(Protocol):
    """The seam the `plan_walk` tool talks to.

    Tests inject a fake conforming to this Protocol; production wires in
    `OsrmBackend`. Keeping the seam to a single `route()` method keeps
    the v2 swap to a hosted ORS/OSRM endpoint a base-URL change with
    no caller-side rewrites.
    """

    async def route(
        self,
        stops: list[Coordinate],
        mode: Literal["walking"] = "walking",
    ) -> RouteResult: ...


def _format_coords(stops: list[Coordinate]) -> str:
    """Build OSRM's `lon,lat;lon,lat;...` coords path segment.

    Note: OSRM expects longitude FIRST, latitude SECOND (the GeoJSON
    convention). Our input `Coordinate` is `(lat, lon)`, so we swap.
    """
    return ";".join(f"{lon},{lat}" for (lat, lon) in stops)


def _extract_geometry(raw: Any) -> GeoJSONLineString:
    """Validate that `raw` is a GeoJSON LineString and return it unchanged.

    OSRM gives us the dict shape we want when we ask for
    `geometries=geojson`; this helper only confirms the type so a
    mismatched response doesn't propagate a malformed wire payload.
    """
    if not isinstance(raw, dict) or raw.get("type") != "LineString":
        raise RoutingBackendError(
            "InvalidResponse",
            "OSRM returned a non-LineString geometry; expected geometries=geojson",
        )
    coords = raw.get("coordinates")
    if not isinstance(coords, list):
        raise RoutingBackendError("InvalidResponse", "OSRM geometry is missing a coordinates array")
    return {"type": "LineString", "coordinates": coords}


def _concat_step_geometries(steps_raw: list[dict[str, Any]]) -> GeoJSONLineString:
    """Build a leg geometry by concatenating step geometries.

    OSRM's per-leg geometry is the same shape as the full-route geometry
    only when the request asks for `overview=full` — but `overview=full`
    populates the top-level `route.geometry`, not per-leg. We synthesize
    a per-leg LineString by stitching step geometries end-to-end (last
    point of step `i` = first point of step `i+1`, dedup at the seam).
    Fallback to an empty LineString if a step has no geometry.
    """
    coords: list[list[float]] = []
    for step in steps_raw:
        geom = step.get("geometry")
        if not isinstance(geom, dict):
            continue
        step_coords = geom.get("coordinates")
        if not isinstance(step_coords, list):
            continue
        if not coords:
            coords.extend(step_coords)
        # dedup the seam point if present
        elif step_coords and coords and coords[-1] == step_coords[0]:
            coords.extend(step_coords[1:])
        else:
            coords.extend(step_coords)
    return {"type": "LineString", "coordinates": coords}


def _parse_step(step_raw: dict[str, Any]) -> Step | None:
    """Convert one OSRM step dict to a `Step`, applying the drop rule.

    Returns `None` if the step is a tiny non-bookend that
    `should_keep_step` filters out.
    """
    maneuver = step_raw.get("maneuver") or {}
    mtype = (maneuver.get("type") or "").lower()
    distance_raw = step_raw.get("distance") or 0
    duration_raw = step_raw.get("duration") or 0
    distance_m = round(float(distance_raw))
    duration_s = round(float(duration_raw))

    if not should_keep_step(mtype, distance_m):
        return None

    name = step_raw.get("name")
    instruction = format_step(maneuver, name, distance_m)

    geometry: GeoJSONLineString | None = None
    raw_geom = step_raw.get("geometry")
    if isinstance(raw_geom, dict) and raw_geom.get("type") == "LineString":
        coords = raw_geom.get("coordinates")
        if isinstance(coords, list):
            geometry = {"type": "LineString", "coordinates": coords}

    return Step(
        instruction=instruction,
        distance_m=distance_m,
        duration_s=duration_s,
        maneuver_type=mtype,
        geometry=geometry,
    )


def _parse_leg(
    leg_raw: dict[str, Any],
    from_index: int,
    to_index: int,
) -> Leg:
    """Convert one OSRM leg dict into a `Leg`."""
    steps_raw = leg_raw.get("steps") or []
    steps: list[Step] = []
    for step_raw in steps_raw:
        step = _parse_step(step_raw)
        if step is not None:
            steps.append(step)

    distance_m = round(float(leg_raw.get("distance") or 0))
    duration_s = round(float(leg_raw.get("duration") or 0))
    geometry = _concat_step_geometries(steps_raw)

    return Leg(
        from_index=from_index,
        to_index=to_index,
        distance_m=distance_m,
        duration_s=duration_s,
        geometry=geometry,
        steps=steps,
    )


def _parse_route_legs(legs_raw: list[dict[str, Any]]) -> list[Leg]:
    """Parse `/route` legs in the input order (no permutation)."""
    return [_parse_leg(leg, i, i + 1) for i, leg in enumerate(legs_raw)]


def _parse_trip_legs(
    legs_raw: list[dict[str, Any]],
    waypoints: list[dict[str, Any]],
) -> list[Leg]:
    """Parse `/trip` legs and reorder them by the optimized visit sequence.

    OSRM's `/trip` returns `waypoints[i].waypoint_index` describing the
    optimized position of the i-th INPUT waypoint (i.e., a permutation
    of `[0..n)`). The legs in `trip.legs` already follow the optimized
    visit order — leg `j` connects the waypoint visited j-th to the
    waypoint visited (j+1)-th. We just need to label each leg's
    `from_index` / `to_index` with the INPUT positions so the consumer
    can correlate legs back to the agent's `place_ids`.
    """
    if not waypoints:
        return _parse_route_legs(legs_raw)

    # Build the optimized visit order: visit_to_input[j] = input index visited at j.
    visit_to_input: list[int] = [-1] * len(waypoints)
    for input_idx, wp in enumerate(waypoints):
        try:
            visit_pos = int(wp.get("waypoint_index"))
        except (TypeError, ValueError):
            visit_pos = input_idx
        if 0 <= visit_pos < len(visit_to_input):
            visit_to_input[visit_pos] = input_idx

    # Defensive: if any slot is unfilled, fall back to identity for it.
    for j, src in enumerate(visit_to_input):
        if src < 0:
            visit_to_input[j] = j

    legs: list[Leg] = []
    for j, leg_raw in enumerate(legs_raw):
        from_idx = visit_to_input[j]
        to_idx = visit_to_input[j + 1] if (j + 1) < len(visit_to_input) else j + 1
        legs.append(_parse_leg(leg_raw, from_idx, to_idx))
    return legs


class OsrmBackend:
    """OSRM HTTP routing backend.

    `base_url` is the OSRM root (e.g., `http://osrm:5000`). The client
    issues one HTTP GET per `route()` call. For tests, an `httpx.AsyncClient`
    can be injected via the `client` parameter; otherwise a fresh client
    is constructed per call (and closed on exit) so this object is safe
    to keep on `app.state` without owning a connection pool.
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = 10.0,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = client

    async def route(
        self,
        stops: list[Coordinate],
        mode: Literal["walking"] = "walking",
    ) -> RouteResult:
        if mode != "walking":
            raise ValueError("V1 only supports mode='walking'")
        n = len(stops)
        if n < _MIN_STOPS:
            raise ValueError(f"route() requires at least {_MIN_STOPS} stops; got {n}")
        if n > _MAX_STOPS:
            raise ValueError(
                f"route() supports at most {_MAX_STOPS} stops "
                f"(OSRM /trip's brute-force-optimal regime); got {n}"
            )

        coords_segment = _format_coords(stops)

        # NOTE: we do NOT send a `radiuses=...` snap constraint. The
        # constraint constrained candidate routing edges so tightly that
        # valid routes through the network were rejected (NoRoute /
        # NoTrips) even when every stop snapped within the radius. Letting
        # OSRM use its default unconstrained snapping is the right behavior
        # for a small bbox where road density bounds the snap distance.
        if n == _MIN_STOPS:
            url = f"{self.base_url}{_FOOT_ROUTE_PATH.format(coords=coords_segment)}"
            params: dict[str, str] = {
                "steps": "true",
                "overview": "full",
                "geometries": "geojson",
                "annotations": "duration,distance",
            }
            stop_ordering: Literal["input_order", "tsp_optimized"] = "input_order"
            is_trip = False
        else:
            url = f"{self.base_url}{_FOOT_TRIP_PATH.format(coords=coords_segment)}"
            params = {
                "steps": "true",
                "overview": "full",
                "geometries": "geojson",
                "source": "first",
                "destination": "last",
                "roundtrip": "false",
            }
            stop_ordering = "tsp_optimized"
            is_trip = True

        payload = await self._get_json(url, params)

        code = payload.get("code")
        if code != "Ok":
            message = str(payload.get("message") or "OSRM returned non-Ok status")
            raise RoutingBackendError(str(code or "Unknown"), message)

        if is_trip:
            entries = payload.get("trips") or []
            waypoints = payload.get("waypoints") or []
        else:
            entries = payload.get("routes") or []
            waypoints = []
        if not entries:
            raise RoutingBackendError(
                "EmptyRoute",
                "OSRM responded code=Ok but returned no routes/trips",
            )

        primary = entries[0]
        geometry = _extract_geometry(primary.get("geometry"))
        legs_raw = primary.get("legs") or []

        legs = _parse_trip_legs(legs_raw, waypoints) if is_trip else _parse_route_legs(legs_raw)

        total_distance_m = round(float(primary.get("distance") or 0))
        total_duration_s = round(float(primary.get("duration") or 0))

        return RouteResult(
            geometry=geometry,
            total_distance_m=total_distance_m,
            total_duration_s=total_duration_s,
            legs=legs,
            routing_backend="osrm",
            stop_ordering=stop_ordering,
        )

    async def _get_json(self, url: str, params: dict[str, str]) -> dict[str, Any]:
        """Single GET with timeout/error mapping. Uses an injected client
        when one was provided to the constructor (tests); otherwise opens
        a per-call client so the lifespan doesn't own a pool.
        """
        try:
            if self._client is not None:
                resp = await self._client.get(url, params=params, timeout=self.timeout)
            else:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.get(url, params=params)
        except httpx.TimeoutException as exc:
            raise RoutingBackendError("timeout", str(exc)) from exc
        except httpx.ConnectError as exc:
            raise RoutingBackendError("connection_error", str(exc)) from exc
        except httpx.HTTPError as exc:
            # Catch-all for transport errors that aren't timeout/connect (e.g.
            # protocol errors). Map to a synthetic code so callers get a
            # uniform `RoutingBackendError` surface.
            raise RoutingBackendError("transport_error", str(exc)) from exc

        if resp.status_code >= _HTTP_5XX_THRESHOLD:
            raise RoutingBackendError("upstream_5xx", f"OSRM responded {resp.status_code}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise RoutingBackendError("invalid_json", str(exc)) from exc
        if not isinstance(payload, dict):
            raise RoutingBackendError("InvalidResponse", "OSRM response was not a JSON object")
        return payload
