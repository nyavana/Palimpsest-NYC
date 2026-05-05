"""`plan_walk` — the second LLM-callable tool in V1.

The LLM picks `place_ids` (returned by prior `search_places` calls) and
this tool turns them into a real walking route via the
`RoutingBackend` injected on the `ToolExecutionContext`. When the LLM
passes a small endpoint set (≤ 3 stops), the tool also auto-discovers
nearby POIs along the path and splices them into the route as extra
stops; those stops are surfaced under `discovered_stops[]` with full
citation provenance and the agent loop registers them in the
per-conversation `RetrievalLedger` so the LLM can cite them in its
final JSON.

V1 contract (see
`openspec/changes/agent-route-planning/specs/agent-tools/spec.md` and
`openspec/changes/agent-route-planning/design.md` §4 / §10):

  - 2-8 distinct `place_ids` (after dedup keeping first occurrence).
  - `mode="walking"` only; `mode="driving"` etc. surface a structured
    error rather than a routing call.
  - `place_id` must appear in the per-conversation `RetrievalLedger`
    populated by `search_places` results — anything else is rejected
    structurally before the routing backend is touched.
  - Coordinate lookup re-uses `app.agent.walk.plan_walk` (the DB-backed
    helper) — same SQL today's server-side post-processing pass uses.
  - On `RoutingBackendError`, the tool falls back to a structurally
    identical `RouteResult` built from straight-line haversine legs.
    The fallback logs a structured warning so telemetry sees the
    degradation, then returns the dict — the agent loop never sees an
    exception. Haversine-fallback routes are NOT auto-enriched.

The tool's return value is a JSON-serializable dict whose keys mirror
the `RouteResult` dataclass plus `discovered_stops[]`; the SSE handler
emits it as the `walk` frame byte-for-byte.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.agent.tools.base import Tool, ToolExecutionContext
from app.agent.walk import PlannedStop, discover_pois_along_route, haversine_m
from app.agent.walk import plan_walk as plan_walk_db
from app.routing import RoutingBackendError

# ── Constants ──────────────────────────────────────────────────────

# Comfortable walking pace (~5 km/h) used to synthesize fallback durations.
WALK_M_PER_S = 1.4

# Minimum distinct stops required for a "route" — anything less is just a
# marker, which the citation-driven map already shows. Mirrors the JSON
# Schema `minItems=2` on `place_ids`.
_MIN_DISTINCT_STOPS = 2

# Auto-enrichment kicks in only when the LLM passed a small endpoint set.
# At ≥4 stops the LLM has clearly hand-curated and we don't second-guess.
_AUTO_ENRICH_MAX_INPUT_STOPS = 3

# Buffer-search radius and per-route POI cap. These match the documented
# defaults in `docs/...` and keep the total stop count comfortably under
# the OSRM /trip 8-stop ceiling (3 input + 3 enriched = 6 max).
_ENRICH_RADIUS_M = 150
_ENRICH_LIMIT = 3

_SUPPORTED_MODES = frozenset({"walking"})

_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "required": ["place_ids"],
    "properties": {
        "place_ids": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
            "maxItems": 8,
            "description": (
                "doc_ids of places returned by search_places, in the desired "
                "visit order."
            ),
        },
        "mode": {
            "type": "string",
            "enum": ["walking"],
            "default": "walking",
            "description": "V1 supports walking only.",
        },
    },
}


# ── Helpers ────────────────────────────────────────────────────────


def _dedupe_keep_first(place_ids: list[str]) -> list[str]:
    """Drop duplicate `place_ids`, preserving the first occurrence's order."""
    seen: set[str] = set()
    out: list[str] = []
    for pid in place_ids:
        if pid in seen:
            continue
        seen.add(pid)
        out.append(pid)
    return out


def _is_known_to_ledger(ledger: Any, doc_id: str) -> bool:
    """Membership check across all retrieval turns recorded so far."""
    by_turn = getattr(ledger, "by_turn", None)
    if not isinstance(by_turn, dict):
        return False
    for entries in by_turn.values():
        for entry in entries:
            if getattr(entry, "doc_id", None) == doc_id:
                return True
    return False


def _stop_to_dict(stop: PlannedStop, *, index: int) -> dict[str, Any]:
    """Serialize one stop to the locked output schema (no `leg_distance_m`)."""
    return {
        "index": index,
        "doc_id": stop.doc_id,
        "name": stop.name,
        "lat": stop.lat,
        "lon": stop.lon,
    }


