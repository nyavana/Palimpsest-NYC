## ADDED Requirements

### Requirement: Fixed tool surface exposed to the agent

The agent loop SHALL expose a fixed set of tools to the LLM: `search_places`, `spatial_query`, `historical_lookup`, `current_events`, and `plan_walk`. No new tool MAY be added without a corresponding spec update. Each tool SHALL have a JSON Schema describing its parameters and return type, and these schemas SHALL be the single source of truth used both for LLM tool-calling and server-side validation.

#### Scenario: Agent requests an undeclared tool
- **WHEN** the LLM returns a tool call for a name not in the fixed list
- **THEN** the agent loop rejects the call with `UnknownToolError`, appends an error message to the conversation, and the LLM may retry

### Requirement: Deterministic turn cap

The agent loop SHALL enforce a maximum of 6 tool-calling turns per user message by default, configurable via `AGENT_MAX_TURNS`. When the cap is reached the loop SHALL return whatever narration it has and SHALL NOT make further tool calls.

#### Scenario: Turn cap reached mid-plan
- **WHEN** the agent has made 6 tool calls without producing a final narration
- **THEN** the loop returns a response with `truncated=true` and a partial-tour warning surfaced to the user

### Requirement: Citation contract enforced at generation time

Narration tool outputs returned to the user SHALL be JSON-structured with a `narration` string and a non-empty `citations` array. Each citation SHALL reference a `doc_id` that was actually returned by a retrieval tool in the current turn. A verifier SHALL reject responses that cite documents not present in the current retrieval context.

#### Scenario: Narration cites a document that was retrieved
- **WHEN** `historical_lookup` returned a document with `doc_id="chronicling-america:nytribune:1892-12-27:p3"` and the narration cites it
- **THEN** the citation passes verification and the narration is returned to the user

#### Scenario: Narration cites a document that was NOT retrieved
- **WHEN** the narration cites a `doc_id` that did not appear in any retrieval tool result this turn
- **THEN** the verifier rejects the response, the loop retries once with an explicit correction, and if the retry also fails a visible uncertainty warning is appended

### Requirement: All tools route through the LLM router for any LLM calls

Tools that internally use an LLM (e.g., `plan_walk` may use a cloud LLM to select interesting stops) SHALL obtain their LLM access through the shared `LLMRouter`, never through a hardcoded adapter. This guarantees all calls are telemetered, cached, and circuit-broken consistently.

#### Scenario: plan_walk uses the router
- **WHEN** the `plan_walk` tool makes an LLM call to score POI variety
- **THEN** the call goes through `router.chat(...)` and appears in the router telemetry stream

### Requirement: Tools are pure with respect to database side effects

Tools MUST NOT write to the `places` or `documents` tables. Writes are the responsibility of ingestion pipelines only. Tools may write to the `agent_sessions` table for conversation state and MAY cache intermediate computations in Redis, but SHALL NOT mutate the canonical corpus.

#### Scenario: Tool attempts to insert into places table
- **WHEN** a bug causes a tool handler to call `session.add(Place(...))` and commit
- **THEN** an ORM-level event listener raises `CorpusWriteForbiddenError` and aborts the transaction
