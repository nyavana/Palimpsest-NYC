# §13.4 — Walk Hand-Grading Checklist

This checklist is the per-walk grading rubric for the qualitative review of
5 walks (per `openspec/changes/initial-palimpsest-scaffold/tasks.md` §13.4
and `openspec/changes/swap-llm-tiers-and-lock-mvp-decisions/tasks.md`
§4.5.4). The previous (pre `agent-route-planning`) version of §13.4 — the
free-form report at `docs/eval/v1-eval-report.md` — recorded a one-shot run
and is a historical artifact; this file is the re-runnable rubric for
future grading passes after the route-planning amendment lands.

## How to use

1. Run the eval harness (`docs/eval/scripts/run_eval.py`) on the 5
   hand-curated questions in `docs/eval/questions/v1-qualitative.txt`.
2. For each walk, fill the table below with one row. The first six columns
   come from the existing V1 rubric; the last two are added by the
   `agent-route-planning` change to track over/under-call rates of
   `plan_walk` separately by walk-intent hint.
3. Roll up totals at the bottom. Report citation-correctness rate and
   walk-decision-appropriate rate as separate percentages.

## Per-walk grading table

| #  | Question (truncated) | Verified | Citations correct | Walk stops sensible | Geometry follows streets | Walk decision appropriate | Hint correct |
|----|----------------------|---------:|:-----------------:|:-------------------:|:------------------------:|:-------------------------:|:------------:|
| Q1 |                      |          |                   |                     |                          |                           |              |
| Q2 |                      |          |                   |                     |                          |                           |              |
| Q3 |                      |          |                   |                     |                          |                           |              |
| Q4 |                      |          |                   |                     |                          |                           |              |
| Q5 |                      |          |                   |                     |                          |                           |              |

### Column definitions

- **Verified** — `result.verified == true` from the SSE `done` payload
  (i.e. the citation verifier accepted the response).
- **Citations correct** — every citation row's `doc_id` resolves to a real
  document, the cited `span` is at least loosely supported by the
  document's text, and `source_type` matches provenance. Yes/No.
- **Walk stops sensible** — when a walk is emitted, are the stops
  geographically and thematically reasonable for the user's query? Yes /
  No / N/A (no walk emitted).
- **Geometry follows streets** — when a walk is emitted, does the
  rendered path follow streets (post-route-planning) rather than
  cut through buildings (haversine straight lines)? Yes / No / N/A.
  If `routing_backend == "haversine_fallback"` in the SessionRecord this
  is allowed to be No, with the fallback noted in the comments.
- **Walk decision appropriate** *(added by `agent-route-planning` §9.3)* —
  was the agent's call/no-call on `plan_walk` correct given the user's
  intent? Yes/No. A "tour"/"plan a walk"/"directions" prompt should
  produce a walk; a "tell me about X" prompt should not. This is the
  primary signal for over/under-calling.
- **Hint correct** *(added by `agent-route-planning` §9.3)* — did the
  regex-driven `walk_intent_hint` (`positive | negative | neutral`,
  recorded in the SessionRecord) match the human grader's reading of the
  query? Yes/No. Disagreements feed back into the regex in
  `apps/api/app/agent/intent.py`.

## 2x3 confusion matrix (computed offline from SessionRecord JSONL)

After grading, cross-tabulate `walk_intent_hint` × `plan_walk_called`
across all 5 walks:

|                          | hint=positive | hint=neutral | hint=negative |
|--------------------------|--------------:|-------------:|--------------:|
| `plan_walk_called=true`  |               |              |               |
| `plan_walk_called=false` |               |              |               |

**Watch for:**

- `hint=positive ∧ called=false` — under-calling. Either the regex
  fired but the LLM rejected the hint, or the user prompt is genuinely
  ambiguous despite a keyword match.
- `hint=negative ∧ called=true` — over-calling. The LLM ignored the
  negative hint; if this happens repeatedly on truly informational
  prompts, tighten the system-prompt rubric.
- `hint=neutral` rows — neither bias was applied; the LLM's call/no-call
  is purely its own judgment. These are the cleanest signal of base-rate
  decision quality.

## Source data

For each walk, the SessionRecord written to `logs/claude-sessions/*.jsonl`
contains the four fields the matrix needs:

```jsonc
{
  "plan_walk_called": true,
  "routing_backend": "osrm",
  "stop_ordering": "tsp_optimized",
  "walk_intent_hint": "positive"
}
```

## Historical reference

The first hand-grading pass (pre route-planning, captured 2026-04-29) is at
`docs/eval/v1-eval-report.md` §13.4 and recorded "3/5 walks verified, 60%
citation correctness". Re-running this rubric after the route-planning
amendment lands updates the rate and adds the two new columns above.
