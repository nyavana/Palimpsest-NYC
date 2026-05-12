## ADDED Requirements

### Requirement: Eval harness runs above the API container from a host-side venv

The eval harness SHALL be runnable from the host machine against a running `make up` stack, NOT from inside the API container. Its dependencies SHALL live in `docs/eval/requirements.txt` and SHALL be installed into a host-side venv at `docs/eval/.venv` via `make eval-setup`. The api container's `pyproject.toml` SHALL NOT include matplotlib, PyYAML, or other harness-only dependencies. `.gitignore` SHALL include `docs/eval/.venv/`.

#### Scenario: `make eval-setup` produces a working venv
- **WHEN** the user runs `make eval-setup` on a fresh checkout
- **THEN** `docs/eval/.venv/bin/python -c "import httpx, yaml, matplotlib"` exits 0

#### Scenario: Harness scripts do not import inside the api container
- **WHEN** the user runs `docker compose exec api python -m docs.eval.scripts.run_eval_v2 --help`
- **THEN** the import fails with `ModuleNotFoundError` because the container does not mount `docs/`

### Requirement: Pre-registered 100-question Manhattan bench

The question bank SHALL live in `docs/eval/questions/manhattan-100/`, organized into `single-place.txt` (30), `multi-place.txt` (25), `geographic.txt` (20), `per-neighborhood.txt` (15), and `out-of-scope.txt` (10). A sibling `categories.yaml` SHALL map each question to its category, expected region, and expected source types (`wikipedia`, `osm`, or both). The 100-question commit SHALL be tagged in git so the report can cite "question bank @ commit ABCDEF". The tag SHALL exist BEFORE any retrieval-mode feature work begins.

#### Scenario: Question synthesis produces ~150 candidates for curation
- **WHEN** the user runs `python -m docs.eval.scripts.synthesize_questions`
- **THEN** a curation TSV is written with ~150 templated candidate questions sampled from the corpus

#### Scenario: `categories.yaml` covers every question
- **WHEN** a CI check parses `categories.yaml` against the five `*.txt` files
- **THEN** every question id appears in `categories.yaml` and every category entry references a real question

### Requirement: Vanilla LLM baseline — one-shot OpenRouter call, no retrieval

`docs/eval/scripts/baselines/vanilla_llm.py` SHALL produce one JSONL row per question by issuing a single OpenRouter chat call with a system prompt asking for narration + citations in the V1 JSON shape. Whatever the model fabricates SHALL go into the row unchanged. The row schema SHALL include: `system` (`"vanilla"`), `question`, `narration`, `citations: list[{doc_id, source_url, source_type, span}]`, `retrieved_docs: []`, `llm_cost_usd`, `llm_prompt_tokens`, `llm_completion_tokens`, `latency_s`, `error`.

#### Scenario: Malformed JSON from the model is recorded as an error
- **WHEN** the model returns plain text instead of JSON
- **THEN** the row has `narration: ""`, `citations: []`, and `error` containing the substring `"json"`

#### Scenario: Successful row carries token + cost telemetry
- **WHEN** the model returns valid JSON
- **THEN** the row contains `llm_prompt_tokens`, `llm_completion_tokens`, and `llm_cost_usd` as reported by OpenRouter

### Requirement: Naive-RAG baseline — one-shot retrieval + one-shot generate

`docs/eval/scripts/baselines/naive_rag.py` SHALL: (1) POST the question to `/internal/retrieve` with `top_k=8`, (2) build a prompt with the system instruction, retrieved docs, and the question, (3) issue a single OpenRouter chat call (no agent loop, no verifier), and (4) write a JSONL row with the same schema as the vanilla baseline plus a populated `retrieved_docs` field. The retrieved docs SHALL be the actual hits the LLM saw, not a synthetic placeholder.

#### Scenario: Retrieved docs are stored verbatim
- **WHEN** `/internal/retrieve` returns 8 hits
- **THEN** the JSONL row's `retrieved_docs` field contains all 8 hits with the same fields they came back with

#### Scenario: Citations that reference retrieved docs pass downstream grading
- **WHEN** the LLM cites a `doc_id` that appeared in `retrieved_docs`
- **THEN** the grader can resolve the citation against the row's `retrieved_docs` without any external lookup

### Requirement: Palimpsest baseline — POST SSE consumer

`docs/eval/scripts/baselines/palimpsest.py` SHALL consume `/agent/ask` via a POST + JSON body (per V1.1 — the live route is POST, not GET) using the new `sse_client.py` helper. It SHALL flatten `search_places.results` and `plan_walk.discovered_stops` from every `tool_result` SSE frame into a single `retrieved_docs` list on the output row, then enrich `body_excerpt` for those ids by calling `/internal/documents/by_ids`. The output row SHALL match the same schema as the vanilla and naive-RAG rows so `aggregate.py` does not need per-system branching.

#### Scenario: Tool-result frames are captured across multiple turns
- **WHEN** the agent loop makes 2 tool calls before terminating
- **THEN** `retrieved_docs` contains the union of hits from both `tool_result` frames

#### Scenario: Body excerpts are enriched via `/internal/documents/by_ids`
- **WHEN** the SSE `tool_result` frames carry only `doc_id` + `span`
- **THEN** the row's `retrieved_docs` is enriched by a single call to `/internal/documents/by_ids` before grading

