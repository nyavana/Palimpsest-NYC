# Eval Depth & Corpus Expansion — Design

**Date:** 2026-05-12
**Author:** brainstormed with Claude Code (session telemetry in `logs/claude-sessions/`)
**Status:** approved design, pending implementation plan
**Branch:** `worktree-eval-depth-and-corpus-expansion`

## 1. Motivation

Palimpsest NYC V1 has shipped (commit `e1bc76d` and follow-ups): a single-tool agent with a locked five-field citation contract, two-tier LLM router, ~1k-place corpus over a Morningside-Heights + UWS bounding box, server-side walk planner, SSE frontend, BYOK credentials, and a food-discovery side flow. The existing evaluation artifacts (`docs/eval/v1-eval-report.md`, `docs/eval/v1-router-comparison.md`) cover qualitative review of 5 walks and a cost comparison across 10 walks.

For the EECS E6895 final report we need numbers that compare Palimpsest to a baseline of traditional LLM techniques and that quantify the contribution of each component. The current artifacts are too small for statistical claims (n=5 and n=10) and they don't contrast Palimpsest against a non-agentic baseline. This design adds three orthogonal capability blocks plus a corpus expansion so the final report can carry a headline number ("Palimpsest produces X% higher citation correctness than vanilla LLM, Y% higher than naive RAG") and a clean ablation curve showing what each Palimpsest component contributes.

The locked V1 contract — turn cap of 7, JSON terminal turn, five-field citation contract, one corrective retry — does not change.

## 2. Scope

In scope for this design:

- Widen `SCOPE_BBOX` from MH+UWS to all of Manhattan; re-run OSM + Wikipedia ingestors; resize the OSRM extract.
- Add two retrieval upgrades behind an env flag (`RETRIEVAL_MODE`): hybrid dense+sparse with Reciprocal Rank Fusion, and a cross-encoder reranker. The agent loop and citation verifier are unchanged; only the `search_places` tool's retrieval pipeline branches.
- Build an eval harness above the API that runs three baselines and the three Palimpsest retrieval modes against a pre-registered 100-question bank, grades the outputs with a hybrid hand + LLM-judge protocol, and emits the report's headline ablation table plus per-region, per-source, and Pareto figures.

Out of scope:

