## ADDED Requirements

### Requirement: Routing backend abstraction

The api SHALL provide a `RoutingBackend` interface with a single async method `route(stops: list[Coordinate], mode: Literal["walking"]) -> RouteResult` and exactly one V1 implementation, `OsrmBackend`, that targets an OSRM-compatible HTTP endpoint configured via the `OSRM_BASE_URL` env var. The interface MUST be backend-agnostic so a v2 swap to a hosted OSRM/ORS endpoint requires only an env-var change, not a code change.

`RouteResult` SHALL be a typed dataclass containing:

- `geometry: GeoJSONLineString` — full-route geometry as a GeoJSON LineString (`{"type": "LineString", "coordinates": [[lon, lat], ...]}`).
- `total_distance_m: int` — sum of leg distances in meters, rounded to integer.
- `total_duration_s: int` — sum of leg durations in seconds, rounded to integer.
- `legs: list[Leg]` — one entry per consecutive stop pair, in stop order.
- `routing_backend: Literal["osrm", "haversine_fallback"]` — telemetry tag.
- `stop_ordering: Literal["input_order", "tsp_optimized"]` — telemetry tag indicating whether the OSRM `/route` (input order) or `/trip` (TSP optimized) endpoint produced this result.

`Leg` SHALL contain `from_index`, `to_index`, `distance_m`, `duration_s`, `geometry` (GeoJSONLineString of this leg only), and `steps: list[Step]` (per-maneuver instructions). `Step` SHALL contain `instruction`, `distance_m`, `duration_s`, `maneuver_type`, and an optional `geometry` field.

The api MUST NOT carry encoded polyline strings as the wire format for route geometry. GeoJSON LineString is the V1 contract end-to-end (api → SSE → frontend → MapLibre `geojson` source).

#### Scenario: Default routing backend is OSRM
- **WHEN** the api lifespan completes startup with `OSRM_BASE_URL=http://osrm:5000`
- **THEN** `app.state.routing_backend` is an `OsrmBackend` instance whose `base_url` equals the configured value

#### Scenario: Routing backend is swappable via env var only
- **WHEN** `OSRM_BASE_URL` is set to a hosted OSRM endpoint (e.g., `https://routing.example.com`) and the api restarts
- **THEN** subsequent `plan_walk` tool calls reach the new endpoint with no application code changes

#### Scenario: Backend interface enforces walking-only mode in V1
- **WHEN** any caller invokes `RoutingBackend.route(stops, mode="driving")`
- **THEN** the call raises `ValueError("V1 only supports mode='walking'")` before any HTTP request

#### Scenario: RouteResult exposes geometry as GeoJSON LineString
- **WHEN** `OsrmBackend.route(...)` returns a `RouteResult` for a 2-stop walking query
- **THEN** `result.geometry["type"] == "LineString"` and `result.geometry["coordinates"]` is a non-empty list of `[lon, lat]` pairs

### Requirement: OSRM client endpoint selection

The `OsrmBackend` SHALL select between two OSRM endpoints based on stop count:

- **Exactly 2 stops** → GET `{OSRM_BASE_URL}/route/v1/foot/{lon0},{lat0};{lon1},{lat1}` with query params `steps=true&overview=full&geometries=geojson&annotations=duration,distance&radiuses=50;50`. The result SHALL set `stop_ordering="input_order"`.
- **3 to 8 stops** → GET `{OSRM_BASE_URL}/trip/v1/foot/{coords}` with query params `steps=true&overview=full&geometries=geojson&source=first&destination=last&roundtrip=false&radiuses=50;50;...`. The result SHALL set `stop_ordering="tsp_optimized"` and the emitted `RouteResult.legs` order MUST follow OSRM's `waypoints[].waypoint_index` permutation, not the input order. The first and last stops MUST remain in their input positions (pinned by `source=first&destination=last`); only intermediate stops are reordered.

The client MUST NOT issue more than one HTTP request per `RoutingBackend.route` call (no per-leg fan-out).

If OSRM's response `code` is not `"Ok"`, the client SHALL raise `RoutingBackendError(code, message)` with the OSRM-provided detail. The client SHALL set an httpx timeout of 10.0 seconds for the routing call. Timeouts SHALL surface as `RoutingBackendError("timeout", ...)`.

