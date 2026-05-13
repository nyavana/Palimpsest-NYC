# New-session prompt — Phase 3 onward

Paste this verbatim into a fresh Claude Code session in the
`/home/nyavana/columbia/6895/Palimpsest-NYC/eval-depth-and-corpus-expansion`
working directory:

---

```
Continue executing the OpenSpec plan at
openspec/changes/eval-depth-and-corpus-expansion.

Pick up where the previous session left off. The full handoff is at
docs/eval/notes/2026-05-12-phase3-handoff.md — read that first.

Quick summary of state:
- Phases 0, 1, 2 are committed and tagged (git tag eval/manhattan-100-v1).
- Phase 4 retrieval modules (4.1, 4.2, 4.3, 4.4) and Phase 5 reranker
  modules (5.1, 5.2) are code-complete and tested but their factory
  wiring (4.5) and lifespan wiring (5.3) are not done.
- Phase 3 measurement was attempted but background bash kept getting
  reaped before completion. The fix: docs/eval/scripts/runners/eval_parallel.sh
  spawns 3 per-system Python processes that resume independently. The
  orchestrator now writes JSONL rows incrementally so partial progress
  survives any kill.
- All systems.yaml files have been switched from kimi-k2.6 to
  openai/gpt-5.4-mini for model consistency. The previous Phase 3
  JSONLs were deleted (inconsistent model).

Execution preferences from prior session (please respect):
- Per-PHASE commits (not per-task) per agent memory.
- Skip human-review steps (hand-grading, manual curation) per agent
  memory; document the deferral and use LLM-judge or deterministic
  fallbacks.
- Use subagents per task as tasks.md instructs.
- Parallelize independent tasks.
- When running long-running eval, USE docs/eval/scripts/runners/eval_parallel.sh
  not the single-process run_eval_v2 CLI — the parallel wrapper has
  per-system retry and is what survives the harness's bg-reaper.

Next concrete steps:
1. Verify stack health and OpenRouter key (commands in the handoff doc).
2. Run docs/eval/scripts/runners/eval_parallel.sh phase3 as a
   run_in_background bash task, with docs/eval/scripts/runners/eval_watch.sh
   as a Monitor tool watch.
3. After all 3 JSONLs land a footer line, run judge_run.py + aggregate.py
   to produce the first ablation_table.md.
4. Then dispatch Phase 4.5 → 4.6 → 4.7 (hybrid measurement),
   Phase 5.3 → 5.4 → 5.5 (reranker measurement),
   then Phase 6 figures and methodology summary.

Known issues (documented in
docs/eval/notes/2026-05-12-phase0-smoke.md):
- SSE tool_result frame carries only {name, n_hits} — palimpsest
  retrieved_docs is empty for every row. Affects HR metric only;
  CCR/FA/NQ/GRR are unaffected. Defer the side-channel fix unless HR
  becomes critical to the headline.
- Question bank is 95 not 100 (synthesizer NEIGHBORHOODS list yielded
  15 geographic not 20). Acceptable; tag is `eval/manhattan-100-v1`.
- Wikipedia ingestion capped at 500-item batch; final 492 places looks
  similar to V1 by coincidence.

Memory references that apply:
- [[project-eval-change-commit-cadence]] — per-phase commits
- [[feedback-skip-human-review]] — skip hand-grading/curation gates
```

---

After pasting that, the new session has full context. It will read the
handoff doc, the project memories, and resume cleanly.
