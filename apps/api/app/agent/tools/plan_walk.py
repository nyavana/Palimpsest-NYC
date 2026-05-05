"""`plan_walk` — the second LLM-callable tool in V1.

The LLM picks `place_ids` (returned by prior `search_places` calls) and
this tool turns them into a real walking route via the
`RoutingBackend` injected on the `ToolExecutionContext`. The tool is the
single seam between the LLM's narrative ordering and the OSM-backed
routing engine; it never enters new `doc_id`s into the citation pool —
it only routes through ones the agent has already retrieved.

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
    exception.

The tool's return value is a JSON-serializable dict whose keys mirror
the `RouteResult` dataclass; the SSE handler will eventually emit it
as the `walk` frame byte-for-byte.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.agent.tools.base import Tool, ToolExecutionContext
from app.agent.walk import PlannedStop, haversine_m
from app.agent.walk import plan_walk as plan_walk_db
from app.routing import RoutingBackendError

# ── Constants ──────────────────────────────────────────────────────

# Comfortable walking pace (~5 km/h) used to synthesize fallback durations.
WALK_M_PER_S = 1.4

# Minimum distinct stops required for a "route" — anything less is just a
# marker, which the citation-driven map already shows. Mirrors the JSON
# Schema `minItems=2` on `place_ids`.
_MIN_DISTINCT_STOPS = 2

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
    }


# ── Tool ───────────────────────────────────────────────────────────


class PlanWalkTool(Tool):
    """Plan a real walking route through 2-8 places the agent has retrieved."""

    name = "plan_walk"
    description = (
        "Plan a real walking route through the given places, in the order "
        "provided. Call this ONLY when the user wants a tour, route, or "
        "directions across two or more places. Do NOT call for single-place "
        "or purely informational questions."
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

        # ── 6. Reorder stops to executed visit order ──────────────
        if result.stop_ordering == "tsp_optimized":
            stops_executed = _reorder_stops_by_legs(stops_input_order, result.legs)
        else:
            stops_executed = list(stops_input_order)

        stops_payload = [
            _stop_to_dict(stop, index=i) for i, stop in enumerate(stops_executed)
        ]
        return _route_result_to_dict(result, stops_payload=stops_payload)