- Multi-hop / query-decomposition agent changes (touches the locked loop; deferred).
- LLM-as-judge replacement for the inline citation verifier (deferred; possible follow-up after the grader's LLM-judge is wired).
- Live web-search or Google Places baselines (require paid keys and have weaker control properties).
- New source types beyond Wikipedia + OSM. Chronicling America, NYPL, NYC Open Data remain in the V2 backlog.
- v2 deployment work (VPS, scheduler).

## 3. Architecture

Three orthogonal capability blocks sit above the existing V1 system:

1. **Corpus expansion** modifies `app/ingest/scope.py` and triggers a re-ingestion; otherwise no API changes.
2. **Retrieval upgrades** live entirely inside `search_places`; selection is driven by `RETRIEVAL_MODE ∈ {dense, hybrid, hybrid_reranked}`. The agent loop, citation verifier, and SSE contract are untouched.
3. **Eval harness** is a sibling of `docs/eval/scripts/run_eval.py`. Vanilla LLM and naive RAG baselines hit OpenRouter directly; Palimpsest configurations are exercised by HTTP calls to the running API with different `RETRIEVAL_MODE` settings.

```
┌──────────────────────────────────────────────────────────────┐
│                     EVAL HARNESS (new)                       │
│                                                              │
│  ┌─────────────────────┐    ┌──────────────────────────────┐ │
│  │ 100-question bench  │───▶│ run_eval_v2.py (orchestrator)│ │
│  │ (generated + curated│    └──────────┬───────────────────┘ │
│  │  + categorized)     │               │                     │
│  └─────────────────────┘     ┌─────────┼──────────┐          │
│                              ▼         ▼          ▼          │
│                       ┌──────────┐ ┌─────────┐ ┌────────┐    │
│                       │ vanilla  │ │ naive   │ │ Palim- │    │
│                       │ LLM      │ │ RAG     │ │ psest  │    │
│                       │ baseline │ │ baseline│ │ agent  │    │
│                       └─────┬────┘ └────┬────┘ └───┬────┘    │
│                             │           │          │         │
│                             └────┬──────┴──────────┘         │
│                                  ▼                           │
│                       ┌────────────────────────┐             │
│                       │ JSONL results          │             │
│                       │ (one row per system×Q) │             │
│                       └──────────┬─────────────┘             │
│                                  │                           │
│                       ┌──────────▼─────────┐                 │
│                       │ HYBRID GRADER      │                 │
│                       │  ├─ hand-grade 20  │                 │
│                       │  ├─ LLM-judge 100  │                 │
│                       │  └─ κ agreement    │                 │
│                       └──────────┬─────────┘                 │
│                                  ▼                           │
│                       ┌──────────────────────┐               │
│                       │ ablation_table.md +  │               │
│                       │ figures (per-region, │               │
│                       │ per-source, Pareto)  │               │
│                       └──────────────────────┘               │
└──────────────────────────────────────────────────────────────┘

                  ▲ (eval harness sits ABOVE existing API)

┌──────────────────────────────────────────────────────────────┐
│                  EXISTING PALIMPSEST API                     │
│  (unchanged contract — additions are behind flags)           │
│                                                              │
│  agent loop ──▶ search_places tool ──▶ retrieval pipeline    │
│                                              │               │
│                                  ┌───────────┴────────────┐  │
│                                  │ stage 1: dense (BGE)   │  │
│                                  │ stage 1b: + sparse RRF │  │← NEW: HYBRID
│                                  │ stage 2: + reranker    │  │← NEW: RERANKER
│                                  │ (each behind env flag) │  │
│                                  └────────────────────────┘  │
│                                                              │
│  corpus: Manhattan-wide (widened SCOPE_BBOX migration)       │← NEW: SCOPE
└──────────────────────────────────────────────────────────────┘
```

Structural decisions:

- The eval harness is *outside* the API. Baselines hit OpenRouter directly; Palimpsest baselines hit the running `/agent/ask` SSE endpoint. The V1 contract is therefore literally not touched by the eval code.
- The retrieval upgrades are driven by a single env flag. The agent loop never knows which retrieval mode is active; only `search_places` reads the flag and branches. This means the *same* running container produces all three Palimpsest ablation rows via env swap + restart.
- Manhattan expansion is one bbox change in `app/ingest/scope.py` plus a re-run of ingestors and an OSRM re-extract. Existing tests pin to specific lat/lons inside the original bbox so most still pass.
- The 100-question bank lives in `docs/eval/questions/manhattan-100/`, versioned in git, organized by category, and committed (and tagged) *before* any feature work begins. This is the standard "pre-registration" defense against fishing for question sets that flatter our system.
- The grader is reproducible. Hand-grade scores are CSV in `docs/eval/grades/`; LLM-judge prompts and model IDs are pinned in `docs/eval/scripts/judge.yaml`; running with the same inputs reproduces the same outputs up to judge-model stochasticity (which we mitigate by setting temperature 0).

## 4. Components

### 4.1 Corpus expansion

| File | Change |
|---|---|
| `apps/api/app/ingest/scope.py` | Widen `SCOPE_BBOX` to Manhattan island (approximately 40.700 → 40.880 N, −74.020 → −73.910 W). Bump a `SCOPE_VERSION` constant for telemetry. |
| `apps/api/app/db/migrations/0XX_widen_scope_indexes.sql` | Verify/recreate spatial indexes if Manhattan-sized cardinality changes the planner's choice. May be a no-op. |
| `apps/api/app/db/migrations/0XX_add_trigram_indexes.sql` | Add `gin_trgm_ops` indexes on `places.name` and `documents.text` if not already present. Needed for hybrid retrieval; landing it during the corpus phase lets the re-ingestion build the index from scratch. |
| `infra/osrm/` (existing) | Re-extract OSRM data for the widened bbox; rebuild `.osrm` files. Follow the procedure in `docs/route-planning-2026-05-04.md`. |
| Ingestion runs | `make nuke && make up` then `python -m app.ingest.cli osm run` and `wikipedia run`. Expected scale: ~3–5k places + ~1.5–2k documents, but verify against actual cardinality (see R1 in §8). |

### 4.2 Retrieval upgrades (behind `RETRIEVAL_MODE`)

| File | Change |
|---|---|
| `apps/api/app/agent/tools/search_places.py` (or wherever it currently lives) | Read `RETRIEVAL_MODE` env. Branch into three pipelines: `dense` (current), `hybrid`, `hybrid_reranked`. Tool result shape is unchanged across all three. |
| `apps/api/app/retrieval/dense.py` *(new, refactored from search_places)* | Current pgvector top-K query, extracted for testability. |
| `apps/api/app/retrieval/sparse.py` *(new)* | `pg_trgm` similarity query over `places.name` and `documents.text`, top-K. |
| `apps/api/app/retrieval/fusion.py` *(new)* | Reciprocal Rank Fusion. Score formula `score = Σ 1/(k + rank_i)` with `k=60` per the canonical Cormack et al. 2009 setup. ~15 lines. |
| `apps/api/app/embeddings/reranker.py` *(new)* | Singleton wrapper around `BAAI/bge-reranker-base`. Loaded in `main.py` lifespan from the `hf-cache` volume. Method `rerank(query, candidates) -> reranked`. |
| `apps/api/app/main.py` (lifespan) | Add `app.state.reranker` singleton, conditionally constructed when `RETRIEVAL_MODE == "hybrid_reranked"` so we don't pay the model-load cost in dense and hybrid modes. |
| `apps/api/app/config.py` | Add `retrieval_mode`, `reranker_model` settings. |
| `.env.example` | Document the new env vars. |

### 4.3 Eval harness

| File | Purpose |
|---|---|
| `docs/eval/questions/manhattan-100/` *(new dir)* | Pre-registered question bank. Subfiles by category: `single-place.txt`, `multi-place.txt`, `geographic.txt`, `out-of-scope.txt`, `per-neighborhood.txt`. |
| `docs/eval/questions/manhattan-100/categories.yaml` *(new)* | Maps each question to category, expected source types, expected region. Drives per-region and per-source breakdowns in §4.6. |
| `docs/eval/scripts/synthesize_questions.py` *(new)* | Samples places from the (expanded) corpus, templates ~150 candidate questions, writes a curation TSV. |
| `docs/eval/scripts/run_eval_v2.py` *(new)* | Orchestrator. Reads question bank + `systems.yaml`. For each (system, question) pair, captures output JSONL with the same row shape across all 5 systems. |
| `docs/eval/scripts/baselines/vanilla_llm.py` *(new)* | One-shot OpenRouter call, no retrieval; asks for narration + citations in the V1 JSON shape. Whatever the model fabricates goes in unchanged. |
| `docs/eval/scripts/baselines/naive_rag.py` *(new)* | Embed query → pgvector top-K → stuff retrieved docs into the prompt → one-shot generate. Uses the same embedder singleton and same corpus as Palimpsest, so the comparison isolates the agent loop + verifier specifically. |
| `docs/eval/scripts/graders/llm_judge.py` *(new)* | For each row, prompt judge model with rubric + output + retrieved docs, return scores for citation correctness, hallucination, factual accuracy, and narration quality. Reads `judge.yaml` (model id, prompt version). |
| `docs/eval/scripts/aggregate.py` *(new)* | Joins LLM-judge + hand-grade rows. Computes per-system metrics with 95% CIs, Cohen's κ between hand and judge on the calibration set, per-region/per-source breakdowns. Emits `ablation_table.md` and figure PNGs. |
| `docs/eval/grades/calibration.csv` *(new, hand-filled)* | Your 20-question hand-grade. Same columns as the LLM-judge output. |
| `docs/eval/scripts/systems.yaml` *(new)* | Pinned per-system config: model, base URL, retrieval mode, env overrides. |
| `docs/eval/scripts/judge.yaml` *(new)* | Pinned judge model + prompt version. Temperature 0. |

### 4.4 Tests

| File | Coverage |
|---|---|
| `apps/api/tests/test_retrieval_sparse.py` | pg_trgm query returns sensible results on known places. |
| `apps/api/tests/test_retrieval_fusion.py` | RRF math, edge cases (empty list, duplicates, ranking ties). |
| `apps/api/tests/test_reranker.py` | Reranker singleton loads from `hf-cache`; reorders a known-bad ordering correctly. |
| `apps/api/tests/test_retrieval_mode_flag.py` | `RETRIEVAL_MODE` env switches pipelines without changing the `search_places` tool-result shape. Asserts shape equivalence across all three modes. |
| `apps/api/tests/test_agent_search_places.py` (existing) | Extend with a "shape contract" assertion so retrieval refactors that change the shape break this test before they touch the loop. |
| `docs/eval/scripts/tests/` | Unit tests for question synthesis, baseline output shape conformance, grader I/O. |

### 4.5 Configuration

| File | Change |
|---|---|
| `.env.example` | Add `RETRIEVAL_MODE`, `RERANKER_MODEL`, `JUDGE_MODEL`, `JUDGE_BASE_URL`. |
| `apps/api/app/config.py` | Corresponding pydantic settings entries. |

### 4.6 Final deliverable shape

The eval harness produces:

```
| System                            | CCR ↑  | HR ↓  | FA ↑  | NQ ↑ | Cost ↓ | p50 ↓ | p95 ↓ | Toks ↓ | GRR ↑ |
|-----------------------------------|--------|-------|-------|------|--------|-------|-------|--------|-------|
| Vanilla LLM                       |        |       |       |      |        |       |       |        |       |
| Naive RAG                         |        |       |       |      |        |       |       |        |       |
| Palimpsest (dense)                |        |       |       |      |        |       |       |        |       |
| Palimpsest (+ hybrid retrieval)   |        |       |       |      |        |       |       |        |       |
| Palimpsest (+ reranker)           |        |       |       |      |        |       |       |        |       |
```

Plus three supplementary figures:

1. Per-region breakdown (Harlem / Midtown / SoHo / FiDi / UWS / MH) — bar chart of CCR per system per region.
2. Per-source breakdown (Wikipedia vs OSM) — does Palimpsest do better on one source family than the other?
3. Accuracy-vs-latency Pareto scatter — one point per system; x = latency p50, y = CCR.

## 5. Data flow

### 5.1 Vanilla LLM baseline

```
question
   ▼
OpenRouter (one call, no tools)
system prompt: "Answer + provide citations as JSON {doc_id, source_url, source_type, span}"
   ▼
narration + (hallucinated) citations
   ▼
JSONL row: { system: "vanilla", question, narration, citations, llm_cost, llm_tokens, latency }
```

The baseline is asked to produce the same JSON shape as Palimpsest. We do not filter or "help" it — if it fabricates citations, those go in as-is. That is the point: fabricated citations fail the CCR check trivially because their `doc_id` does not resolve.

### 5.2 Naive RAG baseline

```
question
   ▼
embedder (same BGE-small singleton as Palimpsest)
   ▼
pgvector top-K=8 (same corpus as Palimpsest)
   ▼
prompt = system + retrieved docs + question
   ▼
OpenRouter (one call, no tools, no agent loop)
   ▼
narration + citations (model picks doc_ids from the retrieved set, or fabricates)
   ▼
JSONL row: { system: "naive_rag", question, retrieved_docs, narration, citations, llm_cost, llm_tokens, latency }
```

Naive RAG uses the same corpus, same embedder, and same model as Palimpsest. The comparison isolates the contribution of the agent loop + verifier specifically.

### 5.3 Palimpsest agent (three retrieval modes)

```
question  ──▶  POST /agent/ask  (existing SSE endpoint, unchanged)
                 │
                 ▼
              agent loop  ──▶  search_places tool
                                  │
                              reads RETRIEVAL_MODE env
                                  │
              ┌───────────────────┼──────────────────────────┐
              ▼                   ▼                          ▼
         dense                hybrid                hybrid_reranked
         (current)         dense ⊕ sparse        dense ⊕ sparse → BGE reranker
                              (RRF fusion)                (top-5 kept)
                                  │
                                  ▼
                          retrieved docs returned via the
                          existing tool-result shape
                                  │
                                  ▼
                          back to agent loop, locked V1 path:
                          narration + 5-field citations + verifier
                                  │
                                  ▼
              JSONL row: { system: "palimpsest-${MODE}", ...same fields..., turns, verified }
```

We produce three eval rows per question for Palimpsest, one per `RETRIEVAL_MODE`. Each row is produced by setting the env var, restarting the API, and re-running the orchestrator.

### 5.4 Grading

```
JSONL results (500 rows: 5 systems × 100 questions)
         │
         ├──▶  hand-grade CSV for the 20-question calibration set
         │       columns: citation_correct ∈ {0,1}, halluc_count, facts_correct,
         │                narration_quality ∈ 1-5
         │
         └──▶  LLM-judge for all 500 rows
                 prompt: rubric + question + system_output + retrieved_docs (if any)
                 model: pinned in judge.yaml (e.g., anthropic/claude-opus-4.7 via OpenRouter)
                 temperature: 0
                 returns: same column set as hand-grade
                                          │
                                          ▼
                                  aggregate.py
                                          │
                       ┌──────────────────┼──────────────────┐
                       ▼                  ▼                  ▼
              per-system means    Cohen's κ          per-region /
              + 95% CI            (hand vs judge)    per-source breakdowns
                                  on calibration set
                                          │
                                          ▼
                                  ablation_table.md + figures
```

Invariants:

- Same JSONL row shape across all 5 systems so `aggregate.py` does not need per-system branching.
- Retrievals are captured in the row for naive RAG and Palimpsest so the LLM-judge can score "is this claim in the retrieved docs?" deterministically without re-fetching.
- Judge model and prompt are pinned in `judge.yaml` and committed; re-running produces stable results up to model temperature, which is set to 0.
- Hand-grade calibration is held out. When we report κ, it is against the 20 calibration questions. When we report headline rates, hand grades are used for those 20 and judge grades for the other 80, with the agreement statistic disclosed.
- No retraining loop. We never tune Palimpsest against the grader. The question bank is committed before any feature work begins.

## 6. Metrics

### 6.1 Headline — Citation Correctness Rate (CCR)

For a single response, let $C$ be the set of emitted citations. A citation $c$ is correct iff:

1. `doc_id` resolves to an actual document in the corpus (verifiable from the JSONL row's `retrieved_docs` field), and
2. the cited `span` is genuinely supported by that document's text (grader judgment), and
3. `source_type` matches the document's provenance.

$$\text{CCR}(\text{response}) = \frac{|\{c \in C : c\text{ correct}\}|}{|C|}\quad\text{if }|C|>0\text{, else 0}$$

System-level CCR is the mean across the 100 questions. For Vanilla LLM, criterion (1) fails on essentially every citation because there is no corpus to resolve against, so CCR is expected near 0% — the dominant signal in the headline number.

Responses with no citations score CCR = 0, to discourage refusing to cite. Out-of-scope questions are scored on the separate GRR metric in §6.5.

### 6.2 Hallucination Rate (HR)

A *factual claim* is a sentence asserting a fact about a place, person, date, or event. The grader (hand or LLM-judge) extracts claims from the narration; for each, marks `supported` if any retrieved document supports it.

$$\text{HR}(\text{response}) = \frac{|\{f \in F : f\text{ unsupported}\}|}{|F|}$$

Reported per system as the mean across questions. Claim extraction is a separate pre-pass with a max of 8 claims per narration; for longer narrations we take the first 8 claims in order (deterministic; no random sampling so that re-runs give the same numbers). The hand-grader follows the same protocol so their numbers are comparable.

### 6.3 Factual Accuracy (FA)

Stricter than HR. For each claim, the grader checks against an external ground-truth source (Wikipedia/Wikidata directly, not what got retrieved). Catches cases where the retrieved doc is itself wrong.

$$\text{FA}(\text{response}) = \frac{|\{f \in F : f\text{ matches ground truth}\}|}{|F|}$$

Because FA is the most labor-intensive metric (the judge must do external lookups; the human must too), it is graded only on the 20-question calibration set plus a 30-question random sample of the remaining 80, for 50 graded. The other 50 questions report CCR + HR only.

### 6.4 Narration Quality (NQ)

LLM-judge rates on a 1–5 Likert scale across four dimensions, averaged: coherence, informativeness, geographic plausibility, style fit (walking-tour register, not encyclopedia/listicle). Scored on all 100 questions (cheap — single LLM call per response, no external lookups needed). Subjective; reported with the caveat that LLM-judge bias is possible. NQ is a supporting metric, not the headline.

### 6.5 Graceful Refusal Rate (GRR) — for out-of-scope questions

10 of the 100 questions are deliberately out of scope (Brooklyn, NYC outside Manhattan, fictional places). For these we do not compute CCR/HR/FA. Instead:

$$\text{GRR}(\text{response}) = 1\text{ if the response correctly refuses or redirects, else }0$$

Vanilla LLM is expected to confabulate (low GRR); Palimpsest is expected to refuse (high GRR). Qualitative row in the table, strong narrative point in the discussion.

### 6.6 Efficiency metrics

| Metric | Definition | Source |
|---|---|---|
| Cost per walk ($) | Sum of OpenRouter `cost` field over all LLM calls for the response | Existing telemetry via `/internal/metrics` |
| Latency p50, p95 | Wall-clock from request to terminal `done`/result | Existing harness |
| Tokens per walk | Sum of prompt + completion tokens over all calls | Existing telemetry |

Reported as distributions so we can render the Pareto frontier figure.

### 6.7 Inter-rater agreement (Cohen's κ)

On the 20-question calibration set, we compute κ between hand and LLM-judge scores on binary metrics (CCR ≥ threshold, HR = 0, per-claim FA). Reported in the methodology section; required for the report to claim the LLM-judge is a reasonable proxy for the broader set. We do not gate the eval on a specific κ value — we report what we measure. Standard "substantial agreement" is κ ≥ 0.6; if we land below, that is an honest limitation in the discussion section (see R2 in §8 for mitigation paths).

## 7. Phases & sequencing

Each phase ends with a committed deliverable before the next starts. If anything slips, the report still has the previous phase's numbers banked.

### Phase 0 — Eval scaffold smoke test (~1 day)

Goal: prove the harness plumbing works before any feature work.

- Create `docs/eval/scripts/run_eval_v2.py` skeleton + `systems.yaml`.
- Implement `baselines/vanilla_llm.py` (~50 lines) and `baselines/naive_rag.py` (~80 lines).
- Implement `graders/llm_judge.py` with pinned `judge.yaml`.
- Smoke test: run vanilla, naive_rag, and current Palimpsest against the existing 15 questions in `docs/eval/questions/v1-router-bench.txt`.
- Hand-grade 3 of those manually and compute κ vs the LLM-judge to validate prompts.

Exit: JSONL output for all 3 systems on the 15-question smoke set; grading runs end-to-end; κ on 3 questions is a sane number.

### Phase 1 — Manhattan corpus expansion (~2–3 days)

Goal: widen the bbox, re-ingest, verify retrieval still works.

- Edit `app/ingest/scope.py`: bump `SCOPE_BBOX` to Manhattan-wide, bump `SCOPE_VERSION`.
- Land `0XX_add_trigram_indexes.sql` migration (needed for hybrid retrieval; landing it now lets the re-ingestion build the index from scratch).
- `make nuke && make up`; run `osm` and `wikipedia` ingestors; expect ~3–5k places + ~1.5–2k docs (verify, see R1).
- Resize OSRM extract per `docs/route-planning-2026-05-04.md`. *Optional — deferrable per R8 if it stalls; the eval headline metrics (CCR / HR / FA / NQ) do not depend on walk geometry.*
- Spot-check 5 Manhattan-specific queries via `/agent/ask`.
- Confirm existing tests still pass.

Exit: `make test` green; manual spot-check returns sensible results outside MH/UWS. If OSRM has been resized, the walk planner produces street-following geometry for SoHo queries; if deferred, the SSE `walk` frame is allowed to be absent for Manhattan-outside-MH queries (already conditional in the existing code path).

### Phase 2 — Question bank synthesis & curation (~2–3 days)

Goal: commit the 100-question bank before any feature work that could be tuned against it.

- Write `synthesize_questions.py`: samples places + templates → ~150 candidates → curation TSV.
- Manually cull and edit to 100, balanced across categories: 30 single-place lookups (varied regions), 25 multi-place themed walks, 20 geographic-constraint queries, 15 per-neighborhood mix, 10 out-of-scope.
- Write `categories.yaml` mapping each question to category + expected region + expected source types.
- Commit to `docs/eval/questions/manhattan-100/` and *tag the commit* so the report can cite "question bank @ commit ABCDEF".

Exit: 100 questions + `categories.yaml` committed and tagged.

### Phase 3 — Baseline + dense Palimpsest measurement (~1–2 days)

Goal: first headline number.

- Run `run_eval_v2.py` against the full 100 questions × 3 systems (vanilla, naive_rag, palimpsest-dense).
- Hand-grade the 20-question calibration set (`docs/eval/grades/calibration.csv`).
- Run LLM-judge on all 300 rows.
- Compute Cohen's κ.
- `aggregate.py` produces the first version of `ablation_table.md` with 3 rows.
- Numbers banked. Even if everything after this slips, you have a publishable comparison.

Exit: `ablation_table.md` committed with the 3 baseline rows + κ value.

### Phase 4 — Hybrid retrieval (~1–2 days)

- Refactor `search_places` to read `RETRIEVAL_MODE`.
- Add `retrieval/sparse.py` (pg_trgm query) and `retrieval/fusion.py` (RRF).
- Tests: `test_retrieval_sparse.py`, `test_retrieval_fusion.py`, `test_retrieval_mode_flag.py`, plus the shape-contract extension to `test_agent_search_places.py`.
- Restart with `RETRIEVAL_MODE=hybrid` and re-run `run_eval_v2.py` for that system row only (100 questions).
- Run the full grading pipeline (CCR + HR + FA on the calibration + sample subsets, NQ on all 100) on the new 100 rows. The existing 300 rows from Phase 3 do not need to be re-graded — their grades are stable. Hand-grade the same 20-question calibration subset for the new system (since the new system's responses to those 20 questions are different from the dense system's).
- Append the new row to `ablation_table.md`; recompute deltas.

Exit: hybrid row in the table; measured lift (or honest null result).

### Phase 5 — Cross-encoder reranker (~1–2 days)

- Add `embeddings/reranker.py` singleton; wire into `main.py` lifespan with conditional construction.
- Modify `search_places` `hybrid_reranked` branch.
- Tests: `test_reranker.py`.
- Restart with `RETRIEVAL_MODE=hybrid_reranked` and re-run 100 questions for that system row.
- Run the full grading pipeline (CCR + HR + FA + NQ) on the new 100 rows, including hand-grading the 20-question calibration subset for this new system.
- Append the final row to `ablation_table.md`.

Exit: all 5 rows in the table.

### Phase 6 — Breakdowns, figures, report numbers (~1–2 days)

- Per-region breakdown via `aggregate.py` reading `categories.yaml`.
- Per-source breakdown (Wikipedia vs OSM).
- Accuracy-vs-latency Pareto scatter.
- Out-of-scope GRR comparison (10 rows × 5 systems).
- Commit final `ablation_table.md`, figure PNGs, and a methodology summary doc.

Exit: all numbers and figures ready for the report.

Total: ~10–15 working days.

## 8. Risks & mitigations

### R1 — Manhattan corpus is much larger than expected

Likelihood medium, impact medium. Widening from a MH/UWS sliver to all of Manhattan could yield 5k–20k OSM places rather than the 3–5k estimate, overloading retrieval latency. Wikipedia/Wikidata SPARQL rate limits may bite over a larger bbox.

Mitigation: after Phase 1, check actual corpus size and retrieval p95. If retrieval is >2s p95 at the larger index, add a per-query bbox filter to `search_places` so the agent can pass a region hint, rather than scoping the whole corpus. Set a hard cost cap on LLM-judge runs (~$10) before kicking off so we cannot accidentally spend $100.

### R2 — LLM-judge has low agreement with hand-grader

Likelihood medium, impact high (this kills the headline number's credibility). If κ < 0.4 on the calibration set, the report cannot credibly use LLM-judge numbers for the other 80 questions.

Mitigation, three layers:

1. Test the judge prompt during Phase 0 against 3 hand-graded questions and iterate before locking.
2. If κ is still low after Phase 3, hand-grade an additional 30 questions (50 total) and report two parallel tables: "headline using hand-graded subset only" and "supporting using full LLM-judged set with caveat."
3. If still bad, the report's headline narrows from "X% better than baseline" to "X% better on the 50 hand-graded subset" — smaller n, still publishable.

### R3 — Reranker on CPU is too slow at p95

Likelihood low–medium, impact low. `bge-reranker-base` on CPU is ~30 ms/pair × top-20 = 600 ms added latency. The walk planner is already slow; adding 600 ms might push some Palimpsest responses past the 180 s eval timeout, especially with multi-turn agent loops.

Mitigation: reduce reranker input to top-12 (~360 ms). Or use an ONNX-quantized reranker. If still bad, mark the reranker as "available but off by default" and report its numbers as a methodology note.

### R4 — Hybrid retrieval does not lift the headline number

Likelihood medium, impact low (academically fine to report a null result). The MH/UWS corpus is small and dense; hybrid may not help. With Manhattan-wide it should help more (sparse signals matter on rarer names), but it is not guaranteed.

Mitigation: a null result on hybrid is publishable ("we measured RRF and found no statistically significant lift over dense-only retrieval on this corpus, suggesting embedding coverage is already saturating"). The report stays valid.

### R5 — Question synthesizer produces biased questions

Likelihood high (this is the standard critique of generated benchmarks), impact medium. If the synthesizer samples places from our corpus and templates questions about them, every question is by construction answerable by our retrieval — vanilla LLM is unfairly disadvantaged, naive RAG unfairly helped.

Mitigation: (a) curation step explicitly rebalances; some questions reference places we do not index. (b) The 10 out-of-scope questions act as a fairness check — these do not appear in our corpus and we measure GRR. (c) The methodology section calls out this limitation transparently; the report's headline reads "CCR on a corpus-sampled benchmark" rather than "CCR in the wild." (d) Optionally pull 20 questions from an external source (e.g., LLM-generated questions about Manhattan landmarks without seeing our corpus) as a "wild" subset.

### R6 — Touching `search_places` breaks the locked V1 contract

Likelihood low (refactor is contained), impact medium. The retrieval refactor must keep `search_places` returning the same tool-result shape so the agent loop, citation verifier, and existing tests do not break.

Mitigation: tests-first. `test_retrieval_mode_flag.py` asserts shape equivalence across all three modes before any production code lands. Add a shape-contract assertion to the existing `test_agent_search_places.py`.

### R7 — pg_trgm + pgvector cardinality on a larger index

Likelihood low, impact low. `gin_trgm_ops` indexes on Manhattan-scale text are large (hundreds of MB); the docker volume will grow.

Mitigation: document volume growth in the migration's comment. Add to `make nuke` notes: expect ~2 GB volume on Manhattan-scale corpus.

### R8 — OSRM extract resize is fiddly

Likelihood medium, impact low. The walk planner depends on the OSRM extract, and resizing it to all of Manhattan is a separate operation from corpus ingestion. The procedure in `docs/route-planning-2026-05-04.md` was authored for the MH-only extract.

Mitigation: the eval does not strictly need the walk planner — citation correctness and hallucination metrics work on narration alone. If OSRM resize takes more than a day, defer it: run the eval with walks disabled (the SSE `walk` frame is already conditional per `feat(api): conditional walk SSE frame`). Address OSRM as a follow-up after the main numbers are banked.

### R9 — Hand-grading is more work than expected

Likelihood medium, impact low. 20 questions × ~5 min × 4 metrics × 5 systems is a few hours of focused work; could stretch to a day if you want to double-check.

Mitigation: reuse and extend the existing rubric template in `docs/walk-eval-checklist.md`. Start with CCR + HR only on the calibration set; defer FA + NQ to LLM-judge only if grading drags.

## 9. Open questions / deferrals

These are tracked as follow-ups, not blockers for this design:

- LLM-as-judge replacement for the inline citation verifier — separate from the eval's grader. Likely cheap to add once the grader is wired, but it touches the locked V1 contract so it gets its own design pass.
- Multi-hop retrieval / query decomposition — academically interesting but high-risk; deferred.
- Live-web baselines (Perplexity, Google Places) — require paid keys; weaker control properties; revisit after main eval is done.
- Additional source types (Chronicling America, NYPL) — remain in V2 backlog; not gated on this design.
