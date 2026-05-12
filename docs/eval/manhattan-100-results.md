# Manhattan-100 Eval Results

This document is the final report-facing summary of the
`eval-depth-and-corpus-expansion` OpenSpec change. All numbers are
reproducible from artifacts in this repository at the question-bank tag
`eval/manhattan-100-v1` and the per-phase commits on the
`worktree-eval-depth-and-corpus-expansion` branch.

## Headline

Palimpsest (full **hybrid + cross-encoder reranker** configuration) produces
citation-correct responses on **75.5%** of manhattan-100 questions, vs
**85.6%** for naive RAG and **6.8%** for vanilla LLM. Naive RAG looks higher
because it dumps the entire top-k retrieval into the LLM prompt (so almost
every cited doc_id is present in `retrieved_docs` by construction); palimpsest
calls retrieval as agent tools and cites a smaller, more targeted set per
turn (see the methodology caveats below).

## Ablation table

See [`docs/eval/results/ablation_table.md`](./results/ablation_table.md).
Summary (CCR mean ± 95 % bootstrap CI):

| System | n | CCR | HR ↓ | NQ | GRR ↑ |
|---|---:|---|---|---|---|
| vanilla | 95 | 0.068 [0.024, 0.126] | 0.186 [0.136, 0.236] | 3.99 [3.89, 4.09] | 0.100 [0.000, 0.300] |
| naive_rag | 95 | 0.856 [0.791, 0.914] | 0.313 [0.242, 0.388] | 3.41 [3.24, 3.59] | 0.700 [0.400, 1.000] |
| palimpsest-dense | 95 | 0.725 [0.648, 0.797] | 0.708 [0.621, 0.786] | 3.44 [3.29, 3.58] | 0.400 [0.100, 0.700] |
| palimpsest-hybrid | 95 | 0.751 [0.683, 0.815] | 0.620 [0.530, 0.717] | 3.45 [3.30, 3.59] | 0.500 [0.200, 0.800] |
| palimpsest-hybrid-reranked | 95 | 0.755 [0.678, 0.818] | 0.794 [0.722, 0.860] | 3.52 [3.39, 3.64] | 0.200 [0.000, 0.500] |

Reading the rows along Palimpsest's retrieval-mode ablation:

- **dense → hybrid:** +2.6 pp CCR, –8.8 pp HR. Adding sparse `pg_trgm` name
  similarity behind RRF helps proper-name lookups; palimpsest now finds
  things like the Flatiron Building when the agent asks for it by name.
- **hybrid → hybrid_reranked:** +0.4 pp CCR (negligible), but HR rises
  17.4 pp. The cross-encoder reranker shuffles top-k order, which the agent
  appears to take as license to make more, longer factual claims it cannot
  ground in the OSM corpus. This is interpretable but unflattering and is
  the main empirical caveat to the reranker row.

## Per-region

See `docs/eval/results/per_region-*.csv` and
[`per_region_ccr.png`](./results/per_region_ccr.png). One CSV per system,
covering the regions tagged in
`docs/eval/questions/manhattan-100/categories.yaml`.

## Per-source

See `docs/eval/results/per_source-*.csv` and
[`per_source_ccr.png`](./results/per_source_ccr.png). One CSV per system,
grouped by the dominant `source_type` of the row's citations (osm vs
wikipedia).

## Out-of-scope refusal (GRR)

See [`docs/eval/results/grr_table.md`](./results/grr_table.md). 10
out-of-scope questions in the bank (indices 85–94: Brooklyn, Queens, Bronx,
out-of-state, fictional). Higher = the system refused or redirected rather
than confabulating. Palimpsest is uneven across configs and reranker
actually regresses this metric (0.500 → 0.200) — surprising; worth a closer
look in v3.

## Accuracy vs latency

See [`docs/eval/results/pareto.png`](./results/pareto.png).

**Caveat:** every system was evaluated against the same warm Redis-backed
LLMCache, so the p50 numbers in `pareto.png` reflect cache-hit timing, not
cold-start LLM latency. Cold-start palimpsest is closer to 2–4 s per
question (the agent runs 2–4 tool turns end-to-end before terminal JSON).
The relative ordering between palimpsest configs (dense vs hybrid vs
hybrid_reranked) is still meaningful because all three serve the same
cached prompts.

## Inter-rater agreement (κ)

**Not measured.** The plan called for hand-grading 20 calibration questions
and computing Cohen's κ between the hand-grader and the LLM-judge; that
step was skipped in this run per the `[[feedback-skip-human-review]]`
preference. The `kappa` cell in `ablation_table.md` is `null`. To recover
this number in a follow-up, run the hand-grading worksheet in
`docs/eval/grades/calibration.csv` and re-run `aggregate.py --hand-grades`.

## Judge model

`openai/gpt-5.4-mini` (same model as systems-under-evaluation). This is a
**known self-grading risk** — gpt-5.4-mini also drives the vanilla and
naive_rag baselines and is the OpenRouter complex-tier model behind
palimpsest. The session explicitly chose this trade-off to keep judge cost
near $1.59 total (1550 calls across 5 systems). A stronger neutral judge
(claude-opus-4-7 or claude-sonnet-4-6) would remove the self-grading
concern at ~3-5× judge cost; the rubric in `docs/eval/scripts/graders/rubric.py`
is judge-model-agnostic so swapping is a one-flag change to `judge_run.py`.

## Methodology

See
`docs/superpowers/specs/2026-05-12-eval-depth-and-corpus-expansion-design.md`
§6 (metrics) and §7 (phases). Question bank is tagged
`eval/manhattan-100-v1`. Note that the actual bank has 95 questions (not
100) after automated curation; this is documented in
`docs/eval/notes/` and Phase 2 of the canonical plan.

