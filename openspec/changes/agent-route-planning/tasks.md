## 1. OpenSpec Artifacts

- [x] 1.1 Write `proposal.md`
- [x] 1.2 Write `design.md`
- [x] 1.3 Write ADDED `specs/route-planning/spec.md`
- [x] 1.4 Write MODIFIED `specs/agent-tools/spec.md` (two-tool surface, turn cap 7, server-side post-processing removed)
- [x] 1.5 Write MODIFIED `specs/map-engine/spec.md` (street-following addPath, walk-frame consumer, polyline decoder, REMOVED unconditional walk frame)
- [x] 1.6 Write `tasks.md` (this file)
- [x] 1.7 Run `openspec validate agent-route-planning --strict` and fix any issues

## 2. Routing Backend Infrastructure (Docker + OSM extract)

- [x] 2.1 Create `infra/osrm/` directory with a `README.md` describing how to refresh the OSM extract from BBBike or Geofabrik for the V1 bbox (`-74.000, 40.795, -73.955, 40.825`)
- [x] 2.2 Add `infra/osrm/extract.osm.pbf` to the repo (or document the download path if it exceeds the 50 MB threshold and gitignore it). *Gitignored; placeholder + `make extract` documented.*
- [x] 2.3 Add an `osrm-prepare` one-shot service to `docker-compose.yml` running `osrm-extract -p /opt/foot.lua && osrm-partition && osrm-customize`, idempotent on volume mtime
- [x] 2.4 Add a runtime `osrm` service to `docker-compose.yml` running `osrm-routed --algorithm mld /data/extract.osrm` on port 5000
- [x] 2.5 Add a named docker volume `osrm-data` shared read-write between `osrm-prepare` and read-only into `osrm`
- [x] 2.6 Update `Makefile` if needed so `make up` brings the routing services healthy alongside postgres/redis/api/web. *No service-list filter; `make extract` target added for OSM extract download.*
- [ ] 2.7 Smoke: `curl http://localhost:5000/route/v1/foot/-73.962,40.804;-73.964,40.811?overview=full&steps=true` returns `code=Ok` *(deferred to Wave 5; needs the bbox extract dropped in place + container running)*

## 3. Routing Module (apps/api/app/routing)

- [x] 3.1 Create `apps/api/app/routing/__init__.py` exporting `RoutingBackend`, `OsrmBackend`, `RouteResult`, `Leg`, `Step`, `RoutingBackendError`, `GeoJSONLineString`
- [x] 3.2 Create `apps/api/app/routing/types.py` with `Coordinate`, `GeoJSONLineString` (TypedDict), `Step`, `Leg`, `RouteResult` dataclasses (slots, frozen where applicable). `RouteResult` carries `geometry: GeoJSONLineString`, `routing_backend`, and `stop_ordering`
- [x] 3.3 Create `apps/api/app/routing/steps.py` with `format_step(maneuver, name, distance_m) -> str` per the closed phrase set in the spec; unit tests cover depart/continue/turn/arrive and the <5 m drop rule
- [x] 3.4 Create `apps/api/app/routing/osrm.py` with `OsrmBackend(base_url, timeout=10.0)` and `route(stops, mode="walking") -> RouteResult`. Branch on `len(stops)`:
  - 2 stops → GET `/route/v1/foot/...?steps=true&overview=full&geometries=geojson&annotations=duration,distance&radiuses=50;...` → set `stop_ordering="input_order"`
  - 3-8 stops → GET `/trip/v1/foot/...?steps=true&overview=full&geometries=geojson&source=first&destination=last&roundtrip=false&radiuses=50;...` → set `stop_ordering="tsp_optimized"`, reorder `legs[]` by `waypoints[].waypoint_index`
- [x] 3.5 Forward OSRM's GeoJSON `geometry` objects untouched into `RouteResult.geometry`, `Leg.geometry`, and `Step.geometry`. Do NOT add a polyline codec — there is no `polyline.py`
- [x] 3.6 Add `OSRM_BASE_URL` to `apps/api/app/config.py::Settings` (default `http://osrm:5000`)
- [x] 3.7 Wire the routing backend into `app.state.routing_backend` in `apps/api/app/main.py::lifespan`
- [x] 3.8 Unit tests `apps/api/tests/test_routing_steps.py`, `test_routing_osrm.py` (httpx mock for OSRM, separate fixtures for `/route` 2-stop and `/trip` 4-stop with `waypoints[].waypoint_index` permutation). *33 tests pass; full suite 207 passed/1 skipped.*

