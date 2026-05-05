## MODIFIED Requirements

### Requirement: Minimum interface surface

The `MapEngine` interface SHALL expose at least the following methods, each with stable semantics: `init(container, viewport)`, `setViewport(v)`, `flyTo(target, durationMs?)`, `addMarkers(layerId, markers)`, `addPath(layerId, coords, style?)`, `clearLayer(layerId)`, and `destroy()`. Additional methods MAY be added later as optional members.

The previously-required `onCameraChange(cb)` callback method is removed from the V1 interface and deferred to v2. V1 drives the camera deterministically via `flyTo` (one fly-to per tour stop) and does not need to react to user-driven camera changes. v2 will re-introduce camera-change observation if a feature like "show what's currently on screen" is added.

`addPath` semantics in V1 are sharpened: when called with a layerId of `"walk"` and coords derived from a `plan_walk` tool result, the path SHALL render the routing engine's GeoJSON LineString geometry (street-following), NOT a great-circle line connecting stop markers. The frontend reads `walk.geometry.coordinates` directly (no decoder); the engine's caller-facing input remains a `LatLng[]` array, so the engine itself does not change.

#### Scenario: MaplibreEngine provides every V1 interface method
- **WHEN** `MaplibreEngine` is instantiated
- **THEN** calling each method from the V1 interface (`init`, `setViewport`, `flyTo`, `addMarkers`, `addPath`, `clearLayer`, `destroy`) either executes or returns a well-typed Promise, with no `undefined is not a function` errors

#### Scenario: V1 interface does NOT include onCameraChange
- **WHEN** an application component attempts `engine.onCameraChange(cb)` in V1
- **THEN** the TypeScript compiler reports the method as missing from the `MapEngine` interface; the build fails before runtime

#### Scenario: addPath renders street-following geometry for walks
- **WHEN** `MapView` reads `walk.geometry.coordinates` (an `[lon, lat][]` array of N≥2 vertices) and calls `engine.addPath("walk", coords)`
- **THEN** the rendered path follows those coordinates vertex-by-vertex (no great-circle smoothing, no mid-segment interpolation through buildings); a visual diff against the OSRM-returned LineString matches within 1-px tolerance at zoom ≥15

#### Scenario: Adding onCameraChange in v2 is a non-breaking interface extension
- **WHEN** v2 re-adds `onCameraChange` as an optional method on the interface
- **THEN** existing V1 components compile unchanged because they never referenced the method

## ADDED Requirements

### Requirement: Walk frame consumer renders LineString geometry + steps

The frontend's SSE consumer SHALL accept the extended `walk` frame payload (`geometry`, `legs[].geometry`, `legs[].steps[]`, `total_distance_m`, `total_duration_s`, `stop_ordering`) additively. Components that read only the V1 fields (`stops[]`) MUST continue to function with no code change.

`MapView` SHALL feed `walk.geometry.coordinates` to `engine.addPath("walk", coords)` after a single `[lon, lat] → {lng, lat}` shape conversion. There SHALL NOT be an encoded-polyline decoder anywhere in the frontend codebase.

`WalkTimeline` SHALL render a footer line containing total distance and duration when `total_distance_m` and `total_duration_s` are present on the `PlannedRoute`. The component SHALL render an expandable per-leg disclosure: clicking a stop expands a list of `legs[<stop.index - 1>].steps[]` rendered as `1. <step.instruction>`. The first stop has no incoming leg and SHALL NOT show a disclosure.

#### Scenario: Walk frame without geometry still renders stops
- **WHEN** the SSE `walk` frame includes only the V1 fields `stops[]` (no `geometry`, no `legs`) — a regression case for backward compatibility
- **THEN** `WalkTimeline` renders the numbered stops list and `MapView` renders markers; no path is drawn from `engine.addPath("walk", ...)`; no footer total appears

#### Scenario: Walk frame with GeoJSON LineString renders street-following path
- **WHEN** the SSE `walk` frame includes `geometry.type="LineString"` with non-empty coordinates
- **THEN** `MapView` passes those coordinates (after `[lon, lat] → {lng, lat}` conversion) directly into `engine.addPath`; the rendered path follows the routed geometry; the path does not coincide with straight-line edges between markers

#### Scenario: Per-leg step disclosure expands turn-by-turn directions
- **WHEN** the user clicks the second stop in a 3-stop walk where `legs[0].steps` has 5 entries
- **THEN** the disclosure expands to show 5 numbered instructions, each with a step distance label (e.g., `"80 m"`)

#### Scenario: Footer total renders only when totals are present
- **WHEN** `PlannedRoute.total_distance_m=1245` and `total_duration_s=890`
- **THEN** the timeline footer renders `"Total: 1.2 km · ~15 min"` rounded to one decimal km and integer minutes

### Requirement: No polyline-decoder dependency in the frontend

The frontend SHALL NOT import or implement a Google polyline decoder. The wire format from the api is GeoJSON LineString, which the MapLibre `geojson` source consumes natively. There SHALL NOT be a file at `apps/web/src/map/polyline.ts` (or any other path) implementing precision-5/6 polyline decoding for the walk path.

#### Scenario: No polyline package in dependencies
- **WHEN** `apps/web/package.json` is inspected
- **THEN** no `polyline`, `@mapbox/polyline`, or `@aws/polyline` package appears in `dependencies` or `devDependencies`

#### Scenario: No inline polyline decoder
- **WHEN** the `apps/web/src/map/` directory is inspected
- **THEN** no source file implements `decodePolyline` or equivalent; the only line-rendering code path goes through `engine.addPath` with a `LatLng[]` derived from a GeoJSON LineString

## REMOVED Requirements

### Requirement: Server emits walk frame after every successful conversation
**Reason**: Replaced by the LLM-decided `plan_walk` tool. The walk frame is now emitted only when the agent has called `plan_walk`; informational queries no longer get a default 1-stop walk.
**Migration**: Frontend already keys `WalkTimeline` rendering on the presence of stops. Queries without a `walk` frame simply do not render the timeline. No frontend code change needed beyond accepting the new optional fields described in the ADDED requirement above.
