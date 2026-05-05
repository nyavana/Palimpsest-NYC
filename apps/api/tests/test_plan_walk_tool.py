"""`plan_walk` tool tests.

Covers the locked V1 contract from
`openspec/changes/agent-route-planning/specs/agent-tools/spec.md`
(plan_walk tool input/output contracts) and
`openspec/changes/agent-route-planning/specs/route-planning/spec.md`
(haversine fallback path).

The DB-backed coordinate lookup `app.agent.walk.plan_walk` is monkey-
patched to a synchronous fake in each test so the suite runs without
postgres. The routing backend is a small in-test fake that returns
fixture `RouteResult`s shaped exactly like `OsrmBackend` would emit.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.agent.citations import RetrievalLedger
from app.agent.tools.base import ToolExecutionContext
from app.agent.tools.plan_walk import PlanWalkTool
from app.agent.walk import PlannedStop
from app.routing import Leg, RouteResult, RoutingBackendError, Step
from app.routing.types import GeoJSONLineString

# ── Test fixtures ──────────────────────────────────────────────────


_PLACES = {
    "wikipedia:A": ("Cathedral of St. John the Divine", 40.8038, -73.9619),
    "wikipedia:B": ("Riverside Church", 40.8108, -73.9626),
    "wikipedia:C": ("Columbia University", 40.8075, -73.9626),
    "wikipedia:D": ("Grant's Tomb", 40.8133, -73.9627),
}


def _ledger_with(*doc_ids: str) -> RetrievalLedger:
    """Build a `RetrievalLedger` populated on turn 1 with the given doc_ids."""
    ledger = RetrievalLedger()
    hits = [
        {
            "doc_id": pid,
            "name": _PLACES[pid][0],
            "source_type": "wikipedia",
            "source_url": f"https://en.wikipedia.org/wiki/{pid.split(':', 1)[1]}",
        }
        for pid in doc_ids
    ]
    ledger.add(turn=1, hits=hits)
    return ledger


def _planned_stops(place_ids: list[str]) -> list[PlannedStop]:
    """Build the list `app.agent.walk.plan_walk` would emit for these IDs."""
    out: list[PlannedStop] = []
    for i, pid in enumerate(place_ids):
        if pid not in _PLACES:
            continue
        name, lat, lon = _PLACES[pid]
        out.append(
            PlannedStop(
                index=i,
                doc_id=pid,
                name=name,
                lat=lat,
                lon=lon,
                leg_distance_m=0.0,  # not consumed by the tool
            )
        )
    return out


def _patch_db_helper(
    monkeypatch: pytest.MonkeyPatch,
    *,
    discovered: list[dict[str, Any]] | None = None,
) -> None:
    """Stub out the DB-backed `plan_walk` and `discover_pois_along_route`.

    By default, `discover_pois_along_route` returns `[]` so the existing
    no-enrichment behaviour is preserved for tests that don't care about
    the auto-discovery branch. Pass `discovered=[...]` to exercise the
    enrichment path with a deterministic POI list.
    """

    async def fake_plan(
        *, session: Any, place_ids: list[str]
    ) -> list[PlannedStop]:
        del session  # unused; matches the real helper's keyword-only signature
        return _planned_stops(place_ids)

    monkeypatch.setattr("app.agent.tools.plan_walk.plan_walk_db", fake_plan)

    discovered_payload = list(discovered or [])

    async def fake_discover(
        *,
        session: Any,
        route_geometry: dict[str, Any],
        exclude_doc_ids: list[str],
        radius_m: int = 150,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        del session, route_geometry, exclude_doc_ids, radius_m, limit
        return list(discovered_payload)

    monkeypatch.setattr(
        "app.agent.tools.plan_walk.discover_pois_along_route", fake_discover
    )


def _line(coords: list[list[float]]) -> GeoJSONLineString:
    return {"type": "LineString", "coordinates": coords}


def _step(
    *, instruction: str, distance_m: int = 100, duration_s: int = 70
) -> Step:
    return Step(
        instruction=instruction,
        distance_m=distance_m,
        duration_s=duration_s,
        maneuver_type="depart",
        geometry=None,
    )


def _leg(
    *, from_index: int, to_index: int, distance_m: int = 100, duration_s: int = 70
) -> Leg:
    return Leg(
        from_index=from_index,
        to_index=to_index,
        distance_m=distance_m,
        duration_s=duration_s,
        geometry=_line([[-73.96, 40.80], [-73.961, 40.801]]),
        steps=[_step(instruction="Head east", distance_m=distance_m, duration_s=duration_s)],
    )


class _FakeRoutingBackend:
    """In-test stand-in for `OsrmBackend`.

    Returns `result` repeatedly, OR consumes from `results` in order on
    each successive call (used to drive the enrichment re-route path).
    """

    def __init__(
        self,
        result: RouteResult | None = None,
        *,
        results: list[RouteResult] | None = None,
        raise_exc: Exception | None = None,
    ) -> None:
        self._result = result
        self._results = list(results) if results is not None else None
        self._raise = raise_exc
        self.calls: list[tuple[list[tuple[float, float]], str]] = []

    async def route(
        self,
        stops: list[tuple[float, float]],
        mode: str = "walking",
    ) -> RouteResult:
        self.calls.append((list(stops), mode))
        if self._raise is not None:
            raise self._raise
        if self._results is not None:
            if not self._results:
                raise AssertionError("_FakeRoutingBackend exhausted scripted results")
            return self._results.pop(0)
        assert self._result is not None
        return self._result


# ── Tool definition shape ──────────────────────────────────────────


def test_tool_definition_metadata():
    tool = PlanWalkTool()
    definition = tool.definition()
    assert definition.name == "plan_walk"
    assert "tour" in definition.description.lower() or "route" in definition.description.lower()
    assert definition.parameters["type"] == "object"
    assert "place_ids" in definition.parameters["required"]


def test_tool_parameter_bounds_are_locked():
    """minItems=2, maxItems=8 per design.md §4."""
    tool = PlanWalkTool()
    schema = tool.parameters
    pids = schema["properties"]["place_ids"]
    assert pids["minItems"] == 2
    assert pids["maxItems"] == 8
    assert pids["items"] == {"type": "string"}
    mode = schema["properties"]["mode"]
    assert mode["enum"] == ["walking"]
    assert mode["default"] == "walking"


# ── Success: 2-stop input_order ────────────────────────────────────


async def test_two_stop_success_input_order(monkeypatch: pytest.MonkeyPatch):
    _patch_db_helper(monkeypatch)
    fake_result = RouteResult(
        geometry=_line(
            [[-73.9619, 40.8038], [-73.9620, 40.8050], [-73.9626, 40.8108]]
        ),
        total_distance_m=412,
        total_duration_s=295,
        legs=[_leg(from_index=0, to_index=1, distance_m=412, duration_s=295)],
        routing_backend="osrm",
        stop_ordering="input_order",
    )
    backend = _FakeRoutingBackend(result=fake_result)
    ctx = ToolExecutionContext(
        session=object(),  # placeholder, not used
        routing_backend=backend,
        retrieval_ledger=_ledger_with("wikipedia:A", "wikipedia:B"),
    )

    out = await PlanWalkTool().run(
        {"place_ids": ["wikipedia:A", "wikipedia:B"]}, ctx
    )

    # Match design.md §4 wire shape exactly.
    assert out["routing_backend"] == "osrm"
    assert out["stop_ordering"] == "input_order"
    assert len(out["stops"]) == 2
    assert [s["doc_id"] for s in out["stops"]] == ["wikipedia:A", "wikipedia:B"]
    assert [s["index"] for s in out["stops"]] == [0, 1]
    # Stop has no leg_distance_m (replaced by legs[])
    assert "leg_distance_m" not in out["stops"][0]
    # Each stop has the locked fields only.
    for s in out["stops"]:
        assert set(s.keys()) == {"index", "doc_id", "name", "lat", "lon"}
    assert len(out["legs"]) == 1
    assert out["legs"][0]["from_index"] == 0
    assert out["legs"][0]["to_index"] == 1
    # Leg coords passed through without re-encoding.
    assert out["legs"][0]["geometry"]["type"] == "LineString"
    assert out["geometry"]["type"] == "LineString"
    assert out["total_distance_m"] == 412
    assert out["total_duration_s"] == 295
    # Coordinates passed in (lat, lon) tuples in input order
    assert backend.calls[0][0] == [(40.8038, -73.9619), (40.8108, -73.9626)]
    assert backend.calls[0][1] == "walking"


# ── Success: 4-stop tsp_optimized with permuted leg order ──────────


async def test_four_stop_success_tsp_reorders_stops(monkeypatch: pytest.MonkeyPatch):
    """Input [A, B, C, D]; OSRM-optimized visit is [A, C, B, D].

    Per the agent-tools "plan_walk tool output contract":
      - `stops[]` MUST reflect the executed (permuted) order.
      - `legs[]` MUST follow OSRM's optimized sequence with `from_index`/
        `to_index` referring to INPUT positions.
    """
    _patch_db_helper(monkeypatch)
    fake_result = RouteResult(
        geometry=_line([[0.0, 0.0], [1.0, 1.0]]),
        total_distance_m=1245,
        total_duration_s=890,
        # Optimized visit order [A, C, B, D] → input indices [0, 2, 1, 3].
        legs=[
            _leg(from_index=0, to_index=2, distance_m=300, duration_s=200),  # A → C
            _leg(from_index=2, to_index=1, distance_m=400, duration_s=290),  # C → B
            _leg(from_index=1, to_index=3, distance_m=545, duration_s=400),  # B → D
        ],
        routing_backend="osrm",
        stop_ordering="tsp_optimized",
    )
    backend = _FakeRoutingBackend(result=fake_result)
    ctx = ToolExecutionContext(
        session=object(),
        routing_backend=backend,
        retrieval_ledger=_ledger_with(
            "wikipedia:A", "wikipedia:B", "wikipedia:C", "wikipedia:D"
        ),
    )

    out = await PlanWalkTool().run(
        {
            "place_ids": [
                "wikipedia:A",
                "wikipedia:B",
                "wikipedia:C",
                "wikipedia:D",
            ]
        },
        ctx,
    )

    assert out["stop_ordering"] == "tsp_optimized"
    # Stops are reordered to A → C → B → D.
    doc_order = [s["doc_id"] for s in out["stops"]]
    assert doc_order == [
        "wikipedia:A",
        "wikipedia:C",
        "wikipedia:B",
        "wikipedia:D",
    ]
    # Indexes are 0..3 along the executed order (not the input order).
    assert [s["index"] for s in out["stops"]] == [0, 1, 2, 3]
    # Legs preserve OSRM's INPUT-index labeling.
    assert [(leg["from_index"], leg["to_index"]) for leg in out["legs"]] == [
        (0, 2),
        (2, 1),
        (1, 3),
    ]
    # Backend was called with INPUT-order coordinates (the routing engine
    # decides the visit order; the tool just feeds it the stops in input
    # order so OSRM can pin first/last via source=first&destination=last).
    expected_input_coords = [
        (_PLACES[pid][1], _PLACES[pid][2])
        for pid in ["wikipedia:A", "wikipedia:B", "wikipedia:C", "wikipedia:D"]
    ]
    assert backend.calls[0][0] == expected_input_coords


# ── Validation errors ──────────────────────────────────────────────


async def test_unknown_place_id_returns_error_envelope(monkeypatch: pytest.MonkeyPatch):
    _patch_db_helper(monkeypatch)
    backend = _FakeRoutingBackend(
        result=RouteResult(
            geometry=_line([[0.0, 0.0]]),
            total_distance_m=0,
            total_duration_s=0,
            legs=[],
            routing_backend="osrm",
            stop_ordering="input_order",
        )
    )
    ctx = ToolExecutionContext(
        session=object(),
        routing_backend=backend,
        retrieval_ledger=_ledger_with("wikipedia:A"),
    )
    out = await PlanWalkTool().run(
        {"place_ids": ["wikipedia:A", "wikipedia:GHOST"]}, ctx
    )
    assert out == {
        "error": "unknown_place_id",
        "place_id": "wikipedia:GHOST",
        "message": "doc_id not in retrieval ledger",
    }
    # No routing call should have been issued.
    assert backend.calls == []


async def test_too_few_places_after_dedup_returns_error_envelope(
    monkeypatch: pytest.MonkeyPatch,
):
    """`["X", "X"]` dedupes to a single distinct id and MUST be rejected."""
    _patch_db_helper(monkeypatch)
    backend = _FakeRoutingBackend(
        result=RouteResult(
            geometry=_line([[0.0, 0.0]]),
            total_distance_m=0,
            total_duration_s=0,
            legs=[],
            routing_backend="osrm",
            stop_ordering="input_order",
        )
    )
    ctx = ToolExecutionContext(
        session=object(),
        routing_backend=backend,
        retrieval_ledger=_ledger_with("wikipedia:A"),
    )
    out = await PlanWalkTool().run(
        {"place_ids": ["wikipedia:A", "wikipedia:A"]}, ctx
    )
    assert out["error"] == "too_few_places"
    assert "at least 2 distinct" in out["message"]
    assert backend.calls == []


async def test_unsupported_mode_returns_error_envelope(
    monkeypatch: pytest.MonkeyPatch,
):
    """JSON-Schema validation rejects `mode='driving'` before execute() runs.

    The tool's enum locks the LLM to `walking`; the JSON-Schema layer
    surfaces this as `ToolArgError`, and the agent loop already wraps
    that as a `bad_args` envelope so the LLM can recover. The "structured
    error envelope" property holds either way — the test asserts the
    behaviour the LLM actually sees.
    """
    _patch_db_helper(monkeypatch)
    backend = _FakeRoutingBackend(
        result=RouteResult(
            geometry=_line([[0.0, 0.0]]),
            total_distance_m=0,
            total_duration_s=0,
            legs=[],
            routing_backend="osrm",
            stop_ordering="input_order",
        )
    )
    ctx = ToolExecutionContext(
        session=object(),
        routing_backend=backend,
        retrieval_ledger=_ledger_with("wikipedia:A", "wikipedia:B"),
    )
    # We bypass the JSON-Schema layer to exercise the in-tool guard,
    # because the schema's `enum: ["walking"]` would otherwise reject
    # `driving` at validate() time. Calling execute() directly is the
    # only way to hit the unsupported_mode envelope.
    out = await PlanWalkTool().execute(
        {"place_ids": ["wikipedia:A", "wikipedia:B"], "mode": "driving"}, ctx
    )
    assert out["error"] == "unsupported_mode"
    assert "walking" in out["message"]
    assert backend.calls == []


# ── Haversine fallback ────────────────────────────────────────────


async def test_osrm_down_falls_back_to_haversine(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    """OSRM unreachable → tool returns a structurally-identical haversine result.

    Spec assertions (route-planning "Haversine fallback path"):
      - `routing_backend == "haversine_fallback"`,
        `stop_ordering == "input_order"`.
      - Each leg geometry is a 2-point LineString.
      - A structured warning record `{"event": "routing_backend_unavailable"}`
        is emitted before the fallback is built.
    """
    _patch_db_helper(monkeypatch)

    captured: list[dict[str, Any]] = []

    class _RecordingLogger:
        def warning(self, event: str, **kwargs: Any) -> None:
            captured.append({"event": event, **kwargs})

    # Monkey-patch the structlog factory used inside the fallback so the
    # warning is intercepted regardless of stdlib log configuration.
    def _factory(*args: Any, **kwargs: Any) -> _RecordingLogger:
        del args, kwargs  # signature-compatible with structlog.get_logger
        return _RecordingLogger()

    monkeypatch.setattr(
        "app.agent.tools.plan_walk.structlog.get_logger", _factory
    )

    backend = _FakeRoutingBackend(
        raise_exc=RoutingBackendError("connection_error", "connection refused")
    )
    ctx = ToolExecutionContext(
        session=object(),
        routing_backend=backend,
        retrieval_ledger=_ledger_with(
            "wikipedia:A", "wikipedia:B", "wikipedia:C"
        ),
    )

    out = await PlanWalkTool().run(
        {
            "place_ids": [
                "wikipedia:A",
                "wikipedia:B",
                "wikipedia:C",
            ]
        },
        ctx,
    )

    assert out["routing_backend"] == "haversine_fallback"
    assert out["stop_ordering"] == "input_order"
    # 3 stops → 2 legs.
    assert len(out["stops"]) == 3
    assert [s["doc_id"] for s in out["stops"]] == [
        "wikipedia:A",
        "wikipedia:B",
        "wikipedia:C",
    ]
    assert len(out["legs"]) == 2
    for leg in out["legs"]:
        assert leg["geometry"]["type"] == "LineString"
        # Two-point LineString — straight segment between the two endpoints.
        assert len(leg["geometry"]["coordinates"]) == 2
        # Each fallback leg has exactly one synthetic step.
        assert len(leg["steps"]) == 1
        assert leg["steps"][0]["maneuver_type"] == "depart"
        assert leg["steps"][0]["instruction"].startswith("Head toward ")
    # Full geometry concatenates leg endpoints with seam dedup; for 3 stops
    # we expect exactly 3 vertices (one per stop).
    assert len(out["geometry"]["coordinates"]) == 3
    # Totals are positive — distances were computed from real coordinates.
    assert out["total_distance_m"] > 0
    assert out["total_duration_s"] > 0
    # Structured warning was logged before the fallback was built.
    assert any(
        rec["event"] == "routing_backend_unavailable"
        and "connection_error" in rec.get("error", "")
        for rec in captured
    )


# ── Auto-enrichment of A→B routes with along-route POIs ───────────


def _initial_two_stop_result() -> RouteResult:
    return RouteResult(
        geometry=_line(
            [
                [-73.9619, 40.8038],
                [-73.9622, 40.8070],
                [-73.9626, 40.8108],
            ]
        ),
        total_distance_m=900,
        total_duration_s=640,
        legs=[_leg(from_index=0, to_index=1, distance_m=900, duration_s=640)],
        routing_backend="osrm",
        stop_ordering="input_order",
    )


def _enriched_three_stop_tsp_result() -> RouteResult:
    return RouteResult(
        geometry=_line(
            [
                [-73.9619, 40.8038],
                [-73.9626, 40.8075],
                [-73.9626, 40.8108],
            ]
        ),
        total_distance_m=950,
        total_duration_s=680,
        legs=[
            _leg(from_index=0, to_index=1, distance_m=420, duration_s=300),
            _leg(from_index=1, to_index=2, distance_m=530, duration_s=380),
        ],
        routing_backend="osrm",
        stop_ordering="tsp_optimized",
    )


async def test_two_stop_route_auto_enriches_with_along_route_pois(
    monkeypatch: pytest.MonkeyPatch,
):
    """A→B with one nearby POI returns 3 stops + a populated discovered_stops."""
    discovered = [
        {
            "doc_id": "wikipedia:C",
            "name": "Columbia University",
            "source_type": "wikipedia",
            "source_url": "https://en.wikipedia.org/wiki/Columbia_University",
            "lat": 40.8075,
            "lon": -73.9626,
            "dist_to_route_m": 18.0,
            "along_t": 0.55,
        }
    ]
    _patch_db_helper(monkeypatch, discovered=discovered)
    backend = _FakeRoutingBackend(
        results=[_initial_two_stop_result(), _enriched_three_stop_tsp_result()]
    )
    ctx = ToolExecutionContext(
        session=object(),
        routing_backend=backend,
        retrieval_ledger=_ledger_with("wikipedia:A", "wikipedia:B"),
    )

    out = await PlanWalkTool().run(
        {"place_ids": ["wikipedia:A", "wikipedia:B"]}, ctx
    )

    assert "error" not in out
    assert len(out["stops"]) == 3
    assert [s["doc_id"] for s in out["stops"]] == [
        "wikipedia:A",
        "wikipedia:C",
        "wikipedia:B",
    ]
    assert out["discovered_stops"] == [
        {
            "doc_id": "wikipedia:C",
            "name": "Columbia University",
            "source_type": "wikipedia",
            "source_url": "https://en.wikipedia.org/wiki/Columbia_University",
            "lat": 40.8075,
            "lon": -73.9626,
            "dist_to_route_m": 18.0,
        }
    ]
    # Two routing calls: the A→B probe, then the enriched 3-stop re-route.
    assert len(backend.calls) == 2
    assert backend.calls[0][0] == [(40.8038, -73.9619), (40.8108, -73.9626)]
    assert backend.calls[1][0] == [
        (40.8038, -73.9619),
        (40.8075, -73.9626),
        (40.8108, -73.9626),
    ]


async def test_two_stop_route_with_no_nearby_pois_returns_unenriched(
    monkeypatch: pytest.MonkeyPatch,
):
    """Empty discovered list ⇒ original 2-stop route, single routing call."""
    _patch_db_helper(monkeypatch, discovered=[])
    backend = _FakeRoutingBackend(result=_initial_two_stop_result())
    ctx = ToolExecutionContext(
        session=object(),
        routing_backend=backend,
        retrieval_ledger=_ledger_with("wikipedia:A", "wikipedia:B"),
    )

    out = await PlanWalkTool().run(
        {"place_ids": ["wikipedia:A", "wikipedia:B"]}, ctx
    )

    assert [s["doc_id"] for s in out["stops"]] == ["wikipedia:A", "wikipedia:B"]
    assert out["discovered_stops"] == []
    assert len(backend.calls) == 1


async def test_four_stop_input_skips_enrichment(monkeypatch: pytest.MonkeyPatch):
    """LLM hand-curated 4 stops ⇒ tool respects the curation, never enriches."""
    discovered = [
        {
            "doc_id": "wikipedia:Z",
            "name": "Z",
            "source_type": "wikipedia",
            "source_url": "https://en.wikipedia.org/wiki/Z",
            "lat": 40.81,
            "lon": -73.96,
            "dist_to_route_m": 5.0,
            "along_t": 0.5,
        }
    ]
    _patch_db_helper(monkeypatch, discovered=discovered)
    fake_result = RouteResult(
        geometry=_line([[0.0, 0.0], [1.0, 1.0]]),
        total_distance_m=1245,
        total_duration_s=890,
        legs=[
            _leg(from_index=0, to_index=2, distance_m=300, duration_s=200),
            _leg(from_index=2, to_index=1, distance_m=400, duration_s=290),
            _leg(from_index=1, to_index=3, distance_m=545, duration_s=400),
        ],
        routing_backend="osrm",
        stop_ordering="tsp_optimized",
    )
    backend = _FakeRoutingBackend(result=fake_result)
    ctx = ToolExecutionContext(
        session=object(),
        routing_backend=backend,
        retrieval_ledger=_ledger_with(
            "wikipedia:A", "wikipedia:B", "wikipedia:C", "wikipedia:D"
        ),
    )

    out = await PlanWalkTool().run(
        {
            "place_ids": [
                "wikipedia:A",
                "wikipedia:B",
                "wikipedia:C",
                "wikipedia:D",
            ]
        },
        ctx,
    )

    assert out["discovered_stops"] == []
    assert len(out["stops"]) == 4
    assert len(backend.calls) == 1


async def test_haversine_fallback_skips_enrichment(monkeypatch: pytest.MonkeyPatch):
    """When OSRM is unreachable the tool returns the haversine route untouched
    — no buffer query, no second routing call, `discovered_stops == []`."""
    discovered = [
        {
            "doc_id": "wikipedia:C",
            "name": "Columbia",
            "source_type": "wikipedia",
            "source_url": "https://en.wikipedia.org/wiki/Columbia_University",
            "lat": 40.8075,
            "lon": -73.9626,
            "dist_to_route_m": 18.0,
            "along_t": 0.5,
        }
    ]
    _patch_db_helper(monkeypatch, discovered=discovered)
    backend = _FakeRoutingBackend(
        raise_exc=RoutingBackendError("connection_error", "connection refused")
    )
    ctx = ToolExecutionContext(
        session=object(),
        routing_backend=backend,
        retrieval_ledger=_ledger_with("wikipedia:A", "wikipedia:B"),
    )

    out = await PlanWalkTool().run(
        {"place_ids": ["wikipedia:A", "wikipedia:B"]}, ctx
    )

    assert out["routing_backend"] == "haversine_fallback"
    assert out["discovered_stops"] == []
    # Only the initial routing attempt happened; no re-route.
    assert len(backend.calls) == 1


async def test_enrichment_re_route_failure_falls_back_to_initial_route(
    monkeypatch: pytest.MonkeyPatch,
):
    """Initial OSRM call succeeds, discovery returns POIs, but the re-route
    fails. Tool returns the original 2-stop OSRM route with no enrichment
    rather than escalating the failure."""
    discovered = [
        {
            "doc_id": "wikipedia:C",
            "name": "Columbia",
            "source_type": "wikipedia",
            "source_url": "https://en.wikipedia.org/wiki/Columbia_University",
            "lat": 40.8075,
            "lon": -73.9626,
            "dist_to_route_m": 18.0,
            "along_t": 0.5,
        }
    ]
    _patch_db_helper(monkeypatch, discovered=discovered)

    # First call returns the initial 2-stop OSRM result; second raises.
    initial = _initial_two_stop_result()
    call_count = {"n": 0}

    class _FlakyBackend:
        def __init__(self) -> None:
            self.calls: list[tuple[list[tuple[float, float]], str]] = []

        async def route(self, stops, mode="walking"):
            self.calls.append((list(stops), mode))
            call_count["n"] += 1
            if call_count["n"] == 1:
                return initial
            raise RoutingBackendError("NoRoute", "re-route failed")

    backend = _FlakyBackend()
    ctx = ToolExecutionContext(
        session=object(),
        routing_backend=backend,
        retrieval_ledger=_ledger_with("wikipedia:A", "wikipedia:B"),
    )

    out = await PlanWalkTool().run(
        {"place_ids": ["wikipedia:A", "wikipedia:B"]}, ctx
    )

    assert out["routing_backend"] == "osrm"
    assert [s["doc_id"] for s in out["stops"]] == ["wikipedia:A", "wikipedia:B"]
    assert out["discovered_stops"] == []
    assert call_count["n"] == 2
