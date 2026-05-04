"""OSRM HTTP backend tests.

Uses `respx` (pinned in `[project.optional-dependencies] dev`) to
intercept httpx requests so the suite runs offline. Tests cover:

  - 2-stop dispatch hits `/route/v1/foot/...`, returns `input_order`.
  - 4-stop dispatch hits `/trip/v1/foot/...`, returns `tsp_optimized`,
    and reorders legs by `waypoints[].waypoint_index`.
  - 9-stop call raises ValueError before any HTTP request.
  - `mode="driving"` raises ValueError before any HTTP request.
  - OSRM `code="NoRoute"` surfaces as `RoutingBackendError("NoRoute", ...)`.
  - Single HTTP request per call, even for `/trip` with multiple legs.
  - The `radiuses` query parameter has exactly N entries.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
import pytest
import respx
from app.routing import OsrmBackend, RoutingBackendError

_BASE_URL = "http://osrm.test"


# ── fixture builders ───────────────────────────────────────────────


def _make_geometry(coords: list[list[float]]) -> dict[str, Any]:
    return {"type": "LineString", "coordinates": coords}


def _make_step(
    *,
    mtype: str,
    distance: float,
    duration: float,
    name: str = "Broadway",
    bearing_after: int = 90,
    modifier: str = "",
    geometry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "distance": distance,
        "duration": duration,
        "geometry": geometry or _make_geometry([[-73.96, 40.80], [-73.961, 40.801]]),
        "maneuver": {
            "type": mtype,
            "bearing_after": bearing_after,
            "modifier": modifier,
        },
    }


def _route_response_2_stop() -> dict[str, Any]:
    """OSRM `/route` response shape with one leg, two steps."""
    return {
        "code": "Ok",
        "routes": [
            {
                "distance": 412.0,
                "duration": 295.0,
                "geometry": _make_geometry(
                    [[-73.962, 40.804], [-73.961, 40.805], [-73.964, 40.811]]
                ),
                "legs": [
                    {
                        "distance": 412.0,
                        "duration": 295.0,
                        "steps": [
                            _make_step(
                                mtype="depart",
                                distance=80.0,
                                duration=60.0,
                                name="West 110th Street",
                                bearing_after=90,
                            ),
                            _make_step(
                                mtype="arrive",
                                distance=0.0,
                                duration=0.0,
                                name="Riverside Church",
                                bearing_after=0,
                            ),
                        ],
                    }
                ],
            }
        ],
        "waypoints": [
            {"location": [-73.962, 40.804]},
            {"location": [-73.964, 40.811]},
        ],
    }


def _trip_response_4_stop_permuted() -> dict[str, Any]:
    """OSRM `/trip` response shape for 4 input stops [A, B, C, D].

    OSRM optimizes the middle waypoints. We model the case where the
    optimal visit order is [A, C, B, D]. Per the OSRM `/trip` contract,
    `waypoints[i].waypoint_index` is the optimized POSITION of the i-th
    INPUT waypoint:
      - input A (i=0) → visit position 0
      - input B (i=1) → visit position 2
      - input C (i=2) → visit position 1
      - input D (i=3) → visit position 3
    The 3 legs in `trip.legs` follow the optimized order:
      leg 0: A → C
      leg 1: C → B
      leg 2: B → D
    """
    return {
        "code": "Ok",
        "trips": [
            {
                "distance": 1245.0,
                "duration": 890.0,
                "geometry": _make_geometry(
                    [
                        [-73.962, 40.804],
                        [-73.961, 40.806],
                        [-73.960, 40.808],
                        [-73.964, 40.811],
                    ]
                ),
                "legs": [
                    # leg 0: A → C
                    {
                        "distance": 300.0,
                        "duration": 200.0,
                        "steps": [
                            _make_step(mtype="depart", distance=300.0, duration=200.0),
                            _make_step(mtype="arrive", distance=0.0, duration=0.0),
                        ],
                    },
                    # leg 1: C → B
                    {
                        "distance": 400.0,
                        "duration": 290.0,
                        "steps": [
                            _make_step(mtype="depart", distance=400.0, duration=290.0),
                            _make_step(mtype="arrive", distance=0.0, duration=0.0),
                        ],
                    },
                    # leg 2: B → D
                    {
                        "distance": 545.0,
                        "duration": 400.0,
                        "steps": [
                            _make_step(mtype="depart", distance=545.0, duration=400.0),
                            _make_step(mtype="arrive", distance=0.0, duration=0.0),
                        ],
                    },
                ],
            }
        ],
        "waypoints": [
            {"location": [-73.962, 40.804], "waypoint_index": 0},  # A → pos 0
            {"location": [-73.961, 40.806], "waypoint_index": 2},  # B → pos 2
            {"location": [-73.960, 40.808], "waypoint_index": 1},  # C → pos 1
            {"location": [-73.964, 40.811], "waypoint_index": 3},  # D → pos 3
        ],
    }


# ── 2-stop /route ──────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_two_stop_call_hits_route_endpoint_with_geojson():
    """Spec scenario: 2-stop call hits /route with input ordering preserved."""
    route_url = re.compile(rf"^{_BASE_URL}/route/v1/foot/")
    mock = respx.get(route_url).mock(
        return_value=httpx.Response(200, json=_route_response_2_stop())
    )

    backend = OsrmBackend(base_url=_BASE_URL)
    result = await backend.route([(40.804, -73.962), (40.811, -73.964)], mode="walking")

    assert mock.called
    assert mock.call_count == 1
    request = mock.calls[0].request
    # /route, not /trip
    assert "/route/v1/foot/" in str(request.url)
    assert "/trip/" not in str(request.url)
    # GeoJSON requested
    assert "geometries=geojson" in str(request.url)
    # radiuses=50;50 (exactly 2 entries)
    qp = request.url.params
    radiuses = qp.get("radiuses")
    assert radiuses == "50;50"
    # Coordinates: lon FIRST per OSRM convention.
    assert "-73.962,40.804;-73.964,40.811" in str(request.url)

    assert result.routing_backend == "osrm"
    assert result.stop_ordering == "input_order"
    assert result.geometry["type"] == "LineString"
    assert len(result.geometry["coordinates"]) > 0
    assert len(result.legs) == 1
    assert result.legs[0].from_index == 0
    assert result.legs[0].to_index == 1


@pytest.mark.asyncio
@respx.mock
async def test_two_stop_geometry_is_passed_through_unchanged():
    """The api MUST forward OSRM's GeoJSON geometry without re-encoding."""
    payload = _route_response_2_stop()
    expected_coords = payload["routes"][0]["geometry"]["coordinates"]

    respx.get(re.compile(rf"^{_BASE_URL}/route/v1/foot/")).mock(
        return_value=httpx.Response(200, json=payload)
    )
    backend = OsrmBackend(base_url=_BASE_URL)
    result = await backend.route([(40.804, -73.962), (40.811, -73.964)], mode="walking")
    assert result.geometry["coordinates"] == expected_coords


