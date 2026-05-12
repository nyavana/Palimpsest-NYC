# Tasks

> **Canonical plan:** `docs/superpowers/plans/2026-05-12-eval-depth-and-corpus-expansion.md` — every task below references a line range in the canonical plan where the full TDD recipe, code skeletons, fixtures, and verification commands live. Implement against the canonical plan; tick the checkbox here when its in-plan steps are all green.
>
> Apply order: phases are sequential (0 → 6); tasks within a phase generally are too, except where the canonical plan explicitly calls out parallelism. **Phase 2 (question-bank tagging) must complete before any Phase 4 retrieval feature work** to preserve the pre-registration claim.

## Execution conventions

These apply to every task below — do not restate them per task.

- **Delegate each task to a subagent.** The main session reads the canonical plan's line range, hands the subagent a self-contained brief (goal, files to touch, the exact `tasks.md` checkbox, the canonical-plan line range, TDD/verification commands, the V1-contract invariants that must not regress), and waits for a structured report (what changed, tests run, anything deferred). The main session then ticks the checkbox and commits. Rationale: each task touches a different module + test pair + canonical-plan slab; loading those into the main context for all 30+ tasks would saturate it long before Phase 6. Use the `Explore` subagent for read-only investigations (corpus cardinality checks, index audits, spot-checks) and the `general-purpose` subagent for code changes; use `Plan` only when a task needs a fresh implementation strategy that the canonical plan does not already supply.
- **Parallelize independent subagents.** Within a phase, dispatch independent tasks in a single message with multiple Agent tool uses (e.g. Phase 4 tasks 4.1 / 4.2 / 4.3 are independent module + unit-test pairs; Phase 6 figures 6.1–6.4 are independent aggregators). Sequence only where the canonical plan calls out a dependency.
- **Commit per task, concise messages, no AI attribution.** Format: `<type>: <description>` (types: feat, fix, refactor, docs, test, chore, perf, ci). One short subject line under ~70 chars; body only when the *why* is non-obvious. Do **not** append `Co-Authored-By: Claude ...`, `Generated with Claude Code`, or any equivalent attribution — global `~/.claude/settings.json` already disables this, but if a subagent emits one, strip it before committing. Reference the `tasks.md` checkbox in the subject when it disambiguates (e.g. `feat(retrieval): RRF fusion (task 4.3)`).
- **V1 contract is the tripwire on every commit.** The five-field citation contract, turn cap of 7, JSON terminal turn, one corrective retry, and SSE event names are unchanged across this entire plan. Every subagent brief must include "do not modify `apps/api/app/agent/loop.py`, `apps/api/app/agent/citations.py`, or the SSE event schema in `apps/api/app/routes/agent.py`" unless the canonical plan explicitly authorizes it (it does not, anywhere in Phases 0–6). The shape-contract test in `apps/api/tests/test_agent_search_places.py` (added in Task 4.6) is the second tripwire.

## 0. Phase 0 — Eval scaffold smoke test