#### Scenario: 2-stop call hits /route with input ordering preserved
- **WHEN** `OsrmBackend.route([(40.804, -73.962), (40.811, -73.964)], mode="walking")` is invoked
- **THEN** httpx records exactly one outbound GET to `/route/v1/foot/...` with `geometries=geojson`, and the returned `RouteResult` has `stop_ordering="input_order"` with leg `from_index=0, to_index=1`

#### Scenario: 4-stop call hits /trip with TSP optimization
- **WHEN** `OsrmBackend.route([A, B, C, D], mode="walking")` is invoked with 4 distinct coordinates
- **THEN** httpx records exactly one outbound GET to `/trip/v1/foot/...` with `source=first&destination=last&roundtrip=false&geometries=geojson`, and the returned `RouteResult` has `stop_ordering="tsp_optimized"`; stops A and D occupy the first and last positions, while B and C may appear in either internal order based on OSRM's optimization

#### Scenario: 8-stop call uses /trip and stays in brute-force-optimal regime
- **WHEN** `OsrmBackend.route([A, B, C, D, E, F, G, H], mode="walking")` is invoked
- **THEN** the request hits `/trip` (≤8 waypoints triggers brute-force optimal TSP in OSRM); the result is treated as authoritative and rendered without further reordering

#### Scenario: OSRM error code surfaces as RoutingBackendError
- **WHEN** OSRM responds with `code="NoRoute"`
- **THEN** the client raises `RoutingBackendError("NoRoute", ...)` and the caller is responsible for fallback handling

#### Scenario: Snap radius is set to 50 m per stop
- **WHEN** the OSRM URL is constructed for N stops
- **THEN** the `radiuses` query parameter contains exactly N `50` values separated by semicolons, regardless of whether the request hits `/route` or `/trip`

#### Scenario: Single HTTP request per route call
- **WHEN** `OsrmBackend.route(...)` is called with 4 stops
- **THEN** httpx records exactly one outbound GET request, regardless of how many legs the result contains

### Requirement: Step-by-step instruction generation

The api SHALL convert OSRM `maneuver` objects into English step text via a deterministic formatter `format_step(maneuver, name, distance_m) -> str` in `apps/api/app/routing/steps.py`. The formatter SHALL produce output limited to a closed phrase set:

- `"Head <bearing-cardinal> on <street-name> for <distance> m"` for `maneuver.type="depart"`.
- `"Continue on <street-name> for <distance> m"` for `maneuver.type="continue"` or `new name`.
- `"Turn <left|right|sharp left|sharp right|slight left|slight right> onto <street-name>"` for `maneuver.type="turn"`.
- `"Arrive at <destination-name>"` for `maneuver.type="arrive"`.

The formatter SHALL drop steps whose `distance_m < 5` UNLESS the step is `depart` or `arrive`. The formatter SHALL round distances to the nearest 5 m for display but preserve the unrounded `distance_m` integer in the `Step.distance_m` field.

The formatter MUST NOT call any LLM or external service. Step text generation is fully deterministic given the OSRM input.

#### Scenario: Depart step renders with bearing and street name
- **WHEN** `format_step({"type": "depart", "bearing_after": 90}, name="West 110th Street", distance_m=82)` is called
- **THEN** the returned string equals `"Head east on West 110th Street for 80 m"`

#### Scenario: Tiny intermediate steps are dropped
- **WHEN** an OSRM `steps[]` array contains a `continue` step with `distance=2`
- **THEN** that step is omitted from the formatted output

#### Scenario: Arrive step never drops regardless of distance
- **WHEN** the final OSRM step has `type=arrive` and `distance=0`
- **THEN** the formatted output retains an `Arrive at ...` step at the end

#### Scenario: Step formatting is offline and deterministic
- **WHEN** `format_step` is called twice with identical input
- **THEN** the two outputs are byte-equal and no network or LLM call is made

### Requirement: GeoJSON geometry pass-through

