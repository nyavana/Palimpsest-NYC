# agent-route-planning — Implementation Notes (2026-05-04)

OpenSpec change: `agent-route-planning` (archived under `openspec/changes/archive/2026-05-05-agent-route-planning/`). Lifts the V1 walk planner from a server-side post-step into an LLM-callable tool, swaps haversine for OSRM-backed street-following routes, and adds a walk-intent soft hint to the system prompt.

This document captures the architecture decisions and the procedural knowledge needed to maintain the routing layer.

## What this change accomplishes

V1 shipped with a server-side `plan_walk` step that ran unconditionally after every agent turn over the cited place IDs, producing haversine straight-line walks. Two issues:

1. **It always ran.** Even informational queries ("tell me about the Cathedral of St John the Divine") got a one-stop "walk" frame, which is meaningless and confused the frontend.
2. **The route was a straight line.** The map markers were correctly placed, but the path between them cut through buildings, the cathedral close, and the Hudson.

This change moves the decision into the LLM (`plan_walk` is now a tool the model chooses to call) and routes via an OSRM `foot.lua` graph so the path follows actual pedestrian ways.

## Code changes

| Path | Purpose |
|---|---|
| `apps/api/app/routing/__init__.py` | Module surface — re-exports `RoutingBackend`, `OsrmBackend`, `RouteResult`, `Leg`, `Step`, `RoutingBackendError`. |
| `apps/api/app/routing/types.py` | Frozen-slots dataclasses for `Coordinate`, `Step`, `Leg`, `RouteResult`, plus the `GeoJSONLineString` TypedDict. `RouteResult` carries `geometry`, `routing_backend`, and `stop_ordering`. |
| `apps/api/app/routing/steps.py` | `format_step(maneuver, name, distance_m)` — deterministic English rendering of OSRM step dicts. Closed phrase set: depart / continue / new name / end of road / turn (4 directions + uturn) / arrive. Drops the "onto/on the route" suffix when OSRM returns an empty `name` (common on campus paths and unnamed alleys). |
| `apps/api/app/routing/osrm.py` | `OsrmBackend(base_url, timeout=10.0)`. Branches on stop count: 2 stops → `/route/v1/foot/...?steps=true&overview=full&geometries=geojson`, 3-8 stops → `/trip/v1/foot/...?source=first&destination=last&roundtrip=false`. **No `radiuses=...` query param** — see "Why no `radiuses`" below. |
| `apps/api/app/agent/intent.py` | `classify_walk_intent(query) -> "positive" \| "negative" \| "neutral"`. Regex/keyword-based; the result is appended to the system prompt as a soft hint, not enforced. |
| `apps/api/app/agent/tools/plan_walk.py` | LLM-callable tool. Validates `place_ids` against the retrieval ledger, looks up coordinates via the existing `app/agent/walk.py` DB helper, calls `RoutingBackend.route(...)`, and serializes the `RouteResult` with the `stop_ordering` telemetry tag. Catches `RoutingBackendError` and returns a haversine fallback so a degraded routing layer never fails the request. |
| `apps/api/app/agent/loop.py` | `MAX_TURNS_DEFAULT` raised 6 → 7. System prompt extended with the "when to call `plan_walk`" rubric and the intent-hint line. `AgentResult` gains `walk: PlannedRoute \| None` and `walk_intent_hint: str`. The latest successful `plan_walk` result is captured into `AgentResult.walk` (most-recent-wins). |
| `apps/api/app/routes/agent.py` | Removed the unconditional post-loop `plan_walk` call. Now emits a `walk` SSE frame only if `terminal_result.walk is not None`. |
| `apps/api/app/main.py` | Lifespan builds an `OsrmBackend` and stashes it on `app.state.routing_backend`. Registers `PlanWalkTool` alongside `SearchPlacesTool` in the tool registry. |
| `apps/api/app/config.py` | Adds `OSRM_BASE_URL` (default `http://osrm:5000`). |
| `apps/api/app/meta/...` | Telemetry: `SessionRecord` gains `plan_walk_called`, `routing_backend`, `stop_ordering`, `walk_intent_hint`. |
| `apps/web/src/state/types.ts` | `PlannedRoute` (replaces the temporary `WalkPayload`), `RouteLeg`, `RouteStep`, `GeoJSONLineString`. Field naming aligns with the wire schema. |
| `apps/web/src/state/useAgentSession.ts` | Walk state collapses to a single `walk: PlannedRoute \| null` field (replaces the split `walk` / `walkLegs` / `walkGeometry` triple introduced as a forward-port). |
| `apps/web/src/components/MapView.tsx` | Consumes `walk.geometry.coordinates` and feeds them into `engine.addPath` after the `[lon, lat] → {lat, lng}` swap. Haversine fallback rendered with a dashed muted style. |
| `apps/web/src/components/WalkTimeline.tsx` | Totals footer (`Total · 1.2 km · ~15 min`), per-stop disclosure expanding `legs[i].steps[]` as numbered turn-by-turn instructions, `tsp-optimized` badge when applicable. |
| `infra/osrm/extract.osm.pbf` (gitignored) | The Morningside Heights + UWS bbox extract. Refresh procedure in `infra/osrm/README.md`. |
| `docker-compose.yml` | Adds `osrm-prepare` (one-shot extract/partition/customize) and `osrm` (runtime, port 5000) services, plus a named `osrm-data` volume shared between them. |