## 4. plan_walk Tool

- [x] 4.1 Create `apps/api/app/agent/tools/plan_walk.py` declaring the JSON Schema (place_ids 2..8, mode enum)
- [x] 4.2 Implement `PlanWalkTool.run(args, context)`: dedupe `place_ids`, validate against `context.retrieval_ledger`, look up coordinates via the existing `apps/api/app/agent/walk.py::plan_walk` DB helper (or its underlying SQL), then call `context.routing_backend.route(...)` and serialize the result with the `stop_ordering` telemetry tag
- [x] 4.3 Implement the haversine fallback path: catch `RoutingBackendError`, log a structured warning, build a `RouteResult` with `routing_backend="haversine_fallback"`, `stop_ordering="input_order"`, per-leg `geometry` as a two-point GeoJSON LineString, and a single `"Head toward <name>"` step per leg
- [x] 4.4 Extend `ToolExecutionContext` (in `apps/api/app/agent/tools/base.py`) to carry `routing_backend` and `retrieval_ledger` references
- [x] 4.5 Register `PlanWalkTool` in the lifespan-built `agent_tool_registry` alongside `SearchPlacesTool`. *Per-request context fields (`routing_backend`, `retrieval_ledger`) wired by Wave 3/4.*
- [x] 4.6 Unit tests `apps/api/tests/test_plan_walk_tool.py` covering: 2-stop success (`stop_ordering="input_order"`), 4-stop success (`stop_ordering="tsp_optimized"`, OSRM `waypoints[].waypoint_index` permutation honored), unknown_place_id, too_few_places, unsupported_mode, OSRM down → haversine fallback with a renderable LineString geometry. *8 tests pass; full suite 215 passed/1 skipped.*

## 5. Walk-Intent Soft Hint

- [x] 5.1 Create `apps/api/app/agent/intent.py` with `classify_walk_intent(query: str) -> Literal["positive", "negative", "neutral"]` implementing the regex/keyword rules in the agent-tools spec
- [x] 5.2 Curate a fixture set of ~30 hand-labeled queries (~10 each label) at `apps/api/tests/fixtures/walk_intent_queries.json` *(10/10/10)*
- [x] 5.3 Unit test `apps/api/tests/test_walk_intent.py` asserting the classifier matches the labeled fixtures *(54 tests pass)*
- [x] 5.4 Update the agent loop builder so the system prompt is templated from `_SYSTEM_PROMPT + INTENT_NOTE[label]`. The `neutral` label appends nothing
- [x] 5.5 Capture `walk_intent_hint: str` on `AgentResult` so the SSE handler / telemetry can record it without re-classifying

## 6. Agent Loop Update

- [x] 6.1 In `apps/api/app/agent/loop.py`, raise `MAX_TURNS_DEFAULT` from 6 to 7
- [x] 6.2 Extend the `_SYSTEM_PROMPT` with the "when to call plan_walk" rubric described in design §7 (preserve all existing rules verbatim)
- [x] 6.3 Add `walk: PlannedRoute | None` and `walk_intent_hint: Literal["positive", "negative", "neutral"]` to `AgentResult`; defaults `None` and `"neutral"`. *PlannedRoute aliased to `dict[str, Any]` for V1.*
- [x] 6.4 Capture the latest successful `plan_walk` tool result into `AgentResult.walk`; replace on each successful call (most recent wins)
- [x] 6.5 Pass `routing_backend` from `app.state` into `ToolExecutionContext` at the SSE handler entry point
- [x] 6.6 Append the §5.4 INTENT_NOTE line to the system prompt at loop construction time (not at every turn) and store the label on `AgentResult`. *Run-time templating in `run_streamed`; the prompt module-level constant stays untouched.*
- [x] 6.7 Update or add tests in `apps/api/tests/test_agent_loop.py` covering: (a) tour-style query (`positive` hint) → `plan_walk` is called, AgentResult.walk is populated; (b) informational query (`negative` hint) → `plan_walk` is not called, AgentResult.walk is `None`; (c) ambiguous (`neutral`) query → both behaviors valid; (d) two `plan_walk` calls → only the second is retained on AgentResult.walk. *8 new tests; full suite 223 passed/1 skipped.*