# ── 3-8 stop /trip ─────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_four_stop_call_hits_trip_endpoint_with_tsp_params():
    """Spec scenario: 4-stop call hits /trip with TSP optimization."""
    trip_url = re.compile(rf"^{_BASE_URL}/trip/v1/foot/")
    mock = respx.get(trip_url).mock(
        return_value=httpx.Response(200, json=_trip_response_4_stop_permuted())
    )

    backend = OsrmBackend(base_url=_BASE_URL)
    stops = [
        (40.804, -73.962),  # A
        (40.806, -73.961),  # B
        (40.808, -73.960),  # C
        (40.811, -73.964),  # D
    ]
    result = await backend.route(stops, mode="walking")

    assert mock.called
    assert mock.call_count == 1
    request = mock.calls[0].request
    qp = request.url.params
    assert qp.get("source") == "first"
    assert qp.get("destination") == "last"
    assert qp.get("roundtrip") == "false"
    assert qp.get("geometries") == "geojson"
    assert qp.get("radiuses") == "50;50;50;50"

    assert result.routing_backend == "osrm"
    assert result.stop_ordering == "tsp_optimized"

    # Optimized visit order is [A, C, B, D]:
    #   leg 0: A → C  → from=0, to=2
    #   leg 1: C → B  → from=2, to=1
    #   leg 2: B → D  → from=1, to=3
    assert len(result.legs) == 3
    assert (result.legs[0].from_index, result.legs[0].to_index) == (0, 2)
    assert (result.legs[1].from_index, result.legs[1].to_index) == (2, 1)
    assert (result.legs[2].from_index, result.legs[2].to_index) == (1, 3)
    # First and last input stops are pinned to first/last visit positions.
    assert result.legs[0].from_index == 0  # A is first
    assert result.legs[-1].to_index == 3  # D is last