## Architecture decisions

### OSRM with the `foot.lua` profile

We picked OSRM over Valhalla, GraphHopper, and OpenRouteService because:

1. **Simplest deployment.** A single docker image (`osrm/osrm-backend:v5.25.0`) with a one-shot prep step. No Java runtime, no PostGIS dependency duplication, no API key.
2. **MLD on a small bbox is instant.** Multi-Level Dijkstra serves a Morningside Heights → Grant's Tomb route in under 5 ms on the prepared graph. We never approach the latency budget.
3. **`foot.lua` is the right profile out of the box.** It already excludes motor roads, includes campus paths and park trails, and respects pedestrian-only crossings. Switching to `car.lua` or `bicycle.lua` produces nonsensical walking routes — do not.

The image is pinned to `v5.25.0` (`fb23cc9`). An earlier attempt at `v5.27.1` was a hallucinated tag — the OSRM Docker Hub page tops out at `v5.25.0` at the time of writing.

### `/route` for 2 stops, `/trip` for 3-8 stops

OSRM exposes two endpoints:

- **`/route/v1/foot/{coords}`** — connect waypoints in the given order, return one route. Used for 2-stop walks; sets `stop_ordering="input_order"`.
- **`/trip/v1/foot/{coords}`** — solve a TSP over the waypoints and return the optimal visiting order. Used for 3-8 stops with `source=first&destination=last&roundtrip=false` (start and end are pinned to the agent's first and last citations; the middle is reordered by the solver). After the response, we reorder `legs[]` by `waypoints[].waypoint_index` before serializing. Sets `stop_ordering="tsp_optimized"`.

The 8-stop cap matches OSRM's default (`max-trip-size=10` minus the source/destination pinning headroom). For longer walks, V2 would split into segments.

### GeoJSON LineString end-to-end (no polyline codec)

OSRM offers two response formats for `geometry`: a Mapbox-style polyline string (default) or RFC 7946 GeoJSON LineString (when `geometries=geojson`). We use GeoJSON throughout:

- The api's `OsrmBackend` requests `geometries=geojson`.
- `RouteResult.geometry`, `Leg.geometry`, and `Step.geometry` carry the GeoJSON `{type: "LineString", coordinates: [[lon, lat], ...]}` object **untouched**.
- The SSE serializer passes this object straight through; no encoding step.
- The frontend's `MapView` consumes `walk.geometry.coordinates` and converts each `[lon, lat]` to the engine's `{lat, lng}` shape inline (one map call), then feeds the array into `engine.addPath`. **No `polyline.ts` exists in the frontend** — there is a test that fails fast if anyone re-introduces a decoder.

This costs ~3-5x more wire bytes than encoded polylines in the worst case, but for a Manhattan-bbox walk that's still under 50 KB and the simplification is worth it. `agent-route-planning/design.md §2` has the full rationale.

### Walk-intent soft hint, not a router

`apps/api/app/agent/intent.py` classifies the user's query into one of `{positive, negative, neutral}` based on regex/keyword rules ("walk through", "tour" → positive; "what is", "tell me about" → negative; everything else → neutral). The label is appended to the system prompt as a one-liner:

> _Hint: the user appears to want a walking tour — consider calling `plan_walk` if you have ≥2 cited places._

This is **a soft hint, not a router**. The LLM is still in charge of the call decision; the classifier is just a prior. The `neutral` case appends nothing.

The label is also stored on `AgentResult.walk_intent_hint` and surfaced in session telemetry, so over/under-call rates can be evaluated separately by hint label.

### `RoutingBackend` swap-in pattern

`OsrmBackend` is one implementation of a `RoutingBackend` Protocol-style interface (`route(stops, mode) -> RouteResult`). The lifespan builds a single instance and stashes it on `app.state.routing_backend`; tools resolve it through the request's `ToolExecutionContext`. To swap in Valhalla, OpenRouteService, or an in-process router for tests, you replace one factory call in `app/main.py` and nothing else changes — `plan_walk.py`, the SSE handler, and the frontend are agnostic.

The haversine fallback path uses this same shape: when `OsrmBackend.route` raises, `plan_walk` builds a synthetic `RouteResult` with `routing_backend="haversine_fallback"` and a two-point GeoJSON LineString per leg. The frontend already handles this (dashed muted path), so a degraded routing layer is graceful, not a hard failure.

### Why no `radiuses` constraint on OSRM calls

The first implementation passed `radiuses=50;50;...` to constrain where each waypoint could snap to the road network. **This was wrong** — the constraint applied not just to the input snap but to the candidate edge set during routing. Valid routes through the network (where every stop snapped within 50 m of a road) were rejected with `code: NoRoute` because the path between snaps required edges outside the 50 m radius.

Removing the constraint and letting OSRM use its default unconstrained snapping produces correct results. For our small bbox where road density bounds snap distance anyway, the unconstrained behavior is what we want. This is documented inline in `osrm.py` and in the routing module docstring.

## OSM extract refresh procedure

The OSM extract at `infra/osrm/extract.osm.pbf` is **gitignored** (~100 MB, changes upstream over time). On a fresh checkout you need to drop a real extract there before `make up`. Two sources:

1. **BBBike** (recommended for precise bbox): https://extract.bbbike.org → PBF format → enter the bbox `west=-74.000, south=40.795, east=-73.955, north=40.825` → email link, ~5 minutes, ~3-8 MB raw download.
2. **Geofabrik New York metro + osmium clip**: download `new-york-latest.osm.pbf` (~1.2 GB), then `osmium extract --bbox -74.000,40.795,-73.955,40.825 new-york-latest.osm.pbf -o extract.osm.pbf`.

After replacing the file:

```bash
docker volume rm palimpsest-osrm-data   # drop the prepared graph
make up                                  # osrm-prepare reprocesses (~2 min total)
```

Quarterly cadence is more than enough for the V1 bbox — OSM coverage in Morningside Heights / UWS is excellent and stable. Full procedure: [`infra/osrm/README.md`](../infra/osrm/README.md).

## Tests added

| File | Count | Coverage |
|---|---|---|
| `tests/test_routing_steps.py` | 30+ | Every maneuver type × modifier combination from the closed phrase set. Empty-name behavior (drops "onto/on the route" suffix). Distance rounding to 5 m. `<5 m` step drop rule. |
| `tests/test_routing_osrm.py` | ~12 | `httpx` mock for OSRM. `/route` 2-stop fixture with GeoJSON geometry. `/trip` 4-stop fixture with `waypoints[].waypoint_index` permutation honored. `code="NoRoute"` → `RoutingBackendError`. `mode="driving"` → `ValueError`. **No `radiuses` param sent** (regression guard). |
| `tests/test_plan_walk_tool.py` | ~6 | 2-stop success (`stop_ordering="input_order"`); 4-stop success (`stop_ordering="tsp_optimized"`, OSRM permutation honored); unknown_place_id; too_few_places; unsupported_mode; OSRM down → haversine fallback with renderable LineString geometry. |
| `tests/test_walk_intent.py` | ~30 fixtures | Hand-labeled queries (~10 each: positive/negative/neutral). Asserts the classifier matches every label. |
| `tests/test_agent_loop.py` | (new cases) | Tour-style query (positive hint) calls `plan_walk` and populates `AgentResult.walk`. Informational query (negative hint) does not. Two `plan_walk` calls → only the second is retained. |
| `apps/web/src/components/WalkTimeline.test.tsx` | ~10 | Totals footer rendering. `tsp-optimized` badge when `stop_ordering` matches. Disclosure trigger expand/collapse. Stop 0 has no incoming-leg disclosure. Per-step distance rounding shown verbatim. |
| `apps/web/src/components/MapView.test.tsx` | (new path-drawing cases) | `walk.geometry.coordinates` fed to `engine.addPath` after `[lon, lat] → {lat, lng}` swap. Legacy V1 walks (no `geometry`) fall back to straight-line stop coords. `routing_backend="haversine_fallback"` renders dashed style. `walk=null` clears the layer. |

Final tallies: 237 backend tests pass (1 skipped — the HF-weights integration), 46 frontend tests pass. End-to-end SSE smoke tests covered §10.2 (3-stop tour), §10.3 (2-stop tour), §10.4 (informational query produces no walk frame), §10.5 (OSRM down → haversine fallback path renders).

## What unblocks next

- **Wiring OSRM into `docker-compose.prod.yml`.** Currently published-image deployments fall back to haversine. The osrm-prepare/osrm services exist only in dev `docker-compose.yml`. Adding them to prod requires deciding how the `.osm.pbf` ships (committed bbox extract vs. download-on-first-boot vs. baked into a custom image).
- **Multi-mode support.** The tool surface accepts `mode` enum but only `walking` is wired; cycling/driving extensions would need profile-aware OSRM service instances and a per-mode prep step.
- **Eval rubric for over/under-call rates.** The `walk_intent_hint` telemetry exists; `docs/walk-eval-checklist.md` was updated with two columns for "walk decision appropriate" and "hint correct" so over/under-call rates can be tracked separately by hint label. Running this against a labeled fixture set is a separate eval task.

## Out-of-scope work flagged (not done in this change)

- **Polyline codec.** Not added by design. There is a test that fails fast if `apps/web/src/map/polyline.ts` ever appears.
- **Reusing OSRM for distance-only place ranking.** Cosine + `pg_trgm` remains the retrieval signal; routing is post-retrieval.
- **In-app extract refresh UX.** Refreshing OSM data is a maintainer operation, not a runtime concern. The procedure lives in [`infra/osrm/README.md`](../infra/osrm/README.md).
