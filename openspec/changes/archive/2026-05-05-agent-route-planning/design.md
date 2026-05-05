## Context

V1 (commit `e1bc76d`, validated 2026-04-29) ships an agent loop with one LLM-callable tool (`search_places`) and an unconditional server-side post-processing pass that walks `citations[]` through a haversine helper. The SSE handler (`apps/api/app/routes/agent.py`) emits the `walk` frame after every successful run. This was a deliberate V1 narrowing (see `swap-llm-tiers-and-lock-mvp-decisions` Decision §7): a one-tool agent is robust to free-tier model tool-calling fidelity, and a deterministic post-processing pass is something the LLM cannot break.

The narrowing has done its job: the loop is reliable, citations verify on the first try in the common case, and the SSE timing budget fits a 6-turn cap (typical end-to-end ≤ 60 s on the paid `moonshotai/kimi-k2.6` model; ~233 s on the verified Riverside Church prompt that exercised the retry path). The MVP demo works.

The post-processing pass, on the other hand, has reached the end of its usefulness:

1. The "leg" it draws is a great-circle straight line. At Manhattan grid scale (≈ 110 m per avenue, 60 m per cross-street), great-circle distance under-counts walking distance by 30-60% on common paths and produces visibly wrong-looking lines (cuts through Riverside Park, the Cathedral close, the Columbia campus).
2. The frontend renders the path unconditionally, which makes informational queries ("tell me about X") look like 1-stop tours. We routinely see one-marker walks emitted for queries with no walk intent — visual noise the user did not ask for.

The fix is a routing-engine-backed `plan_walk` exposed as an LLM tool, with the LLM auto-deciding whether the query warrants a walk. This change is a deliberate widening of the V1 single-tool surface — the locked decision in `swap-llm-tiers-and-lock-mvp-decisions` Decision §7 (one tool only) is being explicitly amended.

## Goals / Non-Goals

**Goals:**

- Replace the unconditional server-side `plan_walk` post-processing with an LLM-callable `plan_walk` tool whose invocation reflects the agent's intent assessment.
- Replace haversine straight-line legs with a real OSM walking route (street-following polyline, per-leg step-by-step instructions, real distance/duration).
- Keep V1's offline-on-localhost demo property: routing must work with `docker compose up` only, no third-party API key required.
- Preserve the existing SSE event contract additively. Frontend code that only reads V1 fields keeps working.
- Keep the citation contract unchanged. The five-field contract for citations is orthogonal to routing and stays locked.
- Stay within the agentic-engineering case-study constraints: every change must be implementable in a single Claude Code session with a clean before/after telemetry record.

**Non-Goals:**

- Not adding more LLM-callable tools beyond `plan_walk`. The other deferred tools (`spatial_query`, `historical_lookup`, `current_events`) remain v2 work and are explicitly NOT re-introduced by this change.
- Not adding multi-modal routing (transit, biking, driving). V1 is foot-only walking. The `mode` parameter exists in the tool schema for forward compatibility but only `walking` is accepted in V1.
- Not adding accessibility-aware routing (avoid stairs, prefer ramps), live-traffic ETAs, or weather-aware routing. These are v2 ideas.
- Not switching the routing backend at request time. The OSRM container is the single V1 backend; the env-driven `OSRM_BASE_URL` lets a v2 deployment swap in a hosted endpoint without code change, but at any given moment the api targets exactly one backend.
- Not exposing route editing, manual stop reordering, or "redo with different stops" UI. The LLM's tool result is final for the turn; a follow-up user message starts a new conversation.

## Decisions

### 1. Routing backend: containerized OSRM

OSRM (`osrm/osrm-backend:v5.27.1`) wins over the alternatives on three V1-relevant axes:

| Backend | Offline-on-localhost | Step-by-step text | Stack fit | Setup cost |
|---|---|---|---|---|
| **OSRM in Docker** | ✓ | ✓ (legs[].steps[].maneuver) | own service, talks HTTP | ~5 min one-time bbox preprocessing |
| OpenRouteService API | ✗ (needs internet + API key) | ✓ | HTTP only, no infra | API key acquisition |
| pgRouting | ✓ | partial (raw ways, no maneuver text) | extends existing PostGIS | days — load OSM ways into topology |
| Valhalla in Docker | ✓ | ✓ | own service, talks HTTP | similar to OSRM, larger image |