def _step_to_dict(step: Any) -> dict[str, Any]:
    """Convert a `Step` dataclass (or dict) to the wire shape."""
    out: dict[str, Any] = {
        "instruction": getattr(step, "instruction", None) or step.get("instruction"),
        "distance_m": getattr(step, "distance_m", None)
        if hasattr(step, "distance_m")
        else step.get("distance_m"),
        "duration_s": getattr(step, "duration_s", None)
        if hasattr(step, "duration_s")
        else step.get("duration_s"),
        "maneuver_type": getattr(step, "maneuver_type", None)
        if hasattr(step, "maneuver_type")
        else step.get("maneuver_type"),
    }
    geometry = (
        getattr(step, "geometry", None)
        if hasattr(step, "geometry")
        else step.get("geometry")
    )
    if geometry is not None:
        out["geometry"] = geometry
    return out


def _leg_to_dict(leg: Any) -> dict[str, Any]:
    """Convert a `Leg` dataclass to the wire shape."""
    steps_raw = getattr(leg, "steps", None) or []
    return {
        "from_index": leg.from_index,
        "to_index": leg.to_index,
        "distance_m": leg.distance_m,
        "duration_s": leg.duration_s,
        "geometry": leg.geometry,
        "steps": [_step_to_dict(s) for s in steps_raw],
    }


def _route_result_to_dict(
    result: Any,
    *,
    stops_payload: list[dict[str, Any]],
) -> dict[str, Any]:
    """Bundle a `RouteResult` + ordered stops into the JSON-serializable dict."""
    return {
        "stops": stops_payload,
        "legs": [_leg_to_dict(leg) for leg in result.legs],
        "geometry": result.geometry,
        "total_distance_m": result.total_distance_m,
        "total_duration_s": result.total_duration_s,
        "routing_backend": result.routing_backend,
        "stop_ordering": result.stop_ordering,
    }


def _reorder_stops_by_legs(
    stops: list[PlannedStop],
    legs: list[Any],
) -> list[PlannedStop]:
    """Reorder `stops` (in input order) into the executed visit order.

    For `/route` the executed order equals input order — the legs go
    `0 → 1 → 2 → ...` and we return `stops` unchanged.

    For `/trip` (TSP-optimized) OSRM emits legs already in visit order;
    each leg's `from_index` / `to_index` is an INPUT index. So the
    visit order is `[legs[0].from_index, legs[0].to_index,
    legs[1].to_index, ...]`. We pull stops out in that sequence.
    """
    if not legs:
        return list(stops)
    visit_order: list[int] = [legs[0].from_index]
    for leg in legs:
        visit_order.append(leg.to_index)
    out: list[PlannedStop] = []
    for input_idx in visit_order:
        if 0 <= input_idx < len(stops):
            out.append(stops[input_idx])
    return out


async def _maybe_enrich_route(
    *,
    context: ToolExecutionContext,
    place_ids: list[str],
    initial_result: Any,
    stops_input_order: list[PlannedStop],
) -> tuple[Any, list[PlannedStop], list[dict[str, Any]]]:
    """Auto-discover POIs along the initial route and re-route through them.

    Returns `(result, stops, discovered)`. On any reason to skip
    (LLM hand-curated, haversine fallback, no candidates, re-route failed),
    returns the inputs unchanged with `discovered=[]` so the caller's
    output path is identical.
    """
    if (
        len(place_ids) > _AUTO_ENRICH_MAX_INPUT_STOPS
        or initial_result.routing_backend != "osrm"
    ):
        return initial_result, stops_input_order, []

    discovered = await discover_pois_along_route(
        session=context.session,
        route_geometry=initial_result.geometry,
        exclude_doc_ids=list(place_ids),
        radius_m=_ENRICH_RADIUS_M,
        limit=_ENRICH_LIMIT,
    )
    if not discovered:
        return initial_result, stops_input_order, []

    enriched_stops = _splice_discovered_stops(stops_input_order, discovered)
    enriched_coords = [(s.lat, s.lon) for s in enriched_stops]
    try:
        enriched_result = await context.routing_backend.route(
            enriched_coords, mode="walking"
        )
    except RoutingBackendError:
        # Re-route failed — keep the unenriched route rather than escalate.
        return initial_result, stops_input_order, []

    return enriched_result, enriched_stops, discovered