## 7. SSE Handler Update

- [x] 7.1 In `apps/api/app/routes/agent.py`, remove the unconditional `plan_walk(session=..., place_ids=[c.doc_id ...])` call after the loop completes
- [x] 7.2 Replace it with: emit the `walk` frame ONLY if `terminal_result.walk is not None`, serializing the `PlannedRoute` dataclass (with `legs[].steps[]`, `legs[].geometry`, full-route `geometry`, totals, `stop_ordering`). *Framed directly with `_frame("walk", terminal_result.walk)` so GeoJSON dicts pass through as plain JSON objects.*
- [x] 7.3 Preserve the V1 `walk` frame's `stops[]` shape (additive change only); keep the same SSE event name
- [x] 7.4 Update `_serialize_event` to handle the new `AgentResult.walk` field if needed; ensure GeoJSON `geometry` dicts serialize as plain JSON objects, not wrapped in dataclass shells. *Walk frame bypasses `_serialize_event` (it operates on `AgentEvent`s); GeoJSON dicts hit `json.dumps` directly.*
- [ ] 7.5 Curl smoke per the spec: tour-style query produces a `walk` frame; informational query does not *(deferred to Wave 5)*

## 8. Frontend Updates

- [x] 8.1 Extend `apps/web/src/state/types.ts`: add `GeoJSONLineString` type alias, `RouteLeg`, `RouteStep`; extend `PlannedRoute` with `geometry?: GeoJSONLineString`, `legs?: RouteLeg[]`, `total_distance_m?: number`, `total_duration_s?: number`, `stop_ordering?: "input_order" | "tsp_optimized"` (all optional for backward compatibility)
- [x] 8.2 Update `apps/web/src/state/sse.ts` typed payload schema for the `walk` event to mirror the extended shape (no decoder needed)
- [x] 8.3 Update `apps/web/src/components/MapView.tsx` to: when a `walk` frame includes `geometry`, convert `geometry.coordinates` from `[lon, lat]` to `{lng, lat}` and pass into `engine.addPath("walk", coords)`; when only V1 `stops[]` is present, fall back to the existing straight-line behavior. NO polyline decoder is created — the file `apps/web/src/map/polyline.ts` MUST NOT exist. *Haversine fallback renders dashed + ink-muted via existing `PathStyle.dashed`.*
- [x] 8.4 Update `apps/web/src/components/WalkTimeline.tsx`: render a footer with `total_distance_m`/`total_duration_s` when present, formatted as `"Total: 1.2 km · ~15 min"`; add a per-stop disclosure that expands `legs[stop.index - 1].steps[]` rendered as numbered instructions. *Plus a `tsp-optimized` micro-annotation in the section header when stops were reordered.*
- [x] 8.5 Confirm `npm run typecheck` and `npm run lint` pass cleanly in `apps/web/`; confirm no `polyline` or `@mapbox/polyline` is added to `apps/web/package.json`. *Typecheck clean; lint baseline-identical (zero new errors/warnings).*
- [x] 8.6 Add a Vitest snapshot or RTL test for `WalkTimeline` rendering with a fake walk fixture (stops + legs + steps + totals + GeoJSON geometry). *7 vitest+RTL tests written; vitest itself not installed (no new devDeps); test files excluded from tsc/eslint until vitest lands.*
- [x] 8.7 Add a `MapView` test asserting it consumes `walk.geometry.coordinates` directly, without invoking any decoder function. *5 tests written under same vitest-pending arrangement.*

## 9. Telemetry