@pytest.mark.asyncio
@respx.mock
async def test_four_stop_call_emits_single_http_request():
    """Spec scenario: single HTTP request per route call (no per-leg fan-out)."""
    mock = respx.get(re.compile(rf"^{_BASE_URL}/trip/v1/foot/")).mock(
        return_value=httpx.Response(200, json=_trip_response_4_stop_permuted())
    )
    backend = OsrmBackend(base_url=_BASE_URL)
    await backend.route(
        [
            (40.804, -73.962),
            (40.806, -73.961),
            (40.808, -73.960),
            (40.811, -73.964),
        ],
        mode="walking",
    )
    assert mock.call_count == 1


# ── stop count guards ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_nine_stop_call_raises_before_http():
    """Spec contract: ≤ 8 stops keeps OSRM in brute-force-optimal regime."""
    backend = OsrmBackend(base_url=_BASE_URL)
    stops = [(40.80 + i * 0.001, -73.96) for i in range(9)]
    with pytest.raises(ValueError, match="at most"):
        await backend.route(stops, mode="walking")


@pytest.mark.asyncio
async def test_one_stop_call_raises_before_http():
    backend = OsrmBackend(base_url=_BASE_URL)
    with pytest.raises(ValueError, match="at least"):
        await backend.route([(40.804, -73.962)], mode="walking")


# ── walking-only mode ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_driving_mode_raises_before_http():
    """Spec scenario: backend interface enforces walking-only mode in V1."""
    backend = OsrmBackend(base_url=_BASE_URL)
    with pytest.raises(ValueError, match="walking"):
        await backend.route(
            [(40.804, -73.962), (40.811, -73.964)],
            mode="driving",  # type: ignore[arg-type]
        )


# ── error mapping ─────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_no_route_status_raises_routing_backend_error():
    """Spec scenario: OSRM `code != "Ok"` surfaces as RoutingBackendError."""
    respx.get(re.compile(rf"^{_BASE_URL}/route/v1/foot/")).mock(
        return_value=httpx.Response(200, json={"code": "NoRoute", "message": "Impossible route"})
    )
    backend = OsrmBackend(base_url=_BASE_URL)
    with pytest.raises(RoutingBackendError) as exc_info:
        await backend.route([(40.804, -73.962), (40.811, -73.964)], mode="walking")
    assert exc_info.value.code == "NoRoute"
    assert "Impossible route" in exc_info.value.message


@pytest.mark.asyncio
@respx.mock
async def test_timeout_maps_to_routing_backend_error():
    respx.get(re.compile(rf"^{_BASE_URL}/route/v1/foot/")).mock(
        side_effect=httpx.TimeoutException("read timeout")
    )
    backend = OsrmBackend(base_url=_BASE_URL)
    with pytest.raises(RoutingBackendError) as exc_info:
        await backend.route([(40.804, -73.962), (40.811, -73.964)], mode="walking")
    assert exc_info.value.code == "timeout"


@pytest.mark.asyncio
@respx.mock
async def test_connection_error_maps_to_routing_backend_error():
    respx.get(re.compile(rf"^{_BASE_URL}/route/v1/foot/")).mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    backend = OsrmBackend(base_url=_BASE_URL)
    with pytest.raises(RoutingBackendError) as exc_info:
        await backend.route([(40.804, -73.962), (40.811, -73.964)], mode="walking")
    assert exc_info.value.code == "connection_error"


# ── radiuses parameter has exactly N entries ───────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_radiuses_param_has_n_entries_for_route():
    """Spec scenario: snap radius is set to 50 m per stop (2 entries)."""
    mock = respx.get(re.compile(rf"^{_BASE_URL}/route/v1/foot/")).mock(
        return_value=httpx.Response(200, json=_route_response_2_stop())
    )
    backend = OsrmBackend(base_url=_BASE_URL)
    await backend.route([(40.804, -73.962), (40.811, -73.964)], mode="walking")
    qp = mock.calls[0].request.url.params
    assert qp.get("radiuses") == "50;50"
    assert qp["radiuses"].count("50") == 2


@pytest.mark.asyncio
@respx.mock
async def test_radiuses_param_has_n_entries_for_trip():
    """Spec scenario: 50 m per stop, regardless of /route or /trip."""
    mock = respx.get(re.compile(rf"^{_BASE_URL}/trip/v1/foot/")).mock(
        return_value=httpx.Response(200, json=_trip_response_4_stop_permuted())
    )
    backend = OsrmBackend(base_url=_BASE_URL)
    await backend.route(
        [
            (40.804, -73.962),
            (40.806, -73.961),
            (40.808, -73.960),
            (40.811, -73.964),
        ],
        mode="walking",
    )
    qp = mock.calls[0].request.url.params
    assert qp.get("radiuses") == "50;50;50;50"
    assert qp["radiuses"].count("50") == 4
