# Phase 0 smoke run — 2026-05-12

Smoke run of the new eval harness against the existing 10-question
`v1-router-bench.txt` on the MH/UWS V1 corpus.

## Configuration

- Systems: vanilla, naive_rag, palimpsest-dense (3 of 5; hybrid + reranker
  variants deferred until Phases 4–5 land).
- Systems config: `docs/eval/scripts/systems-phase0-smoke.yaml`.
- Models: `moonshotai/kimi-k2.6-20260420` for baselines, agent loop uses
  whatever the api router picks (kimi for standard/complex).
- API_BASE_URL: `http://localhost:8000` (single-host stack).
- 10 questions × 3 systems = 30 calls. ~$0.20 actual OpenRouter spend.

## Outputs

| System            | rows | errors | empty_narration | retrieved_docs (per row) | citations (per row) |
|-------------------|------|--------|-----------------|--------------------------|---------------------|
| vanilla           | 10   | 1      | 1               | 0 (correct, no retrieval)| 0–4                 |
| naive_rag         | 10   | 5      | 5               | 0 or 8                   | 0–8                 |
| palimpsest-dense  | 10   | 0      | 0               | **0 (BUG, see below)**   | 1–6                 |

## What worked

- The orchestrator dispatched all 3 systems sequentially and wrote one
  JSONL each under `docs/eval/results/phase0-smoke-*.jsonl` with
  header/row/footer framing.
- The row schema is consistent across systems: `narration`, `citations`,
  `retrieved_docs`, `latency_s`, `error` all present in every row.
- `/internal/retrieve` and `/internal/documents/by_ids` returned correctly
  populated `body_excerpt` for wikipedia rows after fixing a SQL join bug
  (places→documents prefix mismatch; see commit immediately preceding
  these artifacts).

## Known issues (not blockers for Phase 1)

### 1. `palimpsest.retrieved_docs` is always empty

Root cause: the v1 SSE `tool_result` frame from `/agent/ask` carries only
`{name, n_hits}` (see `apps/api/app/agent/loop.py:289-292`). The actual
hit payload (`SearchPlaceHit` records) lives in the agent's in-process
ledger and never crosses the SSE boundary. The canonical plan
(`docs/superpowers/plans/2026-05-12-eval-depth-and-corpus-expansion.md`
§Task 0.5) assumed the full result lived in `tool_result.data.result`,
which is not the case for the locked V1 contract.

**Implication for grading**: HR (hallucination rate) cannot distinguish
"agent saw a doc but didn't cite it" from "agent never saw the doc",
because the only doc_ids the eval can observe are the cited ones.

**Mitigation options** (pick before Phase 3):
- Fallback to citations as the retrieved-set proxy in
  `flatten_retrieved_docs(...)` — undercounts HR denominator but stays
  on locked V1 contract.
- Add a `/internal/last-retrieval/{request_id}` endpoint that exposes
  the ledger keyed by X-Request-ID. Requires plumbing the request_id
  through `AgentLoop` and a small TTL cache; no SSE schema change.
- Wide the `tool_result` SSE frame to include the hit payload behind a
  flag (`?include_tool_results=true`). Modifies SSE schema; against the
  locked-contract guidance.

### 2. Naive RAG has ~50% JSON-parse failure rate

`run_naive_rag` asks the LLM for a JSON envelope; in ~5/10 calls the
model returned non-JSON (raw narrative text or fenced code). Tightening
the system prompt (explicit JSON-only with no surrounding prose, plus
`response_format=json` if the OpenRouter passthrough supports it) should
fix this before Phase 3.

### 3. `llm_cost_usd` reads zero for vanilla / naive_rag

OpenRouter's `usage.total_cost` was not in the response payload for
kimi-k2.6 on these calls; need to inspect the raw OpenRouter response
to map cost reliably (it may come back as `usage.cost` instead, or only
when `?include_usage=true` is set on the request).

## Decision

These issues do **not** block Phase 1 (corpus widening). They are real
problems to fix before Phase 3 measurement, where the headline numbers
need accurate `retrieved_docs` and `llm_cost_usd`. The plumbing
end-to-end is validated by this smoke run.

Hand-vs-judge κ check skipped per ongoing project preference (see
[[feedback-skip-human-review]] in agent memory).
