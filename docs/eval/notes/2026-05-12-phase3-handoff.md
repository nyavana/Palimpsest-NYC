# Phase 3+ Session Handoff — 2026-05-12

Stopping mid-Phase-3 to start a fresh session with cleaner context. This
note captures everything the next session needs to pick up cleanly.

## Where we are

### Committed (on `worktree-eval-depth-and-corpus-expansion`)

```
588ddd5 feat(eval): Phase 2 — manhattan question bank (95Q, pre-registered)
fb73535 feat(corpus): Phase 1 — widen SCOPE_BBOX to Manhattan + re-ingest
aea421a test(eval): Phase 0 smoke run + body_excerpt JOIN fix
aebf240 feat(eval): Phase 0 — eval harness scaffold + /internal/retrieve
```

Plus the upcoming "Phase 4 retrieval modules" commit (this handoff session).

### Done in the previous session (committed in the handoff bundle)

- Phase 0: eval harness scaffold (3 baselines, grader, clients, orchestrator,
  /internal/retrieve route, /internal/documents/by_ids route, smoke run)
- Phase 1: SCOPE_BBOX widened to Manhattan; re-ingest produced
  **12,858 OSM + 492 wikipedia + 456 wikipedia docs**
- Phase 2: 95-question bank synthesized + auto-curated; tagged
  `eval/manhattan-100-v1`. Bank is at
  `docs/eval/questions/manhattan-100/all.txt`
- Phase 4: tasks 4.1 (DenseRetriever extract), 4.2 (SparseRetriever),
  4.3 (RRF fusion k=60), 4.4 (HybridRetriever) — code + tests landed
- Phase 5: tasks 5.1 (Reranker singleton), 5.2 (RerankedRetriever) —
  code + tests landed
- Pre-Phase-3 fixes: naive_rag/vanilla JSON prompt tightened + fence
  stripping, openrouter cost extraction robust to `cost`/`total_cost`/missing
- Phase 3 prep: `judge_run.py` + `aggregate.py` (with no-hand-grades path,
  bootstrap CIs, Phase 6 breakdown helpers pulled forward) — code + tests
  landed but not yet RUN
- Orchestrator: incremental JSONL writes + resume support, so any kill
  preserves N-1 rows on disk
- Parallel runner: `docs/eval/scripts/runners/eval_parallel.sh` spawns 3
  per-system Python processes that resume independently; per-system logs
  at `/tmp/eval_<name>.log`; companion `eval_watch.sh` script with fail-loud
  grep patterns (process exits, attempts, every 10th question, errors)

### Not done (Phase 3 measurement onward)

- **Phase 3.1** — run `run_eval_v2.py` over the 95Q bank × 3 systems
  (vanilla, naive_rag, palimpsest-dense). Was attempted multiple times but
  Claude Code's harness aggressively reaps background bash; despite resume
  support, runs kept getting killed at 20–30 questions in. The parallel
  wrapper is the resilience answer.
- **Phase 3.3** — judge_run.py over the 3 JSONLs (~$10 cost cap)
- **Phase 3.4** — aggregate.py → `ablation_table.md` with first 3 rows
- **Phase 4.5** — factory + `RETRIEVAL_MODE` wiring in `main.py`/`config.py`
- **Phase 4.6** — shape-contract assertion in `test_agent_search_places.py`
- **Phase 4.7** — restart `RETRIEVAL_MODE=hybrid` + run 95Q + judge + row 4
- **Phase 5.3** — reranker lifespan wiring in `main.py`
- **Phase 5.4** — verify reranker loads from `hf-cache` (no HF network call)
- **Phase 5.5** — restart `RETRIEVAL_MODE=hybrid_reranked` + run 95Q + row 5
- **Phase 6** — per-region/per-source/Pareto/GRR figures + methodology doc

## Open issues that must be fixed before Phase 3 measurement re-runs

### 1. Model consistency: `openai/gpt-5.4-mini` everywhere

