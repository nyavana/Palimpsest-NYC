## MODIFIED Requirements

### Requirement: Fixed tool surface exposed to the agent

For V1, the agent loop SHALL expose **two tools**, `search_places` and `plan_walk`, to the LLM. The remaining tools described in earlier drafts of this spec (`spatial_query`, `historical_lookup`, `current_events`) are deferred to v2 and SHALL NOT be registered with the LLM in V1.

`plan_walk` is now an LLM-callable tool that produces an OSM-routed walking path through 2-8 places the agent has already retrieved via `search_places`. The previous V1 contract — under which `plan_walk` ran as server-side post-processing over `citations[]` after every conversation — is superseded: server-side post-processing is REMOVED, and the `walk` SSE frame is emitted only when the agent has called `plan_walk` during the conversation.

Each tool SHALL have a JSON Schema describing its parameters and return type, and these schemas SHALL be the single source of truth used both for LLM tool-calling and server-side validation. Adding a tool to the V1 surface (re-introducing `historical_lookup`, for example) MUST be done as an explicit spec change, not silently in code.

The agent's system prompt SHALL include explicit dispatch criteria for `plan_walk`: the LLM is instructed to call `plan_walk` ONLY when the user is asking for a tour, route, or directions across two or more distinct places, and to NOT call it for purely informational queries about a single place, comparison questions that do not imply visiting, or queries the user has not asked for a route on. The system prompt MUST also state that citations are drawn from `search_places` results and that `plan_walk` does not contribute new `doc_id`s to the citation pool.

#### Scenario: V1 agent has exactly two registered tools
- **WHEN** the agent loop initializes for a new conversation
- **THEN** the `tools` parameter sent to the LLM contains exactly two entries, named `search_places` and `plan_walk`, and no other tool name appears

#### Scenario: Agent requests an undeclared tool
- **WHEN** the LLM returns a tool call for a name not in the V1 surface (including `historical_lookup`, `current_events`, `spatial_query`, etc.)
- **THEN** the agent loop rejects the call with `UnknownToolError`, appends an error message to the conversation, and the LLM may retry

#### Scenario: Agent does not call plan_walk on an informational query
- **WHEN** the user asks "tell me about the Cathedral of St. John the Divine" and the agent retrieves matching places via `search_places`
- **THEN** the agent emits its final JSON without calling `plan_walk`, and the SSE stream contains no `walk` event

#### Scenario: Agent calls plan_walk for a tour-style query
- **WHEN** the user asks "plan a 30-minute walk through Morningside Heights highlighting the Cathedral, Riverside Church, and Grant's Tomb" and the agent retrieves these three places
- **THEN** the agent issues a `plan_walk` tool call with the three doc_ids in narration order; the SSE stream contains `tool_call(plan_walk)` followed by `tool_result`, and the terminal `walk` frame carries the routed polyline plus per-leg steps

#### Scenario: Multiple plan_walk calls keep only the most recent
- **WHEN** the agent calls `plan_walk` twice in the same conversation, the second time with a refined `place_ids` list
- **THEN** the SSE `walk` frame emitted after `done` corresponds to the second tool result; the first is silently superseded

#### Scenario: Server no longer runs unconditional plan_walk over citations
- **WHEN** an agent conversation completes successfully without calling `plan_walk`
- **THEN** the SSE handler does not invoke `app.agent.walk.plan_walk`, no `walk` event is emitted, and the stream proceeds directly from `citations` to `done`

### Requirement: Agent loop turn cap

The agent loop SHALL enforce a hard turn cap. For V1, the default cap is **7 turns** (raised from 6 to absorb the `plan_walk` round-trip while preserving the existing two-turn retry headroom). Hitting the cap SHALL be a hard failure (`AgentLoopError`) — not a graceful return — so eval can surface runaway loops without confusing them with normal completions.

The final turn (turn `MAX_TURNS_DEFAULT`) SHALL strip the tool surface (`tools=None`), append a "stop searching, emit JSON now" directive to the message log, and request `response_format="json"` with a larger `max_tokens` budget (8192 vs 2048 on tool-call turns) to leave headroom for extended-thinking models.

