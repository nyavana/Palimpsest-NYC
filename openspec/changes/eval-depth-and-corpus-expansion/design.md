## Context

Palimpsest NYC V1 has shipped (commit `e1bc76d` + follow-ups): a two-tool agent (`search_places` + `plan_walk`) with a locked five-field citation contract, two-tier LLM router, ~1k-place corpus over a MH+UWS bbox, server-side OSRM walk planner, BYOK SSE frontend, and a food-discovery side flow. The existing eval artifacts (`docs/eval/v1-eval-report.md`, `docs/eval/v1-router-comparison.md`) total n=5 walks reviewed qualitatively and n=10 router-cost rows. The EECS E6895 report needs (a) a headline number comparing Palimpsest to a non-agentic baseline and (b) an ablation curve showing what each Palimpsest component contributes.

Three orthogonal capability blocks sit *above* the existing V1 system. None of them mutate the locked V1 agent loop / verifier / SSE contract:

1. **Corpus expansion** — widen `app/ingest/scope.py` `SCOPE_BBOX` to all of Manhattan and re-run ingestors. Re-extract OSRM PBF (deferrable; the eval's headline metrics do not depend on walk geometry).
2. **Retrieval upgrades** — all live inside `search_places`. Selection is by env flag `RETRIEVAL_MODE ∈ {dense, hybrid, hybrid_reranked}`. The agent loop never knows which retrieval mode is active; only `search_places` reads the flag.
3. **Eval harness** — a sibling of `docs/eval/scripts/run_eval.py`. Vanilla LLM and naive RAG baselines hit OpenRouter directly; Palimpsest baselines POST to the running `/agent/ask` SSE endpoint with the same input shape across all three retrieval-mode rows.

The full ~5,700-line task-by-task plan with verbatim test fixtures, code skeletons, and command recipes lives at `docs/superpowers/plans/2026-05-12-eval-depth-and-corpus-expansion.md`. The design narrative (motivation, metrics, phases, risks, open questions) lives at `docs/superpowers/specs/2026-05-12-eval-depth-and-corpus-expansion-design.md`. This OpenSpec design summarizes the architectural decisions and points back to those documents for line-level detail; `tasks.md` mirrors the phased checklist with line-range references into the canonical plan.

## Goals / Non-Goals

**Goals:**
- Manhattan-wide corpus: widen `SCOPE_BBOX` and re-run OSM + Wikipedia ingestors. Verify retrieval still works on the larger index.
- Pluggable retrieval pipelines behind a single env flag, with identical tool-result shape across all three modes (a tested invariant).
- A pre-registered, committed-before-feature-work 100-question Manhattan bench, organized by category and tagged in git.
- An above-the-API eval harness that runs 5 systems × 100 questions, grades the outputs with a hybrid hand + LLM-judge protocol, computes Cohen's κ on a 20-question calibration set, and emits the headline ablation table plus per-region, per-source, and accuracy-vs-latency Pareto figures.
- Reproducibility: pinned judge model + prompt version, temperature 0, host-side venv pinned in `docs/eval/requirements.txt`, committed configs.
- No regression in the V1 contract: turn cap, JSON terminal turn, five-field citation contract, one-retry verifier, SSE event names all unchanged.

**Non-Goals:**
- Multi-hop / query-decomposition agent changes — touches the locked loop; deferred.
- LLM-as-judge replacement of the inline citation verifier — separate from the eval grader; deferred.
- Live-web baselines (Perplexity, Google Places) — require paid keys, weaker control properties.
- New source types beyond Wikipedia + OSM (Chronicling America, NYPL, NYC Open Data remain V2 backlog).
- V2 deployment work (VPS, scheduler).

## Decisions

### D1 — Retrieval mode is a process-start env flag, not a per-request parameter

Selecting retrieval mode per request would require threading the flag through the agent loop, the tool registry, and the LLM tool-call interface — and would force the LLM to know about retrieval mode, which leaks an internal detail into the prompt. Instead, `RETRIEVAL_MODE` is read once at process start by `app/main.py` lifespan, the factory builds the right retriever, and the same retriever serves the whole process.

Alternatives considered: (a) per-request mode via header — rejected because it complicates BYOK and the SSE contract; (b) hardcoded "best" mode after Phase 5 — rejected because it eliminates the ablation rows that motivate the design.

Consequence: producing all three Palimpsest ablation rows is an env swap + container restart from the host, not a code change. The eval harness's `systems.yaml` encodes this as separate system rows.

### D2 — `DenseRetriever` is extracted from `search_places` before any new mode is added

`apps/api/app/agent/tools/search_places.py` currently embeds the pgvector retrieval inline. Extracting it into `app/retrieval/dense.py` first lets the shape-contract test land and pass before any second-mode code exists. Refactor-then-extend keeps the diff per phase smaller and the V1-shape tripwire on guard the entire time.

### D3 — Reciprocal Rank Fusion with k=60, not learned weights

For hybrid retrieval we use the canonical Cormack et al. 2009 RRF setup: `score = Σ 1/(k + rank_i)` with `k=60`. No training, no weights, no per-corpus tuning. This keeps `fusion.py` ~15 lines of pure-function code with one unit-test file. Alternatives considered: Reciprocal Rank with `k=20`, weighted sum of normalized scores, learning-to-rank. All are rejected for the V1 eval because they would either introduce training data dependencies (LTR) or per-corpus tuning that violates the "ablation isolates one variable" principle.

### D4 — Reranker is conditionally loaded in the lifespan

`BAAI/bge-reranker-base` is ~120 MB of model weights and ~30 ms/pair of CPU inference. Always-loading it would tax `make up` time for the 80% of dev work that does not need it. Instead the lifespan checks `settings.retrieval_mode == "hybrid_reranked"` (or an explicit `RERANKER_ENABLED=true`) before constructing the singleton. `RerankedRetriever` reads `app.state.reranker` and fails fast at request time if absent, surfacing the misconfiguration as a 500 with a clear message rather than silently degrading.

### D5 — Naive-RAG baseline uses Palimpsest's same embedder + corpus via a new `/internal/retrieve` route

The naive-RAG baseline is meant to isolate the contribution of the agent loop + verifier specifically. Having the baseline embed and pg-query directly from the host would mean it could drift from Palimpsest's retrieval over time (different embedder version, different filter logic). Instead, we expose `/internal/retrieve` and `/internal/documents/by_ids` so the baseline and the Palimpsest grader-side enrichment share one server-side retrieval implementation. `/internal/retrieve` is *not* `search_places` re-skinned: it has no agent loop, no citation verifier, no SSE — it just returns the retrieval results. Same retriever instance, same corpus, same embedder. The seam keeps the comparison clean.

### D6 — Question bank is committed and tagged BEFORE any retrieval feature work

This is the standard "pre-registration" defense against fishing for a benchmark that flatters the system being tested. The 100 questions live in `docs/eval/questions/manhattan-100/` with `categories.yaml` mapping each to category + region + expected source types. The commit is tagged so the report can cite "question bank @ commit ABCDEF". Synthesis is templated from corpus samples (`synthesize_questions.py`) to ~150 candidates, then manually culled to 100 with explicit balance across single-place / multi-place / geographic / per-neighborhood / out-of-scope. The 10 out-of-scope questions act as the fairness check (per risk R5 — see §Risks).

### D7 — Hand + LLM-judge hybrid grading with κ disclosed

The headline numbers use hand grades on a 20-question calibration set and LLM-judge grades on the other 80. Cohen's κ between hand and LLM-judge on the 20 calibration questions is reported alongside; if κ < 0.4 we hand-grade an additional 30 and report two tables (see risk R2). The judge model and prompt are pinned in `judge.yaml` (`anthropic/claude-opus-4-7`, temperature 0, `prompt_version: v1`) so re-runs are stable. We never tune Palimpsest against the judge — the question bank is committed first.

### D8 — Eval harness lives outside the API container

The eval scripts live under `docs/eval/scripts/`. The api Dockerfile does not `COPY ./docs`, and `docker-compose.yml` does not mount `./docs` into the api service, so `docker compose exec api python -m docs.eval.scripts.run_eval_v2` would ModuleNotFoundError. Also, matplotlib + PyYAML are not API runtime deps; keeping them out of `apps/api/pyproject.toml` preserves the slim runtime image.

Consequence: eval runs from a host-side venv at `docs/eval/.venv` driven by `docs/eval/requirements.txt`, via `make eval-setup`. The harness POSTs against `http://localhost:8000` for Palimpsest baselines and against OpenRouter directly for vanilla / naive_rag. `docker-compose.yml` adds `RETRIEVAL_MODE: ${RETRIEVAL_MODE:-dense}` and `RERANKER_ENABLED: ${RERANKER_ENABLED:-false}` to the `api` service's `environment:` block so the host can pass mode via env vars (compose does YAML-side substitution only, not implicit passthrough).

### D9 — TDD on every retrieval module and every baseline

Each new module (`dense`, `sparse`, `fusion`, `hybrid`, `reranked`, `factory`, `reranker`, all three baselines, the grader rubric, `aggregate.py`) lands with a failing test first. Tests assert: (a) module shape contracts where applicable, (b) RRF math edge cases, (c) shape-equivalence across all three retrieval modes (the V1 tripwire), (d) baseline JSONL row shape conformance so `aggregate.py` does not need per-system branching, (e) `aggregate.py` κ math against a hand-crafted fixture.

### D10 — Locked V1 contract is enforced by tests, not convention

The five-field citation contract (`doc_id`, `source_url`, `source_type ∈ {wikipedia, wikidata, osm}`, `span`, `retrieval_turn`), the turn cap of 7, the JSON terminal turn, the single corrective retry, and the SSE event names are all unchanged. The `search_places` tool-result shape is now a tested invariant: `test_retrieval_factory.py` asserts byte-identical shape across all three modes, and an extension to `test_agent_search_places.py` asserts shape stability against the V1 baseline. Any refactor that changes the shape breaks these tests before it touches the loop.

## Risks / Trade-offs

- **R1 — Manhattan corpus is larger than expected** → After Phase 1, check actual cardinality and retrieval p95. If retrieval is >2s p95, add a per-query bbox filter so the agent can pass a region hint. Cap LLM-judge spend at ~$10 with a hard counter in `run_eval_v2.py`.
- **R2 — LLM-judge has low agreement with hand-grader (κ < 0.4)** → Test judge prompt against 3 hand-graded questions in Phase 0 and iterate before locking. If κ stays low after Phase 3, hand-grade 30 more (50 total) and report two parallel tables. Worst case: headline narrows to "X% better on the 50 hand-graded subset" — smaller n, still publishable.
- **R3 — Reranker on CPU is too slow at p95** → Reduce reranker input to top-12 (~360 ms) or use an ONNX-quantized reranker. If still bad, mark reranker as "available but off by default" and report its numbers as a methodology note.
- **R4 — Hybrid does not lift the headline number** → A null result is publishable ("we measured RRF and found no statistically significant lift over dense-only on this corpus, suggesting embedding coverage is saturating"). The report stays valid.
- **R5 — Question synthesizer produces biased questions** → Curation rebalances; the 10 out-of-scope questions act as a fairness check via GRR; methodology section calls out the corpus-sampled limitation; optionally add 20 "wild" questions from an external LLM that has not seen the corpus.
- **R6 — Touching `search_places` breaks the V1 contract** → Tests-first. `test_retrieval_factory.py` asserts shape equivalence across all three modes before any production code lands. The extension to `test_agent_search_places.py` is the second tripwire.
- **R7 — `pg_trgm` indexes on a larger corpus blow up the docker volume** → Document expected ~2 GB on Manhattan-scale corpus in the migration comment + `make nuke` notes.
- **R8 — OSRM extract resize is fiddly** → Defer if it takes >1 day. The eval headline metrics (CCR / HR / FA / NQ) do not depend on walk geometry; the SSE `walk` frame is already conditional in the current code path.
- **R9 — Hand-grading drags** → Reuse `docs/walk-eval-checklist.md` template. Start with CCR + HR on the calibration set; defer FA + NQ to LLM-judge only if time pressure mounts.

## Migration Plan

This change is additive; rollback is `git revert` plus an optional `make nuke && make up` to restore the MH+UWS corpus. There is no production deployment to coordinate (V1 ships from `main`; this branch is being developed in a worktree).

Phased order (mirrored in `tasks.md`):

1. **Phase 0 — Eval scaffold smoke test (~1 day).** Host venv, compose env passthrough, baseline / grader skeletons, validate κ against 3 hand grades on the existing 15-question smoke set.
2. **Phase 1 — Manhattan corpus expansion (~2–3 days).** Widen bbox, trigram migration, `make nuke && make up`, OSM + Wikipedia re-ingest. OSRM resize optional / deferrable.
3. **Phase 2 — Question bank synthesis + curation (~2–3 days).** Tag the commit before any further feature work.
4. **Phase 3 — Baseline + dense Palimpsest measurement (~1–2 days).** First headline number with 3 rows.
5. **Phase 4 — Hybrid retrieval (~1–2 days).** Append the hybrid row.
6. **Phase 5 — Cross-encoder reranker (~1–2 days).** Append the reranker row.
7. **Phase 6 — Breakdowns, figures, report numbers (~1–2 days).** Per-region, per-source, GRR, accuracy-vs-latency Pareto, methodology summary.

Total: ~10–15 working days. Each phase ends with a committed deliverable so if anything later slips, the previous phase's numbers are banked.

## Open Questions

- Final judge model selection: `anthropic/claude-opus-4-7` is the pinned choice; if cost runs over the ~$10 cap on the first 300-row pass, fall back to `anthropic/claude-sonnet-4-6` and re-validate κ.
- Whether to add an external-LLM "wild" question subset of 20 (R5 mitigation layer): deferred to Phase 2 curation; revisit after the first 150 templated candidates are reviewed.
- Whether `RERANKER_ENABLED` should default to `true` once Phase 5 numbers are in: deferred until we see the latency p95 measurement. Default stays `false` for V1 to keep `make up` fast.
- Whether to commit the OSRM `.osrm` artifacts (in addition to `extract.osm.pbf`) once the Manhattan-wide PBF lands: deferred to Phase 1's R8 follow-up.