The api SHALL request `geometries=geojson` from OSRM and SHALL pass the resulting `geometry` objects (full-route, per-leg, optionally per-step) into `RouteResult.geometry`, `Leg.geometry`, and `Step.geometry` without re-projection or re-encoding. There SHALL be no encoded-polyline codec in the api or the frontend; the wire format is GeoJSON end to end.

The frontend SHALL feed `walk.geometry.coordinates` directly into a MapLibre `geojson` source without a decoder. The `MapView` rendering effect MUST NOT depend on any polyline-decoding npm package.

#### Scenario: api forwards OSRM GeoJSON without re-encoding
- **WHEN** OSRM responds with `routes[0].geometry = {type: "LineString", coordinates: [[lon, lat], ...]}`
- **THEN** `RouteResult.geometry` is the same dict shape with the same coordinates (deep-equal); no precision loss occurs in transit

#### Scenario: Frontend renders without a polyline decoder
- **WHEN** the SSE `walk` frame arrives with `geometry.type="LineString"`
- **THEN** `MapView` calls `engine.addPath("walk", coords)` where `coords` is derived from `geometry.coordinates` via a single `[lon, lat] → {lng, lat}` shape conversion; no decoder package or function is invoked

#### Scenario: No polyline package in frontend dependencies
- **WHEN** the production bundle for `apps/web/` is inspected
- **THEN** no `polyline`, `@mapbox/polyline`, or `@aws/polyline` package appears in `package.json` dependencies, and no inline polyline-decoder file exists at `apps/web/src/map/polyline.ts`

### Requirement: Haversine fallback path

When the routing backend raises `RoutingBackendError`, the `plan_walk` tool implementation SHALL produce a structurally-identical `RouteResult` using straight-line haversine geometry. The fallback `RouteResult` SHALL have `routing_backend="haversine_fallback"` and `stop_ordering="input_order"`. Each `Leg.geometry` SHALL be a two-point LineString (`{type: "LineString", coordinates: [[lon0, lat0], [lon1, lat1]]}`); the full-route `RouteResult.geometry` SHALL be the concatenation of leg endpoints. `legs[].steps[]` SHALL contain exactly one entry `{instruction: "Head toward <name>", distance_m: <leg distance>, duration_s: <leg distance / WALK_M_PER_S>, maneuver_type: "depart"}`. `total_distance_m`/`total_duration_s` SHALL be consistent with the haversine sum.

The fallback path SHALL NOT silently swallow the original error: a structured warning record `{"event": "routing_backend_unavailable", "error": "<error>"}` MUST be logged before the fallback is used so telemetry can detect degradation.

#### Scenario: OSRM container down triggers haversine fallback
- **WHEN** the OSRM endpoint returns connection refused and the agent calls `plan_walk` with 3 valid stops
- **THEN** the tool returns a `RouteResult` with `routing_backend="haversine_fallback"` and a structured warning is emitted to the api logger

#### Scenario: Fallback geometry is a renderable LineString
- **WHEN** the fallback `RouteResult` is serialized through the SSE `walk` frame
- **THEN** `walk.geometry.type == "LineString"` with coordinates matching the (straight-line) endpoint sequence; the frontend renders the path without code change

### Requirement: Routing offline-on-localhost demo property

V1's demo target `docker compose up` SHALL produce a working routing backend without internet access at request time. The OSM extract SHALL be checked into the repository at `infra/osrm/extract.osm.pbf` (gitignored if larger than 50 MB; otherwise checked in). The `osrm-prepare` service SHALL idempotently produce the runtime `.osrm` files into a docker volume. The `osrm` service SHALL serve routes from that volume with no outbound HTTP needs.

#### Scenario: Cold checkout reaches a working routing backend
- **WHEN** a fresh checkout runs `make up` with no internet after the initial `docker pull`
- **THEN** `curl http://localhost:5000/route/v1/foot/-73.962,40.804;-73.964,40.811?overview=full&geometries=geojson` returns a JSON response with `code=Ok` and a GeoJSON LineString geometry

#### Scenario: Re-running osrm-prepare is a no-op when output is up to date
- **WHEN** `osrm-prepare` is started a second time with the extract unchanged
- **THEN** it exits 0 quickly without redoing the extract/partition/customize steps