#### Scenario: Default turn cap is 7
- **WHEN** the agent loop is built without overriding `max_turns`
- **THEN** `loop._max_turns == 7`

#### Scenario: Hitting the cap raises AgentLoopError
- **WHEN** the agent issues tool calls on every turn through turn 7 without producing a parseable final response
- **THEN** the loop raises `AgentLoopError` rather than returning an unverified `AgentResult`

#### Scenario: Final turn strips tools and forces JSON
- **WHEN** the loop reaches turn 7
- **THEN** the chat request to the router has `tools=None`, `response_format="json"`, `max_tokens=8192`, and the message log includes a "stop searching" user directive at the tail

### Requirement: Citation contract enforced at generation time

Narration tool outputs returned to the user SHALL be JSON of the following exact shape:

```json
{
  "narration": "The Cathedral of St. John the Divine was begun in 1892...",
  "citations": [
    {
      "doc_id": "wikipedia:Cathedral_of_Saint_John_the_Divine",
      "source_url": "https://en.wikipedia.org/wiki/Cathedral_of_Saint_John_the_Divine",
      "source_type": "wikipedia",
      "span": "intro",
      "retrieval_turn": 2
    }
  ]
}
```

Each `Citation` SHALL have all five required fields with the following semantics:

- **`doc_id`** (string) — globally unique within the corpus, prefixed by source (e.g., `wikipedia:<page-id>`). MUST equal the `doc_id` of a row already present in the corpus and returned by a retrieval tool on or before `retrieval_turn`. `plan_walk` is NOT a retrieval tool and MUST NOT contribute new `doc_id`s to the ledger; only `search_places` results enter the citation pool.
- **`source_url`** (string) — clickable link the frontend renders next to each citation. MUST be an `https://` URL pointing at a public-domain or open-licensed resource.
- **`source_type`** (enum: V1 = `wikipedia | wikidata | osm`; see `data-ingest` spec for the canonical list) — drives icon and color in the UI. MUST equal the cited document's provenance `source_type` field.
- **`span`** (string, **opaque to the verifier**) — a free-form annotation hint the frontend MAY render (e.g., a sentence number, a section name, an empty string). The verifier does NOT parse or validate this field; it only checks that the field is a string. Sentence-segmentation logic is out of V1 scope.
- **`retrieval_turn`** (integer) — agent loop turn (1-based) on which a retrieval tool returned this `doc_id`. MUST be ≤ the current turn.

The `citations` array MUST be non-empty. The `narration` string MUST be non-empty. The verifier SHALL reject any response that fails any of the per-field rules above; the agent loop retries once with an explicit correction message, and if the retry also fails a visible uncertainty warning is surfaced to the user.

#### Scenario: Narration cites a document that was retrieved
- **WHEN** `search_places` returned a document with `doc_id="wikipedia:Cathedral_of_Saint_John_the_Divine"` on turn 1 and the narration cites it with `retrieval_turn=1`
- **THEN** the citation passes verification and the narration is returned to the user

#### Scenario: Narration cites a document that was NOT retrieved
- **WHEN** the narration cites a `doc_id` that did not appear in any retrieval tool result this turn
- **THEN** the verifier rejects the response, the loop retries once with an explicit correction, and if the retry also fails a visible uncertainty warning is appended

#### Scenario: Narration cites a doc_id only mentioned in a plan_walk tool result
- **WHEN** `plan_walk` accepted a `place_ids` list (passed in by the LLM from prior `search_places` results) and the narration cites a `doc_id` whose only appearance in the conversation is the `plan_walk` arguments
- **THEN** the citation MUST also have been returned by a `search_places` result on or before its `retrieval_turn`; `plan_walk` does NOT add to the retrieval ledger and an attempt to cite a doc_id known only from `plan_walk` arguments fails verification

#### Scenario: Citation references a future retrieval_turn
- **WHEN** the narration emits `retrieval_turn=4` but the agent has only completed 2 turns so far
- **THEN** the verifier rejects the response with a "future retrieval_turn" error, and the standard one-retry-then-warn flow applies