def _splice_discovered_stops(
    stops_input_order: list[PlannedStop],
    discovered: list[dict[str, Any]],
) -> list[PlannedStop]:
    """Splice discovered POIs (already in along-route order) between the
    first and last input stops. The endpoints stay pinned; OSRM's TSP
    on the re-route is free to permute the intermediates if a shorter
    permutation exists, but in practice along_t order is already close
    to optimal for routes through a corpus dense at the endpoints."""
    if len(stops_input_order) < _MIN_DISTINCT_STOPS or not discovered:
        return list(stops_input_order)
    head = stops_input_order[0]
    tail = stops_input_order[-1]
    middle_existing = list(stops_input_order[1:-1])
    middle_discovered = [
        PlannedStop(
            index=0,  # reassigned by _stop_to_dict at output time
            doc_id=poi["doc_id"],
            name=poi["name"],
            lat=float(poi["lat"]),
            lon=float(poi["lon"]),
            leg_distance_m=0.0,
        )
        for poi in discovered
    ]
    return [head, *middle_existing, *middle_discovered, tail]


def _discovered_to_dict(poi: dict[str, Any]) -> dict[str, Any]:
    """Project a `discover_pois_along_route` row into the wire shape we
    surface alongside the route. We drop `along_t` (internal bookkeeping)
    and keep the citation-shape provenance fields plus distance-to-route."""
    return {
        "doc_id": poi["doc_id"],
        "name": poi["name"],
        "source_type": poi["source_type"],
        "source_url": poi["source_url"],
        "lat": float(poi["lat"]),
        "lon": float(poi["lon"]),
        "dist_to_route_m": float(poi["dist_to_route_m"]),
    }


def _haversine_fallback_result(
    stops_in_order: list[PlannedStop],
    *,
    error: Exception,
) -> dict[str, Any]:
    """Build a `RouteResult`-shaped dict using straight-line haversine legs.

    Per `route-planning/spec.md` "Haversine fallback path":
      - `routing_backend == "haversine_fallback"`,
        `stop_ordering == "input_order"`.
      - Each leg has a 2-point GeoJSON LineString and exactly one step
        `"Head toward <name>"`.
      - The full-route geometry concatenates leg endpoints with seam
        dedup so adjacent legs don't double up the shared vertex.
      - Totals are sums of leg distances/durations; durations come from
        `WALK_M_PER_S`.
    """
    log = structlog.get_logger(__name__)
    log.warning("routing_backend_unavailable", error=str(error))

    if len(stops_in_order) < _MIN_DISTINCT_STOPS:
        # Defensive: caller guards against this, but make the function
        # safe to call with a degenerate input.
        return {
            "stops": [
                _stop_to_dict(stop, index=i) for i, stop in enumerate(stops_in_order)
            ],
            "legs": [],
            "geometry": {"type": "LineString", "coordinates": []},
            "total_distance_m": 0,
            "total_duration_s": 0,
            "routing_backend": "haversine_fallback",
            "stop_ordering": "input_order",
            "discovered_stops": [],
        }

    legs: list[dict[str, Any]] = []
    full_coords: list[list[float]] = []
    total_distance_m = 0
    total_duration_s = 0

    for i in range(len(stops_in_order) - 1):
        a = stops_in_order[i]
        b = stops_in_order[i + 1]
        distance_m = round(haversine_m(a.lat, a.lon, b.lat, b.lon))
        duration_s = round(distance_m / WALK_M_PER_S) if WALK_M_PER_S > 0 else 0

        geometry = {
            "type": "LineString",
            "coordinates": [[a.lon, a.lat], [b.lon, b.lat]],
        }
        steps = [
            {
                "instruction": f"Head toward {b.name}",
                "distance_m": distance_m,
                "duration_s": duration_s,
                "maneuver_type": "depart",
            }
        ]
        legs.append(
            {
                "from_index": i,
                "to_index": i + 1,
                "distance_m": distance_m,
                "duration_s": duration_s,
                "geometry": geometry,
                "steps": steps,
            }
        )
        # Concat with seam dedup
        if not full_coords:
            full_coords.append([a.lon, a.lat])
        full_coords.append([b.lon, b.lat])
        total_distance_m += distance_m
        total_duration_s += duration_s

    return {
        "stops": [
            _stop_to_dict(stop, index=i) for i, stop in enumerate(stops_in_order)
        ],
        "legs": legs,
        "geometry": {"type": "LineString", "coordinates": full_coords},
        "total_distance_m": total_distance_m,
        "total_duration_s": total_duration_s,
        "routing_backend": "haversine_fallback",
        "stop_ordering": "input_order",
        "discovered_stops": [],
    }