- [x] 0.1 Task 0.0 — Eval execution environment: host-side venv + `docker-compose.yml` `RETRIEVAL_MODE` / `RERANKER_ENABLED` passthrough + `make eval-setup` (canonical plan L85–L195)
- [x] 0.2 Task 0.1 — Scaffold `docs/eval/scripts/{baselines,graders,tests}/__init__.py` + commit pinned `systems.yaml` and `judge.yaml` (canonical plan L197–L283)
- [x] 0.3 Task 0.2 — Vanilla LLM baseline `docs/eval/scripts/baselines/vanilla_llm.py` (TDD; test_baselines.py first) (canonical plan L285–L493)
- [x] 0.4 Task 0.3 — Internal retrieve endpoint `apps/api/app/routes/internal_retrieve.py` for `/internal/retrieve` and `/internal/documents/by_ids` (TDD) (canonical plan L495–L828)
- [x] 0.5 Task 0.4 — Naive-RAG baseline `docs/eval/scripts/baselines/naive_rag.py` (TDD; uses `/internal/retrieve`) (canonical plan L830–L1036)
- [x] 0.6 Task 0.5 — Palimpsest baseline `docs/eval/scripts/baselines/palimpsest.py`: POST SSE consumer + `retrieved_docs` flattening + `/internal/documents/by_ids` enrichment (TDD) (canonical plan L1038–L1538)
- [x] 0.7 Task 0.6 — Grader rubric `docs/eval/scripts/graders/{rubric,llm_judge}.py` + per-metric prompts (CCR/HR/FA/NQ/GRR) (TDD) (canonical plan L1540–L1726)
- [x] 0.8 Task 0.7 — OpenRouter + retrieve HTTP clients `docs/eval/scripts/openrouter_client.py` and `retrieve_client.py` + `tests/test_clients.py` (TDD) (canonical plan L1728–L1859). Note: `sse_client.py` and `document_client.py` belong to Task 0.5 (Palimpsest baseline).
- [x] 0.9 Task 0.8 — `docs/eval/scripts/run_eval_v2.py` orchestrator + cost-cap enforcement (TDD) (canonical plan L1861–L2090)
- [x] 0.10 Task 0.9 — Phase-0 smoke run against the existing 15-question bench; hand-grade 3 rows; compute κ against the judge (canonical plan L2092–L2205) — plumbing validated 2026-05-12; κ skipped per [[feedback-skip-human-review]]; two issues filed in `docs/eval/notes/2026-05-12-phase0-smoke.md`

## 1. Phase 1 — Manhattan corpus expansion

- [x] 1.1 Task 1.1 — Widen `apps/api/app/ingest/scope.py` `SCOPE_BBOX` to Manhattan island + bump `SCOPE_VERSION` (TDD) (canonical plan L2209–L2285)
- [x] 1.2 Task 1.2 — Verify existing trigram indexes survive corpus widening; land `apps/api/app/db/migrations/0003_widen_scope_indexes.sql` if needed (canonical plan L2287–L2321)
- [x] 1.3 Task 1.3 — `make nuke && make up` and re-ingest OSM + Wikipedia at the wider bbox; verify ~3–5k places + ~1.5–2k docs (canonical plan L2323–L2390) — actual: 12,858 OSM + 492 wiki + 456 docs
- [ ] 1.4 Task 1.4 — OSRM extract resize for Manhattan bbox (optional; deferrable per design risk R8) (canonical plan L2392–L2454) — **deferred** per R8
- [x] 1.5 Task 1.5 — Spot-check 5 Manhattan-specific queries through `/agent/ask` + confirm `make test` is green (canonical plan L2456–L2495) — 3/5 OK, 2 reveal dense-only gap; 272/273 tests pass

## 2. Phase 2 — Question bank synthesis & curation (PRE-REGISTER BEFORE PHASE 4)

- [x] 2.1 Task 2.1 — `docs/eval/scripts/synthesize_questions.py` — templates ~150 candidate questions from sampled corpus places (TDD) (canonical plan L2499–L2781)
- [x] 2.2 Task 2.2 — Generate seed-places TSV by sampling the expanded corpus (canonical plan L2783–L2893)
- [x] 2.3 Task 2.3 — Synthesize ~150 candidates + manually cull to 100 balanced across categories (30 single / 25 multi / 20 geographic / 15 per-neighborhood / 10 out-of-scope) (canonical plan L2895–L2995)
- [x] 2.4 Task 2.4 — Write `docs/eval/questions/manhattan-100/categories.yaml` mapping each question to category + region + expected source types (canonical plan L2997–L3069)
- [x] 2.5 Commit and `git tag eval/manhattan-100-vN` so the report can cite "question bank @ commit ABCDEF" (canonical plan L2997–L3069 + design D6) — tagged `eval/manhattan-100-v1` after Phase 2 commit; actual count 95 not 100

## 3. Phase 3 — Baseline + dense Palimpsest measurement

- [ ] 3.1 Task 3.1 — Run `run_eval_v2.py` against all 100 questions × 3 systems (vanilla, naive_rag, palimpsest-dense); produce JSONL (canonical plan L3073–L3124)
- [ ] 3.2 Task 3.2 — Hand-grade the 20-question calibration set into `docs/eval/grades/calibration.csv` (canonical plan L3126–L3190)
- [ ] 3.3 Task 3.3 — Run LLM-judge over all 300 rows; respect the ~$10 cost cap (canonical plan L3192–L3363)
- [ ] 3.4 Task 3.4 — `docs/eval/scripts/aggregate.py` + Cohen's κ math (TDD) → first `ablation_table.md` with 3 baseline rows + κ (canonical plan L3365–L3660)