#### Scenario: Citation source_type does not match the cited document's provenance
- **WHEN** the cited document's row has `source_type="osm"` but the citation emits `source_type="wikipedia"`
- **THEN** the verifier rejects the response with a "source_type mismatch" error

#### Scenario: Span field is opaque to the verifier
- **WHEN** a citation has `span="anything-here-even-empty-string"` while all other fields are valid
- **THEN** the verifier accepts the citation; `span` is treated as a frontend annotation hint and not validated

#### Scenario: Empty citations array
- **WHEN** the narration is non-empty but `citations` is `[]`
- **THEN** the verifier rejects the response — uncited narration is forbidden by contract

## ADDED Requirements

### Requirement: plan_walk tool input contract

The `plan_walk` tool SHALL declare a JSON Schema with two parameters:

- `place_ids: array<string>` — required; `minItems=2`, `maxItems=8`. Each entry MUST equal a `doc_id` returned by `search_places` on or before the current turn (validated server-side against the agent's `RetrievalLedger`).
- `mode: string` — optional, default `"walking"`, enum `["walking"]` for V1.

The tool SHALL validate inputs server-side before invoking the routing backend. Validation failures SHALL return structured error messages to the agent (not raise an exception that aborts the loop):

- Fewer than 2 distinct `place_ids` after dedup → `{"error": "too_few_places", "message": "..."}`.
- Any `place_ids[i]` not in the retrieval ledger → `{"error": "unknown_place_id", "place_id": "...", "message": "..."}`.
- `mode` not in the V1 enum → `{"error": "unsupported_mode", "message": "..."}`.

The tool SHALL preserve `place_ids` order (no TSP re-optimization in V1) and SHALL dedupe in-place keeping first occurrence.

#### Scenario: Tool rejects a doc_id that was never retrieved
- **WHEN** the LLM calls `plan_walk(place_ids=["wikipedia:Made_Up_Page"])` and that doc_id is not in the retrieval ledger
- **THEN** the tool returns `{"error": "unknown_place_id", "place_id": "wikipedia:Made_Up_Page", ...}` and the agent loop continues

#### Scenario: Tool rejects fewer than 2 distinct stops after dedup
- **WHEN** the LLM calls `plan_walk(place_ids=["wikipedia:X", "wikipedia:X"])`
- **THEN** the tool returns `{"error": "too_few_places", ...}` and the agent loop continues

#### Scenario: Tool preserves narration order
- **WHEN** the LLM calls `plan_walk(place_ids=[A, B, C])` with three valid distinct doc_ids
- **THEN** the resulting `RouteResult.stops` indexes are `[0, 1, 2]` matching the input order; the routing backend is queried with coordinates in the same order

### Requirement: plan_walk tool output contract

The `plan_walk` tool SHALL return a JSON-serializable object with the following fields:

- `stops: list[Stop]` — same shape as today's `PlannedStop` with fields `index`, `doc_id`, `name`, `lat`, `lon`. The `leg_distance_m` field is REMOVED from `Stop` (replaced by `legs[]`). The order of `stops[]` reflects the *executed* visit order (TSP-optimized when `stop_ordering="tsp_optimized"`, input order when `"input_order"`).
- `legs: list[Leg]` — one entry per consecutive stop pair; each leg has `from_index`, `to_index`, `distance_m`, `duration_s`, `geometry` (GeoJSON LineString), and `steps: list[Step]`.
- `geometry: GeoJSONLineString` — full-route geometry (`{"type": "LineString", "coordinates": [[lon, lat], ...]}`).
- `total_distance_m: int`, `total_duration_s: int` — totals for the full route.
- `routing_backend: "osrm" | "haversine_fallback"` — telemetry tag indicating the backend that produced the result.
- `stop_ordering: "input_order" | "tsp_optimized"` — telemetry tag indicating whether OSRM `/route` (input order) or `/trip` (TSP optimization) produced this result.

This shape MUST match the `walk` SSE frame payload byte-for-byte (the SSE handler serializes the same dataclass). The wire format for geometry MUST be GeoJSON LineString; encoded polyline strings MUST NOT appear anywhere in the tool result.

#### Scenario: Tool result includes GeoJSON geometry and TSP telemetry
- **WHEN** an LLM `plan_walk` call succeeds with 3 valid distinct stops
- **THEN** the resulting tool result contains `stops[]` (length 3, in TSP-optimized order with input first/last pinned), `legs[]` (length 2), `geometry.type == "LineString"`, integer `total_distance_m` and `total_duration_s`, `routing_backend ∈ {"osrm", "haversine_fallback"}`, and `stop_ordering="tsp_optimized"`

#### Scenario: 2-stop tool result preserves input order
- **WHEN** an LLM `plan_walk` call succeeds with exactly 2 valid distinct stops
- **THEN** the tool result has `stop_ordering="input_order"`, `stops[]` length 2 in the input order, and `legs[]` length 1

#### Scenario: AgentResult.walk captures the most recent tool result
- **WHEN** the agent loop completes after one successful `plan_walk` call
- **THEN** `AgentResult.walk` is a `PlannedRoute` dataclass with the fields above; if `plan_walk` was never called, `AgentResult.walk` is `None`

### Requirement: Walk-intent soft hint biases the system prompt

The api SHALL classify each user query into one of three walk-intent labels (`positive | negative | neutral`) using a deterministic regex/keyword classifier `classify_walk_intent(query) -> str` in `apps/api/app/agent/intent.py`. The classifier SHALL be the only intent-detection mechanism in V1 (no model-based classifier, no LLM call).

The classification rules SHALL be:

- `positive` — the query contains any word from `{walk, tour, route, directions, itinerary}` (case-insensitive, word-boundary), OR matches the pattern `from\s+\S.*\s+to\s+\S` (e.g., "from Cathedral to Grant's Tomb").
- `negative` — the query does NOT match any positive pattern AND begins with one of: `tell me|what is|what was|who is|who was|describe|why|when|how does|how is`.
- `neutral` — neither positive nor negative.

The agent loop SHALL append exactly one extra line to the end of its system prompt based on the label:

- `positive` → `"NOTE: The user appears to want a route. After 1-2 search_places calls, strongly prefer calling plan_walk."`
- `negative` → `"NOTE: The user appears to want information about a place. Strongly prefer NOT calling plan_walk."`
- `neutral` → no extra line is appended; the system prompt is unchanged from its base form.

The hint SHALL be a bias only. Both tools (`search_places` and `plan_walk`) SHALL remain registered with the LLM regardless of label; the LLM MAY override the hint when its semantic understanding disagrees with the regex.

The session telemetry record SHALL include the `walk_intent_hint` label and the resulting `plan_walk_called` boolean so a 2×3 confusion matrix (called × hint) can be computed offline.

#### Scenario: Tour-style query gets a positive hint
- **WHEN** the user asks `"plan a walk through Morningside Heights"` and the loop builds the system prompt
- **THEN** `classify_walk_intent(query) == "positive"` and the system prompt ends with the positive NOTE line; the `plan_walk` tool is registered alongside `search_places`

#### Scenario: Informational query gets a negative hint
- **WHEN** the user asks `"tell me about the Cathedral of St. John the Divine"`
- **THEN** `classify_walk_intent(query) == "negative"` and the system prompt ends with the negative NOTE line; both tools remain registered

#### Scenario: Ambiguous query gets a neutral hint and no NOTE line
- **WHEN** the user asks `"Cathedral of St. John the Divine"` (no verb, no keyword)
- **THEN** `classify_walk_intent(query) == "neutral"` and the system prompt has no NOTE line appended

#### Scenario: Hint is a bias, not a gate
- **WHEN** `walk_intent_hint == "negative"` and the LLM nonetheless decides to call `plan_walk`
- **THEN** the loop dispatches the tool normally; no gating logic prevents the call; the telemetry records both the negative hint and `plan_walk_called=true`

#### Scenario: Telemetry captures the 2x3 confusion matrix inputs
- **WHEN** an agent session completes
- **THEN** `SessionRecord.walk_intent_hint ∈ {"positive", "negative", "neutral"}` and `SessionRecord.plan_walk_called ∈ {true, false}`; both fields are present even on errored or warned sessions