# ── Tool ───────────────────────────────────────────────────────────


class PlanWalkTool(Tool):
    """Plan a real walking route through 2-8 places the agent has retrieved."""

    name = "plan_walk"
    description = (
        "Plan a real walking route through the given places, in the order "
        "provided. When you pass 2-3 endpoints, the tool also auto-discovers "
        "interesting POIs along the path and adds them to the route as extra "
        "stops; the response's `discovered_stops[]` lists each one with full "
        "citation provenance (`doc_id`, `source_url`, `source_type`) so you "
        "can cite them in your narration. Call this ONLY when the user wants "
        "a tour, route, or directions across two or more places. Do NOT "
        "call for single-place or purely informational questions."
    )
    parameters = _PARAMETERS

    async def execute(
        self, args: dict[str, Any], context: ToolExecutionContext
    ) -> dict[str, Any]:
        # ── 1. Mode validation ────────────────────────────────────
        mode = args.get("mode", "walking")
        if mode not in _SUPPORTED_MODES:
            return {
                "error": "unsupported_mode",
                "message": (
                    f"plan_walk supports {sorted(_SUPPORTED_MODES)} only "
                    f"(got {mode!r})"
                ),
            }

        # ── 2. Dedup + minimum-distinct check ─────────────────────
        raw_ids = list(args.get("place_ids") or [])
        place_ids = _dedupe_keep_first(raw_ids)
        if len(place_ids) < _MIN_DISTINCT_STOPS:
            return {
                "error": "too_few_places",
                "message": "plan_walk requires at least 2 distinct place_ids",
            }

        # ── 3. Retrieval-ledger validation ────────────────────────
        if context.retrieval_ledger is None:
            raise RuntimeError(
                "plan_walk requires a retrieval_ledger on the "
                "ToolExecutionContext; got None"
            )
        for pid in place_ids:
            if not _is_known_to_ledger(context.retrieval_ledger, pid):
                return {
                    "error": "unknown_place_id",
                    "place_id": pid,
                    "message": "doc_id not in retrieval ledger",
                }

        # ── 4. Coordinate lookup (re-uses today's DB helper) ──────
        if context.session is None:
            raise RuntimeError(
                "plan_walk requires a DB session on the ToolExecutionContext; "
                "got None"
            )
        stops_db = await plan_walk_db(session=context.session, place_ids=place_ids)
        # `plan_walk_db` may drop place_ids that don't exist in `places` table.
        resolved_ids = {s.doc_id for s in stops_db}
        for pid in place_ids:
            if pid not in resolved_ids:
                return {
                    "error": "unknown_place_id",
                    "place_id": pid,
                    "message": "doc_id not in retrieval ledger",
                }
        # Re-order DB stops back into the LLM's input order — `plan_walk_db`
        # already preserves order, but be explicit so a future helper change
        # can't silently change the contract.
        stops_by_id = {s.doc_id: s for s in stops_db}
        stops_input_order = [stops_by_id[pid] for pid in place_ids]

        # ── 5. Routing-backend dispatch (with haversine fallback) ─
        if context.routing_backend is None:
            raise RuntimeError(
                "plan_walk requires a routing_backend on the "
                "ToolExecutionContext; got None"
            )
        coords = [(s.lat, s.lon) for s in stops_input_order]
        try:
            result = await context.routing_backend.route(coords, mode="walking")
        except RoutingBackendError as exc:
            return _haversine_fallback_result(stops_input_order, error=exc)

        # ── 6. Auto-enrich with along-route POIs (default behaviour) ─
        result, stops_input_order, discovered = await _maybe_enrich_route(
            context=context,
            place_ids=place_ids,
            initial_result=result,
            stops_input_order=stops_input_order,
        )

        # ── 7. Reorder stops to executed visit order ──────────────
        if result.stop_ordering == "tsp_optimized":
            stops_executed = _reorder_stops_by_legs(stops_input_order, result.legs)
        else:
            stops_executed = list(stops_input_order)

        stops_payload = [
            _stop_to_dict(stop, index=i) for i, stop in enumerate(stops_executed)
        ]
        out = _route_result_to_dict(result, stops_payload=stops_payload)
        out["discovered_stops"] = [
            _discovered_to_dict(poi) for poi in discovered
        ]
        return out