Previous attempts used `moonshotai/kimi-k2.6-20260420` for vanilla/naive_rag
and whatever the api router picked for palimpsest. **Updated in this
handoff**: all `systems*.yaml` files now pin `openai/gpt-5.4-mini`. Palimpsest
already uses it via `OPENROUTER_STANDARD_MODEL`/`OPENROUTER_COMPLEX_MODEL`
env vars (verified in `docker compose config`).

### 2. SSE `tool_result` frame carries only `{name, n_hits}`

The api's locked V1 SSE schema (see `apps/api/app/agent/loop.py:289-292`)
emits `tool_result` events with only the summary, not the hit payload.
The palimpsest baseline's `flatten_retrieved_docs()` returns `[]` for
every row because of this. Documented in
`docs/eval/notes/2026-05-12-phase0-smoke.md` §1.

**Implication**: HR (hallucination rate) on palimpsest is unreliable until
fixed. CCR is fine because citations carry the doc_ids that get enriched
via `/internal/documents/by_ids`. **Decision**: report Phase 3 with this
caveat; defer the SSE-schema-or-side-channel fix to a follow-up if HR
becomes critical for the headline.

### 3. Background process reaping

Claude Code's harness reaps `run_in_background: true` bash tasks after some
idle window (10–30 min). `setsid`/`nohup`/`disown` did NOT survive on this
host. The parallel wrapper at `docs/eval/scripts/runners/eval_parallel.sh`
should still be launched from a `run_in_background: true` Bash tool call —
when it dies, the wrapper's per-system loop has already preserved partial
JSONL state and can resume seamlessly on next launch.

## To resume in the next session

1. Verify stack health:
   ```bash
   docker compose ps
   curl -sf http://localhost:8000/health
   curl -s -X POST http://localhost:8000/internal/retrieve \
     -H "Content-Type: application/json" \
     -d '{"query":"cathedral","top_k":2}'
   ```
2. Verify OpenRouter key has headroom:
   ```bash
   curl -s -X POST https://openrouter.ai/api/v1/chat/completions \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer $(grep ^OPENROUTER_API_KEY .env | cut -d= -f2)" \
     -d '{"model":"openai/gpt-5.4-mini","messages":[{"role":"user","content":"hi"}],"max_tokens":10}'
   ```
3. Confirm previous Phase 3 JSONL outputs are deleted (the kimi-k2.6 data is
   not consistent with the new gpt-5.4-mini systems pin):
   ```bash
   ls docs/eval/results/phase3-*.jsonl  # should be empty
   ```
4. Launch the parallel runner:
   ```bash
   bash docs/eval/scripts/runners/eval_parallel.sh phase3
   ```
   Each system relaunches independently if killed; partial JSONLs resume
   automatically. Total wall-clock: ~30 min if uninterrupted (palimpsest
   dominates).
5. Watch with the companion script:
   ```bash
   bash docs/eval/scripts/runners/eval_watch.sh
   ```
   Emits a line per process exit, every 10th question per system, attempts,
   and errors.
6. After all 3 JSONLs have a `"type": "footer"` line, run the judge:
   ```bash
   OPENROUTER_API_KEY=$(grep ^OPENROUTER_API_KEY .env | cut -d= -f2) \
     PYTHONPATH=. docs/eval/.venv/bin/python -m docs.eval.scripts.judge_run \
     --inputs 'docs/eval/results/phase3-*.jsonl' \
     --categories docs/eval/questions/manhattan-100/categories.yaml \
     --out docs/eval/grades \
     --max-cost-usd 10.0
   ```
7. Run aggregate:
   ```bash
   PYTHONPATH=. docs/eval/.venv/bin/python -m docs.eval.scripts.aggregate \
     --grades docs/eval/grades \
     --categories docs/eval/questions/manhattan-100/categories.yaml \
     --out docs/eval/results/ablation_table.md
   ```
8. Then dispatch Phase 4.5, 4.6, 4.7 sequentially, then Phase 5.3–5.5,
   then Phase 6 figures.

## What to put in the next session's prompt

See the README in this directory (`2026-05-12-phase3-handoff-prompt.md`)
for a verbatim prompt the user can paste into a fresh Claude Code session.
