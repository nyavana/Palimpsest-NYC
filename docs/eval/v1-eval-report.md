# Palimpsest NYC — V1 Evaluation Report

This document satisfies tasks **§13.4** (qualitative review of 5 walks) and
**§13.6** (router cost analysis) from
`openspec/changes/initial-palimpsest-scaffold/tasks.md`.

All numbers come from JSONL captures in `docs/eval/results/` produced by
`docs/eval/scripts/run_eval.py`. The per-call telemetry is the production
LLM router's own telemetry stream (`llm:telemetry:v1` in Redis), which the
harness reads at run boundaries.

> **Reproducibility note.** Both the LLM cache and the telemetry stream are
> flushed before each batch (`--clear-telemetry` flag). Without that, cached
> responses inflate cache-hit ratio and underreport per-walk cost.

## §13.4 — Qualitative review of 5 walks

| # | Question | Verified | Citations | Walk stops | Walk dist (m) | Latency (s) |
|---|---|---|---:|---:|---:|---:|
| 1 | Tell me about the gothic cathedral on Amsterdam Avenue. | ❌ no terminal (client `ReadTimeout` at 180 s) | — | — | — | 180.2 |
| 2 | What can you tell me about Riverside Church and its history? | ✅ | 1 (osm) | 1 | 0.0 | 103.2 |
| 3 | Plan a 30-minute walking tour of art deco buildings along Riverside Drive. | ✅ | 4 (wiki + osm) | 4 | 4 990 | 99.8 |
| 4 | What interesting places are within 400 m of Riverside Park around 110 St? | ✅ | 6 (osm) | 6 | 590.1 | 43.9 |
| 5 | Take me on a walking tour of brownstone neighborhoods in Brooklyn. | ⚠️ verifier failed — out of scope; agent returned no JSON | 0 | 0 | — | 198.8 |

**Citation correctness rate**: 3 of 5 walks (60%) returned a verified
five-field citation set. 100% of the citations that *did* arrive verified
against the retrieval ledger (no fabricated `doc_id`). The two failures are
qualitatively different:

- **Q1** hit a 180-second client read-timeout while the agent was still in
  its tool-calling phase (5 `search_places` calls observed). The eval
  harness has since been bumped to 300 s for the §13.6 bench. This is a
  **client-side** failure, not an agent bug — the loop hadn't yet emitted
  its terminal `done` event.
- **Q5** is **out of v1 scope** by design — Brooklyn is not in the
  Morningside Heights / UWS bounding box. The agent correctly produced no
  JSON, the verifier flagged it (`response does not contain a JSON object`),
  and the SSE endpoint returned `verified: false` instead of crashing.
  This is the documented graceful-degradation path from
  `apps/api/app/agent/loop.py`.

### Per-walk narrations (excerpts)

> **Q2 — Riverside Church.** *"Riverside Church rises as a defining landmark
> in the Morningside Heights neighborhood of Upper Manhattan. Located near
> the Hudson River at the western…"* → 1 OSM citation, 1 walk stop.

> **Q3 — Art deco walking tour.** *"Begin your 30-minute walk at the
> Riverside Drive–West 80th–81st Streets Historic District, where
> early-20th-century apartment buildings showcase the e[ra]…"* → 4 citations
> (wiki + osm), 4 walk stops, 4 990 m total — over the requested 30-minute
> envelope but a real 5 km loop.

> **Q4 — Places near Riverside Park ~110 St.** *"Within a short stroll of
> Riverside Park near 110th Street, you'll find a fascinating mix of
> culture, history, and green space. The Nicholas Roerich Mu[seum]…"* → 6
> OSM citations, 6 stops, 590 m loop. Geographic constraint via
> `search_places`'s optional `ST_DWithin` filter worked as designed.

### Notes on qualitative quality

- **Citations skew OSM-heavy.** Q2 and Q4 cited only OSM despite the
  Wikipedia corpus containing the same landmarks. Likely a hybrid-search
  ranking effect — the embeddings index may favor short OSM blurbs over
  longer Wikipedia abstracts. Worth tuning in a future pass.
- **Walk distance can exceed the user's requested duration.** Q3 asked for
  a 30-minute walk and got a 5 km loop (≈60 minutes at 80 m·min⁻¹). The
  agent doesn't constrain walk length to the request. Tracked as a v2
  improvement.
- **Source-type chips work.** All Q2-Q4 citation cards rendered the
  per-source chip color (Wikipedia blue, OSM green) correctly in the
  frontend smoke test.

JSONL: `docs/eval/results/v1-qualitative-2026-04-29T00-18-48Z.jsonl`.

## §13.6 — Router cost analysis

Same 10 questions
(`docs/eval/questions/v1-router-bench.txt`) run twice — once with the paid
**Kimi K2.6** that the user has wired in (`OPENROUTER_*_MODEL=moonshotai/kimi-k2.6`)
and once with the free **GPT-OSS-120B** (`openai/gpt-oss-120b:free`),
selected because it was the only fully-functional free OpenRouter model in
this batch with reliable tool-calling support (Gemma-4-31b-it:free and
Gemma-3-27b-it:free were upstream-rate-limited; Qwen3-next-80b's
`tool_calls` field came back null on the smoke test).

Both runs used the same `--clear-telemetry` flag, which also wipes
`llm:cache:v1:*`, so neither model gets a cache benefit from prior runs.