## 4. Phase 4 — Hybrid retrieval

- [x] 4.1 Task 4.1 — Extract `DenseRetriever` from `search_places` into `apps/api/app/retrieval/dense.py` (TDD; preserves V1 tool-result shape) (canonical plan L3664–L3876)
- [x] 4.2 Task 4.2 — `apps/api/app/retrieval/sparse.py` — `SparseRetriever` over `pg_trgm` on `places.name` (TDD) (canonical plan L3878–L4065)
- [x] 4.3 Task 4.3 — `apps/api/app/retrieval/fusion.py` — Reciprocal Rank Fusion with k=60 (pure function, TDD) (canonical plan L4067–L4189)
- [x] 4.4 Task 4.4 — `apps/api/app/retrieval/hybrid.py` — `HybridRetriever` running dense + sparse concurrently + RRF merge (TDD) (canonical plan L4191–L4360)
- [ ] 4.5 Task 4.5 — `apps/api/app/retrieval/factory.py` — `build_retriever(mode)` factory + `RETRIEVAL_MODE` flag wiring in `apps/api/app/config.py` and `apps/api/app/main.py` lifespan (TDD) (canonical plan L4362–L4581)
- [ ] 4.6 Task 4.6 — Shape-contract assertion in `apps/api/tests/test_agent_search_places.py`: tool-result is byte-identical across `dense` / `hybrid` / `hybrid_reranked` (canonical plan L4583–L4639)
- [ ] 4.7 Task 4.7 — Restart with `RETRIEVAL_MODE=hybrid`, run the 100-question bank for the hybrid system row, hand-grade the 20 calibration questions, append to `ablation_table.md` (canonical plan L4641–L4716)

## 5. Phase 5 — Cross-encoder reranker

- [x] 5.1 Task 5.1 — `apps/api/app/embeddings/reranker.py` — `Reranker` singleton wrapping `BAAI/bge-reranker-base` (TDD) (canonical plan L4720–L4844)
- [x] 5.2 Task 5.2 — `apps/api/app/retrieval/reranked.py` — `RerankedRetriever` wrapping `HybridRetriever` with cross-encoder top-N rerank (TDD) (canonical plan L4846–L5000)
- [ ] 5.3 Task 5.3 — Wire the reranker into `apps/api/app/main.py` lifespan conditionally on `settings.retrieval_mode == "hybrid_reranked"` or `settings.reranker_enabled` (canonical plan L5002–L5046)
- [ ] 5.4 Task 5.4 — Verify reranker loads from `hf-cache` inside the container without a Hugging Face network call (canonical plan L5048–L5099)
- [ ] 5.5 Task 5.5 — Restart with `RETRIEVAL_MODE=hybrid_reranked`, run the 100-question bank for the reranker row, hand-grade the 20 calibration questions, append the final row to `ablation_table.md` (canonical plan L5101–L5158)

## 6. Phase 6 — Breakdowns, figures, report numbers

- [ ] 6.1 Task 6.1 — Per-region CCR breakdown via `aggregate.py` reading `categories.yaml`; emit bar-chart PNG (canonical plan L5162–L5279)
- [ ] 6.2 Task 6.2 — Per-source CCR breakdown (Wikipedia vs OSM); emit bar-chart PNG (canonical plan L5281–L5430)
- [ ] 6.3 Task 6.3 — Accuracy-vs-latency Pareto scatter (x = p50 latency, y = CCR); one point per system (canonical plan L5432–L5531)
- [ ] 6.4 Task 6.4 — Graceful-Refusal-Rate (GRR) analysis on the 10 out-of-scope × 5 systems subset (canonical plan L5533–L5602)
- [ ] 6.5 Task 6.5 — Final methodology summary doc + commit all results under `docs/eval/results/` (canonical plan L5604–L5689)
