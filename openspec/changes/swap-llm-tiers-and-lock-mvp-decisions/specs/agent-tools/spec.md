## MODIFIED Requirements

### Requirement: Fixed tool surface exposed to the agent

For V1, the agent loop SHALL expose **a single tool**, `search_places`, to the LLM. The remaining tools described in earlier drafts of this spec (`spatial_query`, `historical_lookup`, `current_events`, `plan_walk`) are deferred to v2 and SHALL NOT be registered with the LLM in V1.

`plan_walk` is **not removed from the system** — it becomes server-side machinery. After the agent emits its final response, the server SHALL run a deterministic PostGIS routing pass over the place_ids referenced in `citations[]` to produce an ordered walking route, which the frontend renders as a path with markers. The agent does not call this routing pass; the LLM never sees it as a tool.

Each tool SHALL have a JSON Schema describing its parameters and return type, and these schemas SHALL be the single source of truth used both for LLM tool-calling and server-side validation. Adding a tool to the V1 surface (re-introducing `plan_walk` as a callable tool, for example) MUST be done as an explicit spec change, not silently in code.

#### Scenario: V1 agent has exactly one registered tool
- **WHEN** the agent loop initializes for a new conversation
- **THEN** the `tools` parameter sent to the LLM contains exactly one entry, named `search_places`, and no other tool name appears

#### Scenario: Agent requests an undeclared tool
- **WHEN** the LLM returns a tool call for a name not in the V1 surface (including `plan_walk`, `historical_lookup`, etc.)
- **THEN** the agent loop rejects the call with `UnknownToolError`, appends an error message to the conversation, and the LLM may retry

#### Scenario: Server-side route planning runs after agent completion
- **WHEN** the agent emits its final response with `citations[]` referencing N place_ids
- **THEN** the server runs PostGIS routing over those place_ids without invoking the LLM, returns an ordered route to the frontend, and the agent's narration order is preserved as the visit order

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

- **`doc_id`** (string) — globally unique within the corpus, prefixed by source (e.g., `wikipedia:<page-id>`). MUST equal the `doc_id` of a row already present in the corpus and returned by a retrieval tool on or before `retrieval_turn`.
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