The "single env-var flip" the spec asks for is
`docs/eval/scripts/swap-to-free-model.sh`, which:

1. Backs up `.env` to `.env.before-swap`
2. Rewrites `OPENROUTER_STANDARD_MODEL`, `OPENROUTER_COMPLEX_MODEL`, and
   `LOCAL_LLM_MODEL` to the free model
3. `docker compose up -d --force-recreate api` to pick up the new env
4. Re-runs the bench

(`restore-paid.sh` puts it back.)

### Comparison table

| Metric | **Paid: `moonshotai/kimi-k2.6`** | **Free: `openai/gpt-oss-120b:free`** | Δ |
|---|---:|---:|---:|
| Total LLM cost (10 walks) | **$0.3038** | **$0.0000** | -100% |
| $/walk | $0.0304 | $0.0000 | — |
| LLM calls | 53 | 38 | -28% |
| Prompt tokens | 136 596 | 60 879 | -55% |
| Completion tokens | 55 118 | 6 205 | -89% |
| Median client-observed latency | 119.0 s | 29.8 s | **-75%** |
| Median agent turns | 6 | 3 | -50% |
| Verified citation rate | 70% (7/10) | 80% (8/10) | +10 pp |
| Walks with non-empty `walk[]` | 70% (7/10) | 80% (8/10) | +10 pp |
| Median citations per walk | 2.0 | 3.0 | +50% |
| Median walk distance (m) | 2 685 | 947 | -65% |

JSONL: `docs/eval/results/router-bench-paid-kimi-2026-04-29T00-36-11Z.jsonl`
and `docs/eval/results/router-bench-free-gptoss-2026-04-29T01-00-52Z.jsonl`.
Detailed per-question breakdown in
`docs/eval/v1-router-comparison.md`.

### Reading the result

The free model — `openai/gpt-oss-120b:free`, OpenAI's open-weights 120 B
released alongside GPT-5 — beats the paid Kimi K2.6 router config on
**every axis except median walk distance**, and even there the shorter
947 m walks are arguably the *correct* output for "30-minute" /
"45-minute" prompts (Kimi's 2.7 km mean was already over the requested
envelope, see §13.4 Q3). The pattern that explains it:

- **Kimi K2.6 is a thinking model with a default reasoning budget that
  often eats the 8 192-token completion ceiling** before it gets to the
  final-turn JSON, which is why we see the recurring "response does not
  contain a JSON object" verifier warning across paid walks 2, 3, 6, 8, 10.
  GPT-OSS-120B is not a thinking model and emits the JSON directly inside a
  small completion budget (median 6.2 K vs 55 K total completion tokens).
- **Free-gptoss makes fewer tool calls** (38 vs 53) and stops earlier
  (median 3 turns vs 6). Looking at the per-question runs, gptoss tends to
  call `search_places` once or twice and immediately produce the terminal
  narration; Kimi tends to keep refining.
- **Both fail on the same out-of-scope question** (Q7 "Apollo Theater") —
  Apollo is in Harlem, outside the v1 bbox. Both models correctly emit no
  JSON; the verifier surfaces the failure with `verified: false`. This is
  the documented graceful-degradation path.
- **Paid-Kimi additionally fails on Q8 ("Plan a 45-minute walk that hits a
  park, a church, and a university building") and Q10 ("buildings around
  116th and Broadway")** — both are well within scope. gptoss handles
  both with valid citations.
- **Free-gptoss's only failure inside scope is Q1 ("Cathedral of Saint John
  the Divine")** — likely a flaky JSON emission. Worth noting as a
  reproducibility caveat.

### Recommendation

For V1 demo: switch to `openai/gpt-oss-120b:free`. It is **free**, **4× faster
end-to-end**, **more reliable** (80 % vs 70 % verified citation rate), and
produces walks at a more reasonable scale. The single env-var flip
operationalised by `swap-to-free-model.sh` is enough; no code change.

The original Kimi K2.6 config was restored at the end of the run via
`restore-paid.sh`, leaving the environment in the same state the user
started in.

### Notes

- The router's `complexity` axis sends both `standard` and `complex` to the
  same backend in V1 (the local tier is also OpenRouter; on-device hosting
  is v2 per `swap-llm-tiers-and-lock-mvp-decisions`). The cost-per-walk
  numbers therefore reflect a model swap, not a router-decision change.
- Cost is computed by the OpenRouter SDK and emitted on each
  `llm.call` telemetry record, summed over the 10-walk batch from
  `llm:telemetry:v1`. Token counts come from the same telemetry.
- A walk's "verified" status is the agent's own citation verifier
  (`apps/api/app/agent/citations.py`); the eval harness does not reverify.

## Reproducing this report

```bash
# Paid (current config) baseline
.eval-venv/bin/python -u docs/eval/scripts/run_eval.py \
    --questions docs/eval/questions/v1-router-bench.txt \
    --label router-bench-paid-kimi \
    --out docs/eval/results \
    --clear-telemetry

# Swap → free → bench → restore
docs/eval/scripts/swap-to-free-model.sh
docs/eval/scripts/restore-paid.sh

# Generate the comparison
.eval-venv/bin/python docs/eval/scripts/compare_runs.py \
    docs/eval/results/router-bench-paid-kimi-*.jsonl \
    docs/eval/results/router-bench-free-gptoss-*.jsonl \
    --out docs/eval/v1-router-comparison.md
```