### Requirement: LLM-judge grader with pinned model and prompt version

`docs/eval/scripts/graders/llm_judge.py` SHALL grade each JSONL row using the model + prompt configured in `docs/eval/scripts/judge.yaml`. The judge call SHALL use temperature 0 and SHALL produce per-row scores for: CCR (citation correctness rate), HR (hallucination rate), FA (factual accuracy — only on calibration + 30-question sample), NQ (narration quality 1–5 Likert), and GRR (graceful refusal — only on the 10 out-of-scope questions). `judge.yaml` SHALL include a `prompt_version` field that is bumped any time the rubric prompts change.

#### Scenario: Judge re-runs are stable up to model stochasticity
- **WHEN** the user re-runs the judge over the same JSONL with the same `judge.yaml`
- **THEN** scores are stable to within rounding at temperature 0; differences are attributable only to model nondeterminism

#### Scenario: Prompt version is recorded on every graded row
- **WHEN** a graded row is written
- **THEN** the row carries `prompt_version` so post-hoc analysis can distinguish rubric edits from model changes

### Requirement: Aggregator computes per-system means, 95% CIs, and Cohen's κ

`docs/eval/scripts/aggregate.py` SHALL join LLM-judge and hand-grade CSVs by `(system, question_id)` and compute: per-system mean for each metric with 95% confidence intervals, per-region and per-source breakdowns driven by `categories.yaml`, an accuracy-vs-latency Pareto scatter, and Cohen's κ between hand and LLM-judge grades on the 20-question calibration subset. It SHALL emit `docs/eval/results/ablation_table.md` and figure PNGs under `docs/eval/results/figures/`.

#### Scenario: Hand grades and judge grades on the calibration set are joined
- **WHEN** `aggregate.py` runs with both hand grades (CSV) and judge grades (JSONL) on the calibration 20 questions
- **THEN** Cohen's κ is computed for each binary metric (CCR ≥ threshold, HR = 0) and reported in the methodology section

#### Scenario: Aggregator joins on (system, question_id), not on hand-graded subset implicitly
- **WHEN** hand grades exist for 20 questions × 5 systems and judge grades exist for 100 × 5
- **THEN** the headline table uses hand grades for the 20 calibration rows and judge grades for the other 80 per system, with κ disclosed as a separate row

### Requirement: Final deliverable — ablation table with five rows

`docs/eval/results/ablation_table.md` SHALL contain a markdown table with one row per system: Vanilla LLM, Naive RAG, Palimpsest (dense), Palimpsest (+ hybrid), Palimpsest (+ reranker). Columns: CCR ↑, HR ↓, FA ↑, NQ ↑, Cost/walk ↓, p50 latency ↓, p95 latency ↓, Tokens/walk ↓, GRR ↑. Cells SHALL include 95% CIs in parentheses where applicable. Three supplementary figures SHALL accompany it: per-region CCR bar chart, per-source CCR bar chart (Wikipedia vs OSM), and accuracy-vs-latency Pareto scatter.

#### Scenario: Table is regeneratable from JSONL + CSV inputs
- **WHEN** the user runs `python -m docs.eval.scripts.aggregate`
- **THEN** `ablation_table.md` is overwritten with the freshly-aggregated numbers and the supplementary figure PNGs are regenerated

### Requirement: Reproducibility — pinned configs committed in git

`docs/eval/scripts/systems.yaml` SHALL pin per-system model, base URL, and retrieval mode. `docs/eval/scripts/judge.yaml` SHALL pin judge model, base URL, temperature (0), `max_tokens`, `prompt_version`, and the metric list. `docs/eval/requirements.txt` SHALL pin major versions for httpx, PyYAML, matplotlib, redis, pytest, pytest-asyncio. Re-running with the same configs SHALL produce stable numbers up to LLM stochasticity (mitigated by temperature 0).

#### Scenario: Re-running the eval against the same configs produces matching numbers
- **WHEN** the user runs the full pipeline on the same machine 24 hours apart with no config changes
- **THEN** the resulting `ablation_table.md` differs only in stochastic LLM cells, never in deterministic columns (token counts, latency p50)

### Requirement: TDD discipline on every harness module

Each new harness module (baselines, graders, rubric, aggregator, synthesizer) SHALL land with a failing test BEFORE implementation. Tests SHALL assert (a) JSONL row shape conformance so `aggregate.py` does not need per-system branching, (b) RRF / κ math against hand-crafted fixtures, (c) baseline error handling on malformed model output, and (d) synthesis template coverage. Tests SHALL live under `docs/eval/scripts/tests/`.

#### Scenario: Baseline test fails before implementation exists
- **WHEN** the test for `run_vanilla` is written before `vanilla_llm.py` exists
- **THEN** `pytest` reports `ModuleNotFoundError` and the implementation is written to make it pass

### Requirement: Cost cap on judge runs

`run_eval_v2.py` (or the grader) SHALL enforce a hard cost cap (default $10) summed across all judge calls in a single invocation, and SHALL abort with a clear error before the cap is exceeded. The cap SHALL be settable via CLI flag and SHALL be logged at the start of each run.

#### Scenario: Cap is reached mid-run
- **WHEN** the cumulative judge cost crosses the configured cap
- **THEN** the orchestrator aborts cleanly, leaving partial results on disk, and prints a summary of completed vs remaining work