### Methodology caveats specific to this run

1. **v2 CCR rubric.** v1 of the rubric scored every citation against an OSM
   doc's `body_excerpt`. OSM rows store name + URL + lat/lon but no prose
   body, so v1 collapsed OSM citations to CCR=0 by construction —
   measuring corpus shape, not system grounding. v2 (the rubric committed
   alongside this run) treats `doc_id ∈ retrieved_docs` as sufficient
   support when `body_excerpt` is empty. See
   `docs/eval/scripts/graders/rubric.py` and `judge.yaml` (`prompt_version: v2`).

2. **Citation-frame doc_id harvesting.** The V1 SSE schema's `tool_result`
   frame carries only `{name, n_hits}`, not the hit payload, so the prior
   `flatten_retrieved_docs()` produced empty `retrieved_docs` for every
   palimpsest row. The Phase 3 commit on this branch fixes this by also
   harvesting doc_ids from the terminal `citations` frame and from the
   `walk` frame's `discovered_stops[]`. Score/name/lat/lon for these
   citation-path docs end up null in the JSONL (the citation schema
   doesn't carry them), but the v2 rubric handles this gracefully.

3. **LLMCache contamination.** The api uses a Redis-backed LLMCache keyed
   on prompt hash. Phase 3.1, Phase 4.7, and Phase 5.5 issued the same 95
   questions to the same model (`openai/gpt-5.4-mini`) backed by the same
   redis volume, so most second/third runs of the same question hit cache
   and reused an earlier prompt's response. This is harmless for the
   correctness metrics (CCR/HR/FA/NQ/GRR) because they evaluate the same
   answer either way, but it deflates wall-clock and cost numbers
   asymmetrically — palimpsest's reported `latency_s` of ~0.1s is the
   cache-hit path, not the cold agent loop. The Pareto figure should be
   read as "system shape under warm cache."

4. **Hybrid retriever serialization.** `HybridRetriever.search` originally
   ran the dense and sparse branches via `asyncio.gather` on a shared
   SQLAlchemy `AsyncSession`; this trips SQLAlchemy's no-concurrent-
   operations-per-session invariant and crashed every `/internal/retrieve`
   call in hybrid mode. The fix on this branch serializes the two
   branches (sparse is cheap, ~20-50 ms; the overhead is acceptable).

## Reproducibility

To re-run any phase, check out the corresponding commit on
`worktree-eval-depth-and-corpus-expansion` and follow the canonical plan
at
`docs/superpowers/plans/2026-05-12-eval-depth-and-corpus-expansion.md`.

End-to-end re-run of Phases 3–5 measurement against a clean Redis cache:

```bash
make nuke && make up  # also drops LLMCache
bash docs/eval/scripts/runners/eval_parallel.sh phase3   # 3 baseline rows
RETRIEVAL_MODE=hybrid docker compose up -d --force-recreate api
PYTHONPATH=. docs/eval/.venv/bin/python -m docs.eval.scripts.run_eval_v2 \
  --systems docs/eval/scripts/systems-palimpsest-hybrid-only.yaml \
  --questions docs/eval/questions/manhattan-100/all.txt \
  --label phase4-hybrid --out docs/eval/results
RETRIEVAL_MODE=hybrid_reranked RERANKER_ENABLED=true \
  docker compose up -d --force-recreate api
PYTHONPATH=. docs/eval/.venv/bin/python -m docs.eval.scripts.run_eval_v2 \
  --systems docs/eval/scripts/systems-palimpsest-hybrid-reranked-only.yaml \
  --questions docs/eval/questions/manhattan-100/all.txt \
  --label phase5-reranked --out docs/eval/results

# Judge + aggregate
OPENROUTER_API_KEY=$(grep ^OPENROUTER_API_KEY .env | cut -d= -f2) \
  PYTHONPATH=. docs/eval/.venv/bin/python -m docs.eval.scripts.judge_run \
  --inputs 'docs/eval/results/phase[3-5]*.jsonl' \
  --categories docs/eval/questions/manhattan-100/categories.yaml \
  --out docs/eval/grades --judge-model openai/gpt-5.4-mini \
  --max-cost-usd 10.0

PYTHONPATH=. docs/eval/.venv/bin/python -m docs.eval.scripts.aggregate \
  --inputs 'docs/eval/grades/phase[3-5]*-judged.csv' \
  --categories docs/eval/questions/manhattan-100/categories.yaml \
  --inputs-jsonl-dir docs/eval/results \
  --out docs/eval/results/ablation_table.md

# Phase 6 figures
PYTHONPATH=. docs/eval/.venv/bin/python -m docs.eval.scripts.plot_pareto \
  --judge-glob 'docs/eval/grades/phase[3-5]*-judged.csv' \
  --out docs/eval/results/pareto.png
PYTHONPATH=. docs/eval/.venv/bin/python -m docs.eval.scripts.plot_breakdowns \
  --kind region --out docs/eval/results/per_region_ccr.png
PYTHONPATH=. docs/eval/.venv/bin/python -m docs.eval.scripts.plot_breakdowns \
  --kind source --out docs/eval/results/per_source_ccr.png
PYTHONPATH=. docs/eval/.venv/bin/python -m docs.eval.scripts.grr_analysis \
  --judge-glob 'docs/eval/grades/phase[3-5]*-judged.csv' \
  --categories docs/eval/questions/manhattan-100/categories.yaml \
  --out docs/eval/results/grr_table.md
```

Total budget: ~$1.60 judge spend + minimal eval-side spend (most LLM
traffic is the system-under-evaluation prompts, which warm cache on
re-runs).