OSRM's profile is "do one thing well — shortest-path on a precomputed contraction-hierarchies graph." For a fixed Morningside Heights + UWS bbox, the precomputation is a single ~2-minute step at first volume creation, after which routing is single-digit milliseconds per query. The HTTP API is OpenRouteService-compatible at the `/route/v1/foot/{coords}` shape, which means a v2 swap to ORS is a base-URL change.

We branch on stop count between two OSRM endpoints:

- **2 stops** → `/route/v1/foot/{coords}?steps=true&overview=full&geometries=geojson&annotations=duration,distance` — OSRM's shortest-path response.
- **3-8 stops** → `/trip/v1/foot/{coords}?steps=true&overview=full&geometries=geojson&source=first&destination=last&roundtrip=false` — OSRM's TSP service. `source=first&destination=last` pins the agent's chosen narration anchors so only the *middle* stops are reordered for shortness; `roundtrip=false` matches the walking-tour semantics ("don't loop back to stop 0"). At ≤8 waypoints OSRM uses brute-force optimal TSP; at ≥10 it falls back to farthest-insertion. Our `maxItems=8` cap keeps us in the optimal regime, and the `/trip` branch turns the tool into a near-shortest tour planner with one HTTP call rather than two.

Both endpoints return:

- A **GeoJSON LineString** for the full route geometry (`geometries=geojson`). This is the wire format we hand straight to the frontend; see Decision §2 below for the rationale on why we picked GeoJSON over encoded polyline.
- Per-leg `steps[]` with `maneuver` (location, type, modifier), `name` (street name), `distance`, and `duration`. Each step also carries a GeoJSON `geometry` so a future step-highlight UI can light up a single segment without re-querying.
- For `/trip` only: a `waypoints[].waypoint_index` array describing the optimized visit order. The tool maps this back to the input `place_ids` and emits `stops[]` in the optimized sequence (the tool result is the source of truth; the LLM-supplied input order is the fallback if `waypoints[]` is missing — i.e., when we hit `/route` for the 2-stop case).

Step text is generated by a small Python formatter (`apps/api/app/routing/steps.py`) that renders OSRM maneuvers into English: `"Head east on West 110th Street for 80 m"`, `"Turn right onto Broadway"`, `"Arrive at Cathedral of St. John the Divine"`. We do not call the LLM for step text — it would cost a turn and OSRM's structured maneuvers are deterministic enough.

**Alternatives considered.** ORS public API is the simplest to wire (no Docker), but it requires internet at demo time and an API key in `.env` — the project's V1 has gone to lengths to be online-only via OpenRouter; routing should not re-introduce a second cloud dependency. pgRouting integrates with the existing PostGIS, but the loader (osm2pgrouting) is finicky and the resulting topology is large; the time investment outweighs the integration benefit. Valhalla is more capable than OSRM (e.g., tile-based routing, isochrones) but its container is bigger and its API is bespoke; for V1's "shortest walking path between 2-N points" use case, OSRM is the smaller, sharper tool. (Valhalla *does* generate native multilingual `narrative`/`voiceInstructions` natively — the strongest pro-Valhalla argument — but our scope is English-only NYC and the deterministic Python step formatter in §6 is ~50 LOC.)

### 2. Geometry on the wire: GeoJSON LineString, not encoded polyline

The agent → frontend channel carries the route geometry as **GeoJSON LineString** rather than a Google encoded polyline. This is a deliberate departure from "the obvious efficient choice" because every link in our pipeline either prefers or is indifferent to LineString:

- **MapLibre has no native polyline source.** [maplibre-style-spec discussion #696](https://github.com/maplibre/maplibre-style-spec/discussions/696) confirms that `geojson` is the only pre-built source type for line geometry. Choosing encoded polyline would force a custom JS decoder in the frontend just to feed `addSource({type: "geojson", data: {...}})` — i.e., we'd encode on the api side only to decode on the web side. Round-trip waste.
- **Size delta is small at NYC walking-tour scale and zero after gzip.** A typical pedestrian route in our bbox has ~50-150 OSRM coordinates. Pre-gzip, the LineString is ~3-4× the size of the encoded polyline. Post-gzip (nginx already enables `gzip on` for the SSE stream), the lat/lng repetition compresses extremely well; the per-route overhead drops to a few hundred bytes. Encoded polyline only earns its keep at scale (Mapbox/Google ship millions of routes per second) or in bandwidth-constrained mobile SDKs — neither applies here.
- **Easier debugging.** A LineString shows up readable in browser devtools, in `curl -N` output for SSE smoke tests, and in the `logs/claude-sessions/*.jsonl` telemetry. An encoded polyline is opaque without a tool.
- **No precision footgun.** Encoded polyline at precision 5 truncates to ~1 m grid; precision 6 is ~10 cm but +50% size. We'd have to maintain matching precision constants in two languages and test the round-trip in both. Picking GeoJSON sidesteps the entire question — the LineString carries IEEE-754 doubles end to end.

The api requests `geometries=geojson` from OSRM and forwards the response geometry untouched into `RouteResult.geometry`. The frontend `MapView` reads `walk.geometry` and feeds it to `engine.addPath("walk", coords)` after extracting the coordinate array; no decoder needed.

We retain the option to switch to encoded polyline later if a v2 mobile client surfaces a real bandwidth pinch — the change would be additive (`geometry` stays; `geometry_polyline` joins as an opt-in) and isolated to the routing module.

### 3. OSM extract scope and preprocessing

The OSRM container needs a preprocessed OSM extract. We pull a Geofabrik or BBBike extract for a bbox slightly larger than the V1 corpus bbox (≈ `-74.000, 40.795, -73.955, 40.825`) so paths don't dead-end at the border. The extract is `~5-8 MB` `.osm.pbf`.

Preprocessing happens in a one-shot init container `osrm-prepare` defined in `docker-compose.yml`:

```
osrm-prepare:
  image: osrm/osrm-backend:v5.27.1
  command: bash -c "osrm-extract -p /opt/foot.lua /data/extract.osm.pbf
                  && osrm-partition /data/extract.osrm
                  && osrm-customize /data/extract.osrm"
  volumes:
    - osrm-data:/data
    - ./infra/osrm/extract.osm.pbf:/data/extract.osm.pbf:ro
```

The runtime `osrm` service mounts the same volume read-only and serves on `:5000`:

```
osrm:
  image: osrm/osrm-backend:v5.27.1
  command: osrm-routed --algorithm mld /data/extract.osrm
  volumes:
    - osrm-data:/data
  ports:
    - "5000:5000"
```

`make up` brings both services; `osrm-prepare` exits 0 once preprocessing is done (idempotent — it re-checks output file mtimes). The api container points `OSRM_BASE_URL=http://osrm:5000` by default. A v2 deployment can replace this URL with a hosted endpoint and skip the prepare service.

Disk: ~30-60 MB on the volume after preprocessing. Memory: OSRM uses ~50-150 MB resident on a bbox this small. CPU: < 5% at typical request rates.

**Alternatives considered.** Bundling the preprocessed `.osrm` files in the repo (vs. preprocessing on first run) — rejected because preprocessed binaries are platform-specific (architecture and OSRM minor version) and bloat the repo. Downloading the extract from BBBike at first run (vs. checking it in) — rejected because the demo target is "works on grader's localhost without internet"; checking the small `.osm.pbf` in is acceptable at < 10 MB.

### 4. The `plan_walk` tool contract

The tool schema (the `tools/plan_walk.py` definition the LLM sees):

```json
{
  "name": "plan_walk",
  "description": "Plan a real walking route through the given places, in the order provided. Call this ONLY when the user wants a tour, route, or directions across two or more places. Do NOT call for single-place or purely informational questions.",
  "parameters": {
    "type": "object",
    "required": ["place_ids"],
    "properties": {
      "place_ids": {
        "type": "array",
        "items": {"type": "string"},
        "minItems": 2,
        "maxItems": 8,
        "description": "doc_ids of places returned by search_places, in the desired visit order."
      },
      "mode": {
        "type": "string",
        "enum": ["walking"],
        "default": "walking",
        "description": "V1 supports walking only."
      }
    }
  }
}
```

**Why these bounds.** `minItems=2` makes the tool semantics unambiguous (a one-stop "route" is just a marker, which the citation-driven map already shows). `maxItems=8` is a soft cap on routing latency and OSRM table size; longer chains are unlikely in a 4-8-sentence narration. It also keeps us inside OSRM `/trip`'s brute-force-optimal regime (≤8 waypoints) — beyond 8, OSRM falls back to farthest-insertion which is no longer a true shortest tour.

**Stop ordering and TSP.** For the 2-stop case the agent's input order is the only sensible order. For 3-8 stops we hit `/trip` with `source=first&destination=last`: the agent's narrative anchors (first and last places) are pinned, and OSRM optimizes the *middle* stops for shortest total walk. The tool's emitted `stops[]` reflect the optimized order — the LLM sees the optimized sequence in its tool result and narrates against it. This sidesteps two failure modes at once: (a) the LLM picking a quadratically worse order purely from narration flow; (b) the LLM having to do TSP in its head. Re-ordering as an explicit "shuffle the middle" v2 enhancement (e.g., expose stops the LLM may *not* re-pin) is deferred.

**Tool result shape.** The tool returns:

```json
{
  "stops": [
    {"index": 0, "doc_id": "wikipedia:Cathedral_of_Saint_John_the_Divine",
     "name": "Cathedral of St. John the Divine", "lat": 40.804, "lon": -73.962}
  ],
  "legs": [
    {
      "from_index": 0,
      "to_index": 1,
      "distance_m": 412,
      "duration_s": 295,
      "geometry": {
        "type": "LineString",
        "coordinates": [[-73.962, 40.804], [-73.961, 40.805], "..."]
      },
      "steps": [
        {"instruction": "Head east on West 110th Street for 80 m",
         "distance_m": 80, "duration_s": 60,
         "maneuver_type": "depart",
         "geometry": {"type": "LineString", "coordinates": ["..."]}}
      ]
    }
  ],
  "geometry": {
    "type": "LineString",
    "coordinates": [[-73.962, 40.804], "..."]
  },
  "total_distance_m": 1245,
  "total_duration_s": 890,
  "routing_backend": "osrm",
  "stop_ordering": "tsp_optimized"
}
```

Stops mirror today's `PlannedStop` fields except `leg_distance_m` is replaced by the `legs[]` structure (the leg from stop `i-1` to stop `i` lives at `legs[i-1]`). `stop_ordering ∈ {"input_order", "tsp_optimized"}` is a telemetry tag indicating whether `/route` or `/trip` produced this result. Per-step `geometry` is optional in V1 — the formatter populates it when OSRM provides it but the `legs[].geometry` and full `geometry` are sufficient for rendering.

The agent loop dispatches the tool through the existing `ToolRegistry` plumbing. The tool result is captured into the conversation as a normal `tool` message; the JSON serializes compactly enough that the model's context budget is comfortable. The agent can then narrate the walk citing the same `place_ids` it passed in.

### 5. SSE event flow when `plan_walk` is called

Today: `turn → tool_call(search_places) → tool_result → ... → narration → citations → walk → done` (the `walk` frame is server-emitted post-processing).

After this change: `turn → tool_call(search_places) → tool_result → tool_call(plan_walk) → tool_result → ... → narration → citations → walk → done`.

The `walk` frame is emitted by the SSE handler **only when** the agent loop produced a `plan_walk` tool result this conversation. The handler scrapes the most recent `plan_walk` tool result from the message log (or, equivalently, from a new `walk_tool_result` field on `AgentResult`) and serializes it as the `walk` frame. If no `plan_walk` was called, no `walk` frame is emitted — the SSE stream goes straight to `done`.

The frontend's `useAgentSession` already keys off the presence of `walk` to render the `WalkTimeline`. No behavior change for queries with a walk; informational queries simply stop emitting an empty/single-stop walk.

**Why scrape the tool result vs. plumbing it through `AgentResult`.** Both work. We add a typed `AgentResult.walk: PlannedRoute | None` field so the SSE handler doesn't have to re-parse messages — cleaner and matches how `citations` are surfaced today.

### 6. Removing the unconditional server-side `plan_walk`

`apps/api/app/routes/agent.py` currently calls `plan_walk(session=..., place_ids=[c.doc_id for c in terminal_result.citations])` after every loop completion. That call is removed. The `walk` SSE frame's emission condition flips from "always, after `done` is buffered" to "only if `terminal_result.walk is not None`."

`apps/api/app/agent/walk.py::plan_walk_from_coords` (the haversine helper) is **kept** because:
- The `plan_walk` tool implementation needs to dedupe `place_ids` (LLM may pass duplicates) and look up coordinates the same way today's helper does — those steps are reused.
- It serves as a fallback when OSRM is unreachable: the tool catches the routing error, falls back to the haversine helper, and returns a "best-effort" result with `legs[].geometry` set to a two-point straight LineString and `legs[].steps[]` carrying a single instruction `"Head toward <next stop>"`. The agent sees a structurally identical result, so the failure mode is graceful.

The DB-backed `plan_walk(session, place_ids)` async wrapper in `walk.py` is also kept — the new tool reuses it for the coordinate lookup, then hands the coordinates to the OSRM client.

### 7. System prompt update — the "when to call plan_walk" rubric

The current system prompt locks the agent to one tool. We extend it with explicit dispatch rules:

```
Tools you can call:
  - search_places(query, near?, radius_m?) — required at least once.
  - plan_walk(place_ids, mode="walking") — OPTIONAL. Call only when:
      * The user is asking for a tour, route, or directions, AND
      * You can identify at least 2 distinct places worth visiting.
    Do NOT call plan_walk for purely informational questions about a
    single place ("tell me about X"), comparison questions that do not
    imply visiting ("which is older, X or Y"), or queries the user has
    not asked for a route on.

Workflow:
  1. Search 1-3 times via search_places to gather candidates.
  2. Decide whether to call plan_walk based on the rules above.
  3. If you called plan_walk, the tool result includes `total_distance_m`
     and `legs[].steps[]`; you MAY mention these in narration but MUST
     still emit the final JSON {narration, citations[]} with citations
     drawn from search_places results (NOT plan_walk).
  4. Emit the final JSON. If you did not call plan_walk, citations alone
     drive the user-facing response.
```

The system prompt's existing rule "Every citation MUST reference a `doc_id` returned by `search_places`" is preserved verbatim — `plan_walk` does not contribute new `doc_id`s to the corpus, it only routes through ones already retrieved.

### 8. Turn cap raised from 6 to 7

Today's cap: `MAX_TURNS_DEFAULT = 6`. The empirical V1 budget is ~3 search turns + 1 final narration turn = 4, with 2 turns of headroom for retries.

Adding `plan_walk` as an additional intermediate tool call eats one of those headroom turns. We bump the cap to 7 to keep the same headroom (~2 turns) post-change. The "stop searching, emit JSON now" final-turn directive in `loop.py` remains keyed off `is_final_turn = turn >= self._max_turns`, which adapts automatically.

We do not raise the cap higher: the failure mode of "agent burns turns retrying" is a real one (we saw it on the Riverside Church prompt), and 7 turns is the smallest cap that fits the worst-case productive path without inviting wasteful re-search.

### 9. Frontend changes

`apps/web/src/state/types.ts` adds:
- `RouteStep` and `RouteLeg` (mirroring the tool result shape).
- A `GeoJSONLineString` type alias.
- Updates `PlannedRoute` to add `geometry: GeoJSONLineString`, `legs: RouteLeg[]`, `total_distance_m: number`, `total_duration_s: number`. All optional for backward compatibility.

`apps/web/src/components/MapView.tsx`'s walk-rendering effect reads `walk.geometry.coordinates` and passes them straight to `engine.addPath("walk", coords)` after the standard `[lon, lat] → {lng, lat}` shape conversion. No decoder required — the LineString feeds MapLibre's `geojson` source natively, and the engine's existing `addPath` interface stays unchanged.

`apps/web/src/components/WalkTimeline.tsx` gains an expandable per-leg disclosure: clicking a stop expands a list of `legs[i-1].steps[]` rendered as `1. Head east on West 110th Street for 80 m`. The total distance/duration replaces the current per-leg `m / min` summary with one footer-row total at the bottom of the timeline.

No new npm dependencies. No frontend polyline decoder. The wire format (GeoJSON LineString) is debuggable in browser devtools and in `curl -N` SSE smoke tests without tooling.

### 10. Tool ordering and idempotency

The LLM may call `plan_walk` more than once per conversation (e.g., re-plan after refining its place list). We accept the most recent successful `plan_walk` tool result as authoritative; earlier calls are silently superseded. The `AgentResult.walk` field is overwritten on each successful call.

If the LLM calls `plan_walk` with `place_ids` that include `doc_id`s NOT returned by any prior `search_places`, the tool returns a structured error message back into the conversation (`{"error": "unknown_place_id", "place_id": "...", "message": "doc_id not in retrieval ledger"}`); the LLM may retry. This is the same mechanism `UnknownToolError` uses for off-surface tool names.

If `place_ids` after dedup has fewer than 2 entries, the tool returns `{"error": "too_few_places", "message": "plan_walk requires at least 2 distinct place_ids"}`. This is a parameter validation error; it does not consume the LLM's "stop and emit JSON" budget — the agent loop still continues.

### 11. Walk-intent soft hint (heuristic-as-bias, never gate)

Pure prompt-rule dispatch (Decision §7) is the dominant production pattern (Gemini Maps grounding, Mapbox Location Agent, OpenAI Operator). However, the When2Call (NAACL 2025) and BFCL V4 *irrelevance-detection* benchmarks show that even capable models miscall on this binary at meaningful rates: ~15-30% over-call or refusal-to-call without targeted training. To bring our typical-case error toward zero without adding a second model, we add a **server-side soft hint**:

- A regex over the user query — `\b(walk|tour|route|directions|itinerary)\b|from\s+\S.*\s+to\s+\S` — labels each request as `walk_intent_hint ∈ {positive, negative, neutral}`.
  - Match → `positive` (likely a walk).
  - No match AND query starts with `tell me|what is|who is|describe|why|when|how does` → `negative` (likely informational).
  - Otherwise → `neutral`.
- The agent's system prompt is templated with one extra line at the end:
  - `positive` → `"NOTE: The user appears to want a route. After 1-2 search_places calls, strongly prefer calling plan_walk."`
  - `negative` → `"NOTE: The user appears to want information about a place. Strongly prefer NOT calling plan_walk."`
  - `neutral` → no extra line.

The hint is a **bias, never a gate**. The full `plan_walk` tool is registered every turn regardless of hint label; the LLM is free to override the hint when its semantic understanding disagrees with the regex. This follows the layered-router pattern Arize and the NVIDIA AI Blueprints LLM Router both recommend (cheap heuristic → LLM, never heuristic-as-gate).

**Why not pre-classify and gate?** A gate hides the tool from the LLM and silently fails when the heuristic is wrong. With a hint, the worst case is "we biased the LLM and it overrode us," which is exactly the LLM doing its job. The cost is a few tokens per turn — negligible. The classification surface is small enough (one regex, ~10 hand-curated keywords) that we don't need a model.

**Telemetry.** `SessionRecord` gains `walk_intent_hint: "positive" | "negative" | "neutral"` and `plan_walk_called: bool`. This forms a 2x3 confusion matrix the §13.4 hand-grading harness can use to track over/under-calling separately by hint label. If we see hint-disagrees-with-LLM rates spike or hint-and-LLM-both-wrong rates rise, that's the signal to revisit the rubric.

**Alternatives considered.** A pre-classifier model (BERT-tier or a `complexity=simple` LLM call) is the next-strongest alternative. We rejected it because (a) our tool surface is two tools, not 50, so token-bloat from carrying the tool definition isn't a real cost; (b) the classifier would itself need labeling and evaluation, doubling the eval surface area; (c) miscalibration silently hides the tool, which is a worse failure mode than a wrong soft hint. We could revisit if our offline When2Call-style eval (50 hand-labeled queries; half informational, half tour) shows >15% miscall rate after the hint lands.

## Risks / Trade-offs

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| OSRM container is heavy enough to slow `make up` materially on a fresh checkout | Medium | Low | The runtime image is ~600 MB but it's pulled once. Preprocessing the bbox extract is ~2 min one-time on `osrm-prepare` first run; subsequent `make up` skips it (idempotent on volume mtime). Cache hit makes repeat starts fast. |
| OSM extract for the bbox is missing pedestrian paths the corpus references | Low | Medium | Geofabrik/BBBike extracts are kept current (weekly). For the v1 corpus area (Morningside Heights + UWS), the OSM coverage of pedestrian ways is already excellent — Riverside Park trails, Columbia campus paths, Cathedral close are all mapped. If a citation `doc_id` resolves to a coordinate not on the routing graph, the OSRM `Snap` step finds the nearest edge; we set `radiuses=50` to cap the snap distance and surface a tool error if no edge is within 50 m. |
| OSRM container is unreachable during a request (down, timing out) | Low | Medium | The tool implementation catches HTTP errors and falls back to the haversine helper, returning `legs[].geometry` as a two-point straight LineString and `steps[]` with a single "head toward" instruction. The frontend renders this without any code change. The tool result includes `routing_backend: "osrm" | "haversine_fallback"` so telemetry can detect degradation. |
| LLM calls `plan_walk` for queries that don't warrant one (over-eager) | Low (with hint) | Low | The system prompt's rubric is explicit ("Do NOT call for purely informational questions") and is reinforced per-query by the §11 soft hint when the query reads informational. If we still observe over-calling in eval, we add negative examples to the prompt. Telemetry records `plan_walk_called` and `walk_intent_hint` per session for a 2×3 confusion-matrix view. |
| LLM forgets to call `plan_walk` for queries that DO warrant one (under-eager) | Low (with hint) | Low | Same prompt rubric covers the positive direction; the §11 soft hint nudges positive when keywords like `walk`/`tour`/`route`/`directions` appear. Telemetry distinguishes "hint positive but LLM didn't call" from "hint neutral but should have called." We do not re-introduce server-side post-processing as a backup because that defeats the auto-decide property. |
| §11 soft-hint regex misclassifies a query and biases the LLM the wrong way | Medium | Low | The hint is a *bias* layered on top of LLM judgment, not a gate — the LLM can and does override it. Worst case: the hint marginally degrades a corner-case query the LLM would have nailed unaided; mitigation is removing the failed pattern from the regex, with no tool-surface change. The neutral fallback (no hint line emitted) catches everything the regex doesn't recognize. |
| Raising the turn cap from 6 to 7 lets the agent waste an extra turn searching | Low | Low | The system prompt already says "Plan to finalize by turn 4 at the latest. Excessive searching wastes the user's time." The cap raise is a guardrail, not a permission — empirically, V1 finishes in 3-5 turns, well below the 7-turn cap. |
| OSRM step-text is awkward English ("Continue onto W 110 St for 0 m") | Medium | Low | The step formatter normalizes OSRM maneuver types to a small phrase set ("Head", "Continue", "Turn left/right", "Arrive at"), drops zero-distance steps, and rounds to 5-m precision. Edge cases that look bad in QA become a single PR against `apps/api/app/routing/steps.py`. |
| `plan_walk` tool result inflates the conversation and pushes the next turn over context | Low | Low | A typical `plan_walk` result is ~5-15 KB JSON (4 stops, 6 legs, 30 steps total) with GeoJSON LineString geometry — larger than encoded polyline pre-gzip but still negligible on a 200K-context model and well under the 8K turn budget. Post-gzip on the SSE wire, the size delta vs encoded polyline is a few hundred bytes per route. |
| GeoJSON LineString carries an order-of-magnitude more on-the-wire bytes than encoded polyline | Low | Low | nginx already enables `gzip on` for the SSE stream; lat/lng repetition compresses extremely well. At one walk per query and ~50-150 vertices per route, the absolute bandwidth cost is unmeasurable on localhost and would be a ~1 KB saving per route in production — not worth the round-trip encode/decode the polyline path would require. |
| Existing `apps/api/tests/test_walk.py` becomes stale | Low | Low | The haversine helper it tests is still used as a fallback path. The existing tests stay green; new tests in `test_plan_walk_tool.py` and `test_routing_backend.py` cover the OSRM client (with httpx mock) and the tool-level dispatch. |
| Bumping turn cap or adding a tool changes the Decision §7 lock from `swap-llm-tiers-and-lock-mvp-decisions` | High | Low (this change makes the amendment) | This change is exactly the spec amendment. The MODIFIED `agent-tools` spec in this change re-states the new V1 surface (two tools) and the new turn cap (7). Future spec changes can re-narrow if needed. |

## Migration Plan

1. **Land OpenSpec artifacts** (proposal, design, MODIFIED `agent-tools`, MODIFIED `map-engine`, ADDED `route-planning`, tasks). Run `openspec validate agent-route-planning --strict`.
2. **Add OSM extract and OSRM service**: download the bbox `.osm.pbf` from BBBike (one-time, checked in at `infra/osrm/extract.osm.pbf`); add `osrm-prepare` and `osrm` services to `docker-compose.yml`; document `make up` behavior.
3. **Add the routing backend client**: `apps/api/app/routing/osrm.py` (httpx async client targeting `OSRM_BASE_URL`, branching between `/route` and `/trip`), `apps/api/app/routing/steps.py` (maneuver → English). No polyline codec — the api forwards `geometries=geojson` from OSRM untouched.
4. **Add the `plan_walk` tool**: `apps/api/app/agent/tools/plan_walk.py` implementing the schema in §4. Register in the lifespan-built `agent_tool_registry`.
5. **Add walk-intent soft hint**: `apps/api/app/agent/intent.py` exposing `classify_walk_intent(query) -> Literal["positive", "negative", "neutral"]`. The agent loop builder consumes the label and templates the system prompt accordingly.
6. **Update the agent loop**: bump `MAX_TURNS_DEFAULT` to 7, extend the system prompt with the dispatch rubric, add `walk: PlannedRoute | None` to `AgentResult`, capture the tool result into it.
7. **Update the SSE handler**: drop the unconditional `plan_walk` call; emit the `walk` frame only when `terminal_result.walk is not None`; preserve the existing `walk` payload shape additively.
8. **Update the frontend**: extend `PlannedRoute`, `RouteLeg`, `RouteStep` types in `state/types.ts`; add a `GeoJSONLineString` type alias; teach `MapView` to read `walk.geometry.coordinates` directly into `engine.addPath`; teach `WalkTimeline` to render `legs[].steps[]` on disclosure and the totals footer.
9. **Tests**:
   - Unit: `test_steps.py` (maneuver formatting), `test_routing_backend.py` (httpx mock for OSRM, both `/route` and `/trip` paths), `test_walk_intent.py` (regex coverage on a fixture set of ~30 queries).
   - Integration: `test_plan_walk_tool.py` (full tool dispatch with a mocked routing backend), `test_agent_loop.py` (a fixture conversation where the LLM calls `plan_walk`; one each for hint=positive, negative, neutral).
   - Frontend: a Vitest/RTL snapshot for `WalkTimeline` with a fake walk fixture; `MapView` test asserting it consumes `walk.geometry.coordinates` without any decoder call.
10. **End-to-end smoke**: run the curl command in CLAUDE.md against a tour-style query (`"plan me a 30-minute walk through Morningside Heights highlighting the Cathedral of St. John the Divine, Riverside Church, and Grant's Tomb"`) and confirm: (a) `tool_call(plan_walk)` appears in the SSE stream, (b) the `walk` frame carries `geometry` (GeoJSON LineString) and `legs[].steps[]`, (c) the frontend renders a street-following path that matches the OSRM geometry, (d) for ≥3 stops the result has `stop_ordering="tsp_optimized"`. Run an informational query (`"tell me about the Cathedral of St. John the Divine"`) and confirm no `walk` frame is emitted.
11. **Telemetry**: extend `SessionRecord` with `plan_walk_called: bool`, `routing_backend: str | None`, `stop_ordering: str | None`, and `walk_intent_hint: "positive" | "negative" | "neutral"` so the §13 evaluation harness can grade walk-decision appropriateness with the soft-hint label as a covariate.

Rollback: a single `git revert` reverses the API changes; the `osrm` service can be left in `docker-compose.yml` indefinitely without affecting the api (the api's tool registry decides whether `plan_walk` is registered).

## Open Questions

- **Should `plan_walk` accept a `start` and `end` separate from `place_ids`?** Today the tool walks through `place_ids` in order, with stop 0 as start and stop N-1 as end. A future iteration could accept `start_lat`, `start_lon` so the user's GPS becomes stop 0. V1 keeps it simple: the agent picks the first stop. **Decision: defer to v2.**
- **Should we re-rank stops via TSP for shorter total distance?** Yes — V1 already does, via OSRM `/trip` for ≥3 stops with `source=first&destination=last` pinning the agent's chosen narrative anchors. The 2-stop branch keeps `/route`. **Decision: implemented in V1 of this change; see §1 and §4.**
- **Should the routing tool result carry an isochrone for "what's reachable in 15 minutes"?** Out of scope for V1; a v2 enhancement when the corpus grows past one neighborhood. **Decision: defer to v2.**
- **How does this interact with `complexity` selection?** `plan_walk` is a tool dispatch; the LLM round-tripping through it stays at the same complexity level as the calling turn. We do not flip complexity mid-loop. **Decision: no change to router behavior.**
