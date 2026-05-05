## Why

V1 ships a working agent loop that emits cited places, and a server-side `plan_walk` post-processing pass that runs unconditionally after every query. The pass is deliberately minimal: it dedupes the cited `place_ids`, looks up their coordinates, and emits an ordered list with **straight-line haversine** leg distances. The frontend renders these as numbered markers and a great-circle path.

Two gaps make this unsatisfying for an urban explorer tool:

1. **Straight lines are not a route.** "Walk 412 m" between two stops in Morningside Heights crosses through buildings and ignores the actual street grid. There are no turn-by-turn directions because there is no path on a real network — only two endpoints.
2. **Every query gets a walk, even when the user didn't ask for one.** "Tell me about the Cathedral of St. John the Divine" is informational; emitting a one-stop walk over it adds visual noise and confuses the UI's intent. Walks should appear when the user is asking for a tour, comparison, or directions — not as a default trailer on every response.

The fix is to give the LLM agency over when (and over which places) to plan a route, and to back the route with a real OSM street-graph routing engine.

## What Changes

- **MODIFY** the V1 agent tool surface from one tool to two: `search_places` (unchanged) and a new `plan_walk` tool the LLM **chooses to call** when the user is asking for a tour, route, or directions across 2+ places. Single-place informational queries continue to work without a walk.
- **ADD** a `route-planning` capability covering: (a) an OSM-graph routing backend, (b) a deterministic stop-ordering and routing pass that maps `place_ids` → GeoJSON LineString geometry + per-leg step-by-step instructions, (c) the `plan_walk` tool's input/output contract, and (d) the `walk` SSE event payload extension that carries the geometry and steps. Geometry is exchanged as **GeoJSON LineString** (not encoded polyline) — MapLibre has no native polyline source, so a LineString feeds `addSource` directly with no decoder; gzip-on-the-wire absorbs the size delta at NYC walking-tour scale.
- **ADD** an OSRM-based routing service (`osrm/osrm-backend` Docker image) backed by an OSM extract for the V1 bbox (Morningside Heights + UWS). Routing is offline once the extract is preprocessed; no live HTTP calls to a third-party routing service are required for the demo. The api branches between OSRM's `/route` endpoint (2 stops) and `/trip` endpoint (≥3 stops, brute-force TSP with `source=first&destination=last`) so multi-stop tours get a near-optimal visit order without re-implementing TSP.
- **REPLACE** the unconditional server-side post-processing path: server-side `plan_walk` over `citations[]` is removed from `apps/api/app/routes/agent.py`. The walk only appears when the LLM tool-calls it. The internal `apps/api/app/agent/walk.py::plan_walk_from_coords` (haversine helper) is retained as a fallback used by the routing pass when OSRM is unreachable, and as a unit-test convenience.
- **MODIFY** the `agent-tools` capability: register two tools, update the system prompt with explicit "when to call `plan_walk`" criteria, raise the turn cap from 6 to 7 to absorb the extra round-trip, and extend the citation/event contract so a `plan_walk` tool result is treated as authoritative for the SSE `walk` frame.
- **ADD** a server-side **walk-intent soft hint**: a regex over the user query (`walk|tour|route|directions|itinerary|from .* to`) appends a one-line bias to the system prompt nudging the LLM toward (or away from) calling `plan_walk`. The hint is a *bias*, never a gate — when the regex misses, the LLM still decides on its own. This is the layered heuristic→LLM pattern (Arize / NVIDIA AI Blueprints) and follows the When2Call (NAACL 2025) framing for tool-decision accuracy.
- **MODIFY** the `map-engine` capability: the `addPath` method's V1 contract is sharpened to render the routing engine's GeoJSON LineString (street-following) rather than a great-circle line. The frontend `WalkTimeline` adds a per-leg expander that reveals step-by-step text from the routing tool result.
- **DEFER** to v2: multi-modal routing (transit, biking), accessibility-aware routing (avoid stairs), live-traffic-aware ETAs, and any UI to let the user re-order stops manually.

## Capabilities

### New Capabilities

- `route-planning`: OSM-graph routing for the agent — converts an ordered list of `place_ids` (chosen by the LLM in a `plan_walk` tool call) into a real walking route with polyline geometry, per-leg step-by-step navigation text, and total distance/duration. Defines the routing-backend contract (OSRM-compatible HTTP) so the implementation is swappable.

### Modified Capabilities

- `agent-tools`: V1 single-tool surface becomes two-tool. Adds `plan_walk` as an LLM-callable tool with a documented "when to call" rubric in the system prompt, raises the turn cap to 7, and removes the unconditional server-side post-processing pass over `citations[]`. The citation contract is unchanged.
- `map-engine`: tightens the path rendering contract — the polyline drawn for a walk SHALL follow the routing engine's geometry, not a straight line; the rendering MUST round-trip an encoded polyline (Google polyline algorithm, precision 5 or 6) without re-projection.

## Impact

- **Filesystem**: adds `apps/api/app/agent/tools/plan_walk.py` (new tool implementation), `apps/api/app/routing/` (routing backend client + step formatter + polyline codec), `apps/api/tests/test_plan_walk_tool.py`, `apps/api/tests/test_routing_backend.py`. Adds `infra/osrm/` with the bbox extract recipe + `Dockerfile.osrm-prepare`. Modifies `docker-compose.yml` to add the `osrm` service, `apps/api/app/agent/loop.py` (system prompt + turn cap + tool registry), `apps/api/app/routes/agent.py` (drop the server-side walk; relay the agent's `walk` event verbatim), and `apps/web/src/components/WalkTimeline.tsx` + `apps/web/src/state/types.ts` (steps + polyline). Updates `apps/web/src/state/sse.ts` payload type.
- **Runtime dependencies**: adds `osrm/osrm-backend:v5.27.1` (or pinned later) container; ~600 MB image. The bbox extract for Morningside Heights + UWS is ~3-8 MB raw `.osm.pbf`, ~30-60 MB after `osrm-extract` + `osrm-partition` + `osrm-customize`. Adds Python `polyline` package for encoded-polyline decoding in tests.
- **External services**: none new at runtime. The OSM extract is a one-time download from Geofabrik or `bbbike.org` during initial setup; the OSRM container has no outbound network needs. A v2 swap-in to a hosted ORS/OSRM endpoint requires only changing `OSRM_BASE_URL`.
- **Cost**: zero additional LLM dollars in the steady state — `plan_walk` is a tool call, not a separate LLM round. The extra turn it consumes is absorbed by the cap raise (6 → 7); per-walk cost rises by at most one tool-result ingestion turn and stays well within the cache TTL.
- **Backwards compatibility**: the SSE `walk` frame's existing fields (`stops[]` with `index`, `doc_id`, `name`, `lat`, `lon`, `leg_distance_m`) remain. New fields (`geometry` GeoJSON LineString, `legs[].steps[]`, `legs[].geometry`, `total_distance_m`, `total_duration_s`) are additive. Frontend code that only reads the existing fields continues to work; the new step-by-step UI is opt-in render.