- [x] 9.1 Extend `SessionRecord` (in `apps/api/app/meta/`) with optional `plan_walk_called: bool`, `routing_backend: str | None`, `stop_ordering: str | None`, `walk_intent_hint: str` (defaults `"neutral"`)
- [x] 9.2 Populate the new fields from `AgentResult` (`plan_walk_called = result.walk is not None`; `routing_backend = result.walk.routing_backend if result.walk else None`; `stop_ordering = result.walk.stop_ordering if result.walk else None`; `walk_intent_hint = result.walk_intent_hint`). *New `_record_session` hook in routes/agent.py; failures swallowed so telemetry never breaks SSE.*
- [x] 9.3 Update the §13.4 hand-grading checklist (in `docs/`) with two columns: "walk decision appropriate" and "hint correct" so over/under-call rates can be tracked separately by hint label. *Created `docs/walk-eval-checklist.md` (existing v1-eval-report.md is a finalized post-hoc report, not a reusable rubric).*

## 10. End-to-End Validation

- [ ] 10.1 `make up` from a clean checkout brings api + osrm + osrm-prepare + postgres + redis + web all healthy
- [ ] 10.2 Tour-style query (3+ stops): `curl -N "http://localhost:8000/agent/ask?q=plan+a+walk+through+Morningside+Heights+covering+Cathedral+of+St+John+the+Divine,+Riverside+Church,+and+Grant's+Tomb"` produces an SSE stream containing a `tool_call(plan_walk)` event, a `tool_result` for it, and a terminal `walk` frame whose `geometry.type=="LineString"` resolves to a multi-vertex street-following path; `stop_ordering=="tsp_optimized"`
- [ ] 10.3 Tour-style query (2 stops): a query naming exactly two places confirms the `/route` branch fires and `stop_ordering=="input_order"`
- [ ] 10.4 Informational query: `curl -N "http://localhost:8000/agent/ask?q=tell+me+about+the+Cathedral+of+St+John+the+Divine"` produces NO `walk` frame; the stream goes from `citations` to `done`; the agent's session record has `walk_intent_hint=="negative"` and `plan_walk_called==false`
- [ ] 10.5 OSRM down test: stop the `osrm` container and re-run the tour query; confirm the tool succeeds with `routing_backend="haversine_fallback"`, the SSE `walk` frame still arrives with a renderable `geometry` (two-point LineStrings per leg), and the frontend renders a straight-line path
- [ ] 10.6 `make test` passes in `apps/api/.venv` (existing tests stay green; new tests in §3.8, §4.6, §5.3, §6.7 pass)
- [ ] 10.7 Frontend dev server (`npm run dev`) renders the new walk view correctly for a recorded tour fixture; confirm map path follows streets, timeline shows totals, per-stop disclosure expands turn-by-turn

## 11. Cross-Link to initial-palimpsest-scaffold (V1 corrections)

- [x] 11.1 Edit `initial-palimpsest-scaffold/tasks.md` §12.1 to reference the LLM-callable `plan_walk` tool and the routing backend (replacing "server-side post-processing" wording from the prior change)
- [x] 11.2 Edit `initial-palimpsest-scaffold/tasks.md` §12.5 to confirm frontend renders GeoJSON LineString + steps (was "list from server-side §4.4.1")
- [x] 11.3 Note the turn cap raise (6 → 7) in `initial-palimpsest-scaffold/tasks.md` §9.8

## 12. Documentation

- [ ] 12.1 Add a section to root `README.md` describing the new `osrm` and `osrm-prepare` services and the one-time bbox extract step
- [x] 12.2 Update `CLAUDE.md` if any of its locked V1 invariants need amendment: specifically (a) "single-tool surface" → "two tools (search_places, plan_walk)", (b) "Hard turn cap of 6" → "7", (c) "additionally runs server-side `plan_walk` over cited `place_ids` after `done`" → "if the agent called `plan_walk`, the SSE handler relays its tool result as the `walk` frame; otherwise no `walk` frame is emitted"
- [ ] 12.3 Add a short dated note `docs/route-planning-2026-05-04.md` describing the OSRM choice (with `/route` vs `/trip` branching), the GeoJSON-not-polyline rationale, the walk-intent soft-hint pattern, the OSM extract refresh procedure, and the `RoutingBackend` swap-in pattern
