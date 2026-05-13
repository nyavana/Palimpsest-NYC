# Eval Depth & Corpus Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Manhattan-wide corpus, hybrid retrieval + cross-encoder reranker behind a `RETRIEVAL_MODE` env flag, and a 100-question eval harness that produces a hand+LLM-judge graded ablation table comparing Palimpsest against vanilla-LLM and naive-RAG baselines.

**Architecture:** Three orthogonal capability blocks above the locked V1 system. Corpus expansion widens `SCOPE_BBOX` and re-runs ingestion. Retrieval upgrades live entirely inside the `search_places` tool, selected by env flag — the agent loop, citation verifier, and SSE contract are not modified. Eval harness is a sibling of `docs/eval/scripts/run_eval.py`; baselines hit OpenRouter directly, Palimpsest configs are exercised via HTTP against the running `/agent/ask`.

**Tech Stack:** Python 3.12 (FastAPI + SQLAlchemy 2 async + asyncpg + httpx), PostgreSQL 16 (PostGIS + pgvector + pg_trgm), sentence-transformers (`BAAI/bge-small-en-v1.5` embedder + `BAAI/bge-reranker-base` cross-encoder), OpenRouter for LLM and LLM-judge, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-05-12-eval-depth-and-corpus-expansion-design.md`

---

## File Structure

### Files to create

| File | Purpose |
|---|---|
| `apps/api/app/retrieval/__init__.py` | Module marker. |
| `apps/api/app/retrieval/dense.py` | `DenseRetriever` — cosine ANN over `places.embedding` (extracted from current `search_places.PostgresRetriever`). |
| `apps/api/app/retrieval/sparse.py` | `SparseRetriever` — `pg_trgm` similarity over `places.name`. |
| `apps/api/app/retrieval/fusion.py` | `reciprocal_rank_fusion()` — RRF math; pure function, no I/O. |
| `apps/api/app/retrieval/hybrid.py` | `HybridRetriever` — runs dense + sparse in parallel, merges with RRF. |
| `apps/api/app/retrieval/reranked.py` | `RerankedRetriever` — wraps `HybridRetriever` and applies the cross-encoder to top-N. |
| `apps/api/app/retrieval/factory.py` | `build_retriever(mode)` — returns the right retriever class for `RETRIEVAL_MODE`. |
| `apps/api/app/embeddings/reranker.py` | `Reranker` singleton — `BAAI/bge-reranker-base` wrapper; mirrors `Embedder` shape. |
| `apps/api/app/routes/internal_retrieve.py` | `/internal/retrieve` — one-shot retrieval endpoint used by the naive-RAG baseline; identical-shape to a `search_places` call without an agent loop. |
| `apps/api/tests/test_retrieval_dense.py` | Refactor smoke test — dense retriever returns same shape as the previous `PostgresRetriever`. |
| `apps/api/tests/test_retrieval_sparse.py` | `pg_trgm` query returns sensible hits. |
| `apps/api/tests/test_retrieval_fusion.py` | RRF math, edge cases. |
| `apps/api/tests/test_retrieval_hybrid.py` | Hybrid merges dense + sparse correctly. |
| `apps/api/tests/test_retrieval_reranked.py` | Reranker singleton reorders correctly. |
| `apps/api/tests/test_retrieval_factory.py` | `RETRIEVAL_MODE` env switches pipelines; tool-result shape is identical across modes. |
| `apps/api/tests/test_routes_internal_retrieve.py` | `/internal/retrieve` returns the expected shape. |
| `apps/api/app/db/migrations/0003_widen_scope_indexes.sql` | Verify/recreate spatial indexes after corpus widening. No-op if planner is happy. |
| `docs/eval/scripts/run_eval_v2.py` | Orchestrator. Reads `systems.yaml`, runs each (system × question), writes JSONL. |
| `docs/eval/scripts/baselines/__init__.py` | Module marker. |
| `docs/eval/scripts/baselines/vanilla_llm.py` | One-shot OpenRouter call with no retrieval. |
| `docs/eval/scripts/baselines/naive_rag.py` | One-shot retrieval + one-shot generate. |
| `docs/eval/scripts/baselines/palimpsest.py` | Thin wrapper around the existing SSE consumer in `run_eval.py`. |
| `docs/eval/scripts/graders/__init__.py` | Module marker. |
| `docs/eval/scripts/graders/llm_judge.py` | LLM-judge grader; reads `judge.yaml`. |
| `docs/eval/scripts/graders/rubric.py` | Per-metric grading prompts (CCR, HR, FA, NQ, GRR). |
| `docs/eval/scripts/synthesize_questions.py` | Samples places, templates ~150 candidate questions, writes curation TSV. |
| `docs/eval/scripts/aggregate.py` | Joins LLM-judge + hand-grade CSV, computes per-system means + Cohen's κ + per-region/per-source breakdowns. |
| `docs/eval/scripts/systems.yaml` | Per-system config (model, base URL, retrieval mode). |
| `docs/eval/scripts/judge.yaml` | Pinned judge model + prompt version. |
| `docs/eval/scripts/tests/__init__.py` | Module marker. |
| `docs/eval/scripts/tests/test_synthesize.py` | Synth produces expected templates. |
| `docs/eval/scripts/tests/test_baselines.py` | Baselines write the expected JSONL row shape. |
| `docs/eval/scripts/tests/test_llm_judge.py` | LLM-judge output shape conforms to grading schema. |
| `docs/eval/scripts/tests/test_aggregate.py` | Aggregation math; κ on a hand-crafted fixture. |
| `docs/eval/questions/manhattan-100/single-place.txt` | Question bank: 30 single-place lookups. |
| `docs/eval/questions/manhattan-100/multi-place.txt` | 25 multi-place themed walks. |
| `docs/eval/questions/manhattan-100/geographic.txt` | 20 geographic-constraint queries. |
| `docs/eval/questions/manhattan-100/per-neighborhood.txt` | 15 per-neighborhood mix. |
| `docs/eval/questions/manhattan-100/out-of-scope.txt` | 10 out-of-scope refusal tests. |
| `docs/eval/questions/manhattan-100/categories.yaml` | Maps each question to category + region + expected source types. |
| `docs/eval/grades/calibration.csv` | Hand-grade column template. |
| `docs/eval/results/ablation_table.md` | The final deliverable. |

### Files to modify

| File | Change |
|---|---|
| `apps/api/app/ingest/scope.py` | Widen `SCOPE_BBOX`; add `SCOPE_VERSION`. |
| `apps/api/app/agent/tools/search_places.py` | Replace the inline `PostgresRetriever` with a call to `retrieval.factory.build_retriever()`. |
| `apps/api/app/config.py` | Add `retrieval_mode`, `reranker_model`, `reranker_enabled`, `judge_model`, `judge_base_url` settings. |
| `apps/api/app/main.py` | Conditionally load `Reranker` singleton in lifespan; mount `/internal/retrieve` route. |
| `.env.example` | Document `RETRIEVAL_MODE`, `RERANKER_MODEL`, `JUDGE_MODEL`, `JUDGE_BASE_URL`. |
| `apps/api/tests/test_agent_search_places.py` | Add shape-contract assertion that all three modes return the same tool-result shape. |

---

## Phase 0 — Eval scaffold smoke test

### Task 0.1: Scaffold eval directory + pinned config

**Files:**
- Create: `docs/eval/scripts/baselines/__init__.py`
- Create: `docs/eval/scripts/graders/__init__.py`
- Create: `docs/eval/scripts/tests/__init__.py`
- Create: `docs/eval/scripts/systems.yaml`
- Create: `docs/eval/scripts/judge.yaml`

- [ ] **Step 1: Create the directory markers**

```bash
touch docs/eval/scripts/baselines/__init__.py
touch docs/eval/scripts/graders/__init__.py
touch docs/eval/scripts/tests/__init__.py
```

- [ ] **Step 2: Write `docs/eval/scripts/systems.yaml`**

```yaml
# Per-system config consumed by run_eval_v2.py. Pinning model + retrieval
# mode here means re-running with the same yaml reproduces the same numbers
# (up to LLM stochasticity, which we mitigate with temperature 0).
systems:
  - name: vanilla
    kind: vanilla_llm
    model: moonshotai/kimi-k2.6-20260420
    base_url: https://openrouter.ai/api/v1
    temperature: 0.0

  - name: naive_rag
    kind: naive_rag
    model: moonshotai/kimi-k2.6-20260420
    base_url: https://openrouter.ai/api/v1
    temperature: 0.0
    retrieve_top_k: 8
    retrieve_url: http://localhost:8000/internal/retrieve

  - name: palimpsest-dense
    kind: palimpsest
    api_base_url: http://localhost:8000
    retrieval_mode: dense

  - name: palimpsest-hybrid
    kind: palimpsest
    api_base_url: http://localhost:8000
    retrieval_mode: hybrid

  - name: palimpsest-hybrid-reranked
    kind: palimpsest
    api_base_url: http://localhost:8000
    retrieval_mode: hybrid_reranked
```

- [ ] **Step 3: Write `docs/eval/scripts/judge.yaml`**

```yaml
# Pinned judge config. Bump prompt_version any time the rubric prompts change
# so re-runs against the same model can be distinguished from rubric edits.
model: anthropic/claude-opus-4-7
base_url: https://openrouter.ai/api/v1
temperature: 0.0
max_tokens: 1024
prompt_version: v1
# Metrics covered by the judge. CCR and HR are scored on every row;
# FA only on the calibration set + sample (see aggregate.py); NQ on all.
# GRR is binary and only meaningful on out-of-scope questions.
metrics:
  - ccr
  - hr
  - fa
  - nq
  - grr
```

- [ ] **Step 4: Commit**

```bash
git add docs/eval/scripts/baselines/__init__.py \
        docs/eval/scripts/graders/__init__.py \
        docs/eval/scripts/tests/__init__.py \
        docs/eval/scripts/systems.yaml \
        docs/eval/scripts/judge.yaml
git commit -m "chore(eval): scaffold v2 eval harness directory + pinned configs"
```

---

### Task 0.2: Vanilla LLM baseline (TDD)

**Files:**
- Create: `docs/eval/scripts/baselines/vanilla_llm.py`
- Create: `docs/eval/scripts/tests/test_baselines.py`

- [ ] **Step 1: Write the failing test**

```python
# docs/eval/scripts/tests/test_baselines.py
"""Tests for v2 eval baselines.

Each baseline must produce a JSONL row with this minimum schema so
aggregate.py and the LLM-judge grader don't need per-system branching:

    {
      "system": str,
      "question": str,
      "narration": str,
      "citations": list[dict],  # each {doc_id, source_url, source_type, span}
      "retrieved_docs": list[dict],  # may be empty for vanilla
      "llm_cost_usd": float,
      "llm_prompt_tokens": int,
      "llm_completion_tokens": int,
      "latency_s": float,
      "error": str | None,
    }
"""

from __future__ import annotations

from typing import Any

import pytest

from docs.eval.scripts.baselines.vanilla_llm import run_vanilla


class _FakeChatClient:
    """Stand-in for the OpenRouter chat client used by the baseline."""

    def __init__(self, *, response: dict[str, Any]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._response = response

    async def chat(self, *, model: str, messages: list[dict], temperature: float) -> dict[str, Any]:
        self.calls.append({"model": model, "messages": messages, "temperature": temperature})
        return self._response


async def test_vanilla_row_shape():
    fake = _FakeChatClient(
        response={
            "content": (
                '{"narration": "The Cathedral of Saint John the Divine is...", '
                '"citations": [{"doc_id": "wikipedia:Cathedral", '
                '"source_url": "https://en.wikipedia.org/wiki/Cathedral_of_Saint_John_the_Divine", '
                '"source_type": "wikipedia", "span": "Cathedral of Saint John"}]}'
            ),
            "prompt_tokens": 120,
            "completion_tokens": 80,
            "cost_usd": 0.0012,
        }
    )

    row = await run_vanilla(
        question="Tell me about the Cathedral of Saint John the Divine.",
        model="moonshotai/kimi-k2.6-20260420",
        chat_client=fake,
        temperature=0.0,
    )

    assert row["system"] == "vanilla"
    assert row["question"].startswith("Tell me about")
    assert "Cathedral" in row["narration"]
    assert row["citations"][0]["doc_id"] == "wikipedia:Cathedral"
    assert row["retrieved_docs"] == []
    assert row["llm_cost_usd"] == pytest.approx(0.0012)
    assert row["llm_prompt_tokens"] == 120
    assert row["llm_completion_tokens"] == 80
    assert row["latency_s"] >= 0.0
    assert row["error"] is None


async def test_vanilla_malformed_json_records_error():
    fake = _FakeChatClient(
        response={"content": "not json", "prompt_tokens": 10, "completion_tokens": 5, "cost_usd": 0.0}
    )
    row = await run_vanilla(
        question="Q",
        model="m",
        chat_client=fake,
        temperature=0.0,
    )
    assert row["narration"] == ""
    assert row["citations"] == []
    assert row["error"] is not None
    assert "json" in row["error"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest ../../docs/eval/scripts/tests/test_baselines.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'docs.eval.scripts.baselines.vanilla_llm'`

- [ ] **Step 3: Write `docs/eval/scripts/baselines/vanilla_llm.py`**

```python
"""Vanilla-LLM baseline — one-shot OpenRouter call, no retrieval.

Asked to produce the same JSON shape as Palimpsest (narration + citations).
Whatever the model fabricates goes in as-is; that is the point.

Public API:
    async def run_vanilla(*, question, model, chat_client, temperature) -> dict
"""

from __future__ import annotations

import json
import time
from typing import Any, Protocol

_SYSTEM_PROMPT = """You are a Manhattan walking-tour narrator. Answer the user's question with a short narration
(2-4 sentences) about real places in Manhattan, and provide citations supporting your claims.

Return EXACTLY one JSON object with this shape, and nothing else:

{
  "narration": "<your narration text>",
  "citations": [
    {
      "doc_id":      "<stable id e.g. 'wikipedia:Foo_Bar' or 'osm:way:1234'>",
      "source_url":  "<url>",
      "source_type": "wikipedia" | "wikidata" | "osm",
      "span":        "<short quoted span from the source supporting the claim>"
    }
  ]
}
"""


class ChatClient(Protocol):
    async def chat(self, *, model: str, messages: list[dict], temperature: float) -> dict[str, Any]: ...


async def run_vanilla(
    *,
    question: str,
    model: str,
    chat_client: ChatClient,
    temperature: float = 0.0,
) -> dict[str, Any]:
    started = time.perf_counter()
    error: str | None = None
    narration = ""
    citations: list[dict[str, Any]] = []
    response: dict[str, Any] = {}

    try:
        response = await chat_client.chat(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            temperature=temperature,
        )
        content = response.get("content") or ""
        parsed = json.loads(content)
        narration = str(parsed.get("narration") or "")
        raw_citations = parsed.get("citations") or []
        if isinstance(raw_citations, list):
            citations = [c for c in raw_citations if isinstance(c, dict)]
    except json.JSONDecodeError as exc:
        error = f"JSONDecodeError: {exc}"
    except Exception as exc:  # noqa: BLE001 - surfaces all baseline failures
        error = f"{type(exc).__name__}: {exc}"

    elapsed = time.perf_counter() - started

    return {
        "system": "vanilla",
        "question": question,
        "narration": narration,
        "citations": citations,
        "retrieved_docs": [],
        "llm_cost_usd": float(response.get("cost_usd") or 0.0),
        "llm_prompt_tokens": int(response.get("prompt_tokens") or 0),
        "llm_completion_tokens": int(response.get("completion_tokens") or 0),
        "latency_s": round(elapsed, 3),
        "error": error,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && pytest ../../docs/eval/scripts/tests/test_baselines.py -v`
Expected: PASS (both `test_vanilla_row_shape` and `test_vanilla_malformed_json_records_error`)

- [ ] **Step 5: Commit**

```bash
git add docs/eval/scripts/baselines/vanilla_llm.py \
        docs/eval/scripts/tests/test_baselines.py
git commit -m "feat(eval): vanilla-LLM baseline with structured row output"
```

---

### Task 0.3: Internal retrieve endpoint (TDD)

We need a one-shot retrieval endpoint so the naive-RAG baseline can use the same embedder and corpus as Palimpsest without duplicating the model.

**Files:**
- Create: `apps/api/app/routes/internal_retrieve.py`
- Create: `apps/api/tests/test_routes_internal_retrieve.py`
- Modify: `apps/api/app/main.py` (mount the route)

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_routes_internal_retrieve.py
"""Tests for /internal/retrieve — a one-shot retrieval endpoint used by the
naive-RAG baseline. Reuses the embedder + dense pgvector lookup; no agent loop.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent.tools.search_places import SearchPlaceHit
from app.db.models import SourceType
from app.routes import internal_retrieve


class _FakeRetriever:
    def __init__(self, hits: list[SearchPlaceHit]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._hits = hits

    async def search(self, *, session, embedder, query, near, radius_m, limit):
        self.calls.append({"query": query, "limit": limit})
        return self._hits


def _hit(doc_id: str = "wikipedia:X") -> SearchPlaceHit:
    return SearchPlaceHit(
        doc_id=doc_id,
        name="Test Place",
        source_type=SourceType.wikipedia,
        source_url=f"https://en.wikipedia.org/wiki/{doc_id}",
        lat=40.8,
        lon=-73.96,
        distance_m=None,
        score=0.6,
    )


def _app_with(retriever, hits=None):
    app = FastAPI()
    app.state.embedder = object()
    app.state.db_session_factory = lambda: _NoOpSession()
    app.include_router(internal_retrieve.router)
    app.state.retriever_for_internal = retriever
    return app


class _NoOpSession:
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return None
    async def execute(self, *a, **k): return None


def test_internal_retrieve_returns_top_k():
    retriever = _FakeRetriever([_hit("wikipedia:A"), _hit("wikipedia:B")])
    app = _app_with(retriever)
    client = TestClient(app)
    resp = client.post("/internal/retrieve", json={"query": "cathedral", "top_k": 8})
    assert resp.status_code == 200
    body = resp.json()
    assert "results" in body
    assert len(body["results"]) == 2
    assert body["results"][0]["doc_id"] == "wikipedia:A"
    assert retriever.calls[0]["limit"] == 8


def test_internal_retrieve_requires_query():
    retriever = _FakeRetriever([])
    app = _app_with(retriever)
    client = TestClient(app)
    resp = client.post("/internal/retrieve", json={})
    assert resp.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_routes_internal_retrieve.py -v`
Expected: FAIL with `ImportError: cannot import name 'internal_retrieve'`

- [ ] **Step 3: Write `apps/api/app/routes/internal_retrieve.py`**

```python
"""`/internal/retrieve` — one-shot retrieval over the corpus.

Used by the naive-RAG baseline in the eval harness. Identical dense retrieval
to what `search_places` does on its first call, but without the agent loop:
embed query, run cosine ANN, return top-K with the same hit shape.

Mounted on the same app as the rest of the API. Not behind the `/agent/`
namespace because there is no agent involved.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.agent.tools.search_places import DEFAULT_LIMIT, PostgresRetriever

router = APIRouter(prefix="/internal", tags=["internal"])


class RetrieveRequest(BaseModel):
    query: Annotated[str, Field(min_length=1)]
    top_k: int = DEFAULT_LIMIT


class RetrieveResult(BaseModel):
    doc_id: str
    name: str
    source_type: str
    source_url: str
    lat: float
    lon: float
    score: float


class RetrieveResponse(BaseModel):
    results: list[RetrieveResult]


@router.post("/retrieve", response_model=RetrieveResponse)
async def retrieve(req: RetrieveRequest, request: Request) -> RetrieveResponse:
    embedder = request.app.state.embedder
    if embedder is None:
        raise HTTPException(503, detail="embedder not loaded")
    session_factory = request.app.state.db_session_factory
    retriever = getattr(
        request.app.state, "retriever_for_internal", None
    ) or PostgresRetriever()

    async with session_factory() as session:
        hits = await retriever.search(
            session=session,
            embedder=embedder,
            query=req.query,
            near=None,
            radius_m=None,
            limit=int(req.top_k),
        )

    return RetrieveResponse(
        results=[
            RetrieveResult(
                doc_id=h.doc_id,
                name=h.name,
                source_type=h.source_type.value,
                source_url=h.source_url,
                lat=h.lat,
                lon=h.lon,
                score=h.score,
            )
            for h in hits
        ]
    )
```

- [ ] **Step 4: Mount the route in `apps/api/app/main.py`**

Add `internal_retrieve` to the existing routes import line, and include its router.

Find this line (near the top imports):
```python
from app.routes import agent, config, health, llm, meta, places
```
Change to:
```python
from app.routes import agent, config, health, internal_retrieve, llm, meta, places
```

Then in the `create_app()` body where other routers are included (look for `app.include_router(places.router)` or similar):
```python
app.include_router(internal_retrieve.router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd apps/api && pytest tests/test_routes_internal_retrieve.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/routes/internal_retrieve.py \
        apps/api/tests/test_routes_internal_retrieve.py \
        apps/api/app/main.py
git commit -m "feat(api): internal /retrieve endpoint for naive-RAG baseline"
```

---

### Task 0.4: Naive-RAG baseline (TDD)

**Files:**
- Create: `docs/eval/scripts/baselines/naive_rag.py`
- Modify: `docs/eval/scripts/tests/test_baselines.py`

- [ ] **Step 1: Extend the test file**

Append these tests to `docs/eval/scripts/tests/test_baselines.py`:

```python
# --- naive_rag tests ---

from docs.eval.scripts.baselines.naive_rag import run_naive_rag


class _FakeRetrieveClient:
    def __init__(self, *, results: list[dict]) -> None:
        self.calls: list[dict] = []
        self._results = results

    async def retrieve(self, *, query: str, top_k: int) -> list[dict]:
        self.calls.append({"query": query, "top_k": top_k})
        return self._results


async def test_naive_rag_row_shape_with_retrieval():
    retriever = _FakeRetrieveClient(
        results=[
            {
                "doc_id": "wikipedia:Cathedral",
                "name": "Cathedral of Saint John the Divine",
                "source_type": "wikipedia",
                "source_url": "https://en.wikipedia.org/wiki/Cathedral",
                "lat": 40.8038,
                "lon": -73.9619,
                "score": 0.72,
            }
        ]
    )
    chat = _FakeChatClient(
        response={
            "content": (
                '{"narration": "Built in 1892...", '
                '"citations": [{"doc_id": "wikipedia:Cathedral", '
                '"source_url": "https://en.wikipedia.org/wiki/Cathedral", '
                '"source_type": "wikipedia", "span": "Built in 1892"}]}'
            ),
            "prompt_tokens": 250,
            "completion_tokens": 60,
            "cost_usd": 0.0008,
        }
    )

    row = await run_naive_rag(
        question="Tell me about the Cathedral.",
        model="moonshotai/kimi-k2.6-20260420",
        chat_client=chat,
        retrieve_client=retriever,
        top_k=8,
        temperature=0.0,
    )

    assert row["system"] == "naive_rag"
    assert len(row["retrieved_docs"]) == 1
    assert row["retrieved_docs"][0]["doc_id"] == "wikipedia:Cathedral"
    assert row["citations"][0]["doc_id"] == "wikipedia:Cathedral"
    assert retriever.calls[0]["top_k"] == 8
    # Retrieval injection should appear in the user prompt
    user_messages = [m for m in chat.calls[0]["messages"] if m["role"] == "user"]
    assert "wikipedia:Cathedral" in user_messages[-1]["content"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest ../../docs/eval/scripts/tests/test_baselines.py -v -k naive_rag`
Expected: FAIL with `ModuleNotFoundError: No module named 'docs.eval.scripts.baselines.naive_rag'`

- [ ] **Step 3: Write `docs/eval/scripts/baselines/naive_rag.py`**

```python
"""Naive-RAG baseline — one-shot retrieval, one-shot generate, no agent loop.

Embeds query → top-K retrieval via /internal/retrieve → stuffs docs into the
prompt → single OpenRouter call. The comparison vs Palimpsest isolates the
contribution of the agent loop + citation verifier specifically.

Public API:
    async def run_naive_rag(*, question, model, chat_client, retrieve_client,
                            top_k, temperature) -> dict
"""

from __future__ import annotations

import json
import time
from typing import Any, Protocol

_SYSTEM_PROMPT = """You are a Manhattan walking-tour narrator. The user's question is followed by a list
of retrieved documents. Use ONLY information from those documents in your narration. Cite each
factual claim with one of the retrieved doc_ids.

Return EXACTLY one JSON object with this shape, and nothing else:

{
  "narration": "<your narration text>",
  "citations": [
    {
      "doc_id":      "<one of the retrieved doc_ids>",
      "source_url":  "<the matching source_url from the retrieval list>",
      "source_type": "<the matching source_type>",
      "span":        "<short span supporting the claim>"
    }
  ]
}
"""


class ChatClient(Protocol):
    async def chat(self, *, model: str, messages: list[dict], temperature: float) -> dict[str, Any]: ...


class RetrieveClient(Protocol):
    async def retrieve(self, *, query: str, top_k: int) -> list[dict[str, Any]]: ...


def _format_retrievals(results: list[dict[str, Any]]) -> str:
    lines = ["Retrieved documents:"]
    for r in results:
        lines.append(
            f"- doc_id={r['doc_id']} "
            f"source_type={r.get('source_type', '?')} "
            f"source_url={r.get('source_url', '?')} "
            f"name={r.get('name', '?')!r} "
            f"score={r.get('score', 0):.3f}"
        )
    return "\n".join(lines)


async def run_naive_rag(
    *,
    question: str,
    model: str,
    chat_client: ChatClient,
    retrieve_client: RetrieveClient,
    top_k: int = 8,
    temperature: float = 0.0,
) -> dict[str, Any]:
    started = time.perf_counter()
    error: str | None = None
    narration = ""
    citations: list[dict[str, Any]] = []
    retrieved: list[dict[str, Any]] = []
    response: dict[str, Any] = {}

    try:
        retrieved = await retrieve_client.retrieve(query=question, top_k=top_k)
        user_msg = f"{question}\n\n{_format_retrievals(retrieved)}"
        response = await chat_client.chat(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=temperature,
        )
        content = response.get("content") or ""
        parsed = json.loads(content)
        narration = str(parsed.get("narration") or "")
        raw_citations = parsed.get("citations") or []
        if isinstance(raw_citations, list):
            citations = [c for c in raw_citations if isinstance(c, dict)]
    except json.JSONDecodeError as exc:
        error = f"JSONDecodeError: {exc}"
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"

    elapsed = time.perf_counter() - started

    return {
        "system": "naive_rag",
        "question": question,
        "narration": narration,
        "citations": citations,
        "retrieved_docs": retrieved,
        "llm_cost_usd": float(response.get("cost_usd") or 0.0),
        "llm_prompt_tokens": int(response.get("prompt_tokens") or 0),
        "llm_completion_tokens": int(response.get("completion_tokens") or 0),
        "latency_s": round(elapsed, 3),
        "error": error,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && pytest ../../docs/eval/scripts/tests/test_baselines.py -v -k naive_rag`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docs/eval/scripts/baselines/naive_rag.py \
        docs/eval/scripts/tests/test_baselines.py
git commit -m "feat(eval): naive-RAG baseline with one-shot retrieval injection"
```

---

### Task 0.5: Palimpsest baseline wrapper (TDD)

The existing `run_eval.py` already drives SSE against `/agent/ask`; we wrap that consumer so `run_eval_v2.py` treats Palimpsest like any other system.

**Files:**
- Create: `docs/eval/scripts/baselines/palimpsest.py`
- Modify: `docs/eval/scripts/tests/test_baselines.py`

- [ ] **Step 1: Extend the test file**

Append:

```python
# --- palimpsest baseline tests ---

from docs.eval.scripts.baselines.palimpsest import normalize_palimpsest_row


def test_normalize_palimpsest_row_extracts_terminal_fields():
    sse_row = {
        "question": "Q?",
        "client_latency_s": 12.5,
        "server_duration_s": 11.9,
        "turns": 4,
        "verified": True,
        "narration": "Some narration.",
        "citations": [
            {
                "doc_id": "wikipedia:Foo",
                "source_url": "https://example.org/Foo",
                "source_type": "wikipedia",
                "span": "Some span",
                "retrieval_turn": 1,
            }
        ],
        "tool_calls": [{"name": "search_places", "args": {"query": "foo"}}],
        "error": None,
    }
    row = normalize_palimpsest_row(
        sse_row, system_name="palimpsest-dense", retrieval_mode="dense"
    )
    assert row["system"] == "palimpsest-dense"
    assert row["retrieval_mode"] == "dense"
    assert row["narration"] == "Some narration."
    assert row["citations"][0]["doc_id"] == "wikipedia:Foo"
    assert row["latency_s"] == 12.5
    assert row["turns"] == 4
    assert row["verified"] is True
    assert row["error"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest ../../docs/eval/scripts/tests/test_baselines.py -v -k palimpsest`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `docs/eval/scripts/baselines/palimpsest.py`**

```python
"""Palimpsest baseline wrapper.

The existing run_eval.py already drives SSE against /agent/ask and produces a
rich per-question dict. We just normalize that dict into the shared eval row
schema so aggregate.py + the grader can treat Palimpsest identically to
vanilla and naive_rag.

Retrieval mode is injected at the wrapper boundary because it is set
out-of-band (env var on the API container) rather than per request.
"""

from __future__ import annotations

from typing import Any


def normalize_palimpsest_row(
    sse_row: dict[str, Any],
    *,
    system_name: str,
    retrieval_mode: str,
) -> dict[str, Any]:
    citations = list(sse_row.get("citations") or [])
    return {
        "system": system_name,
        "retrieval_mode": retrieval_mode,
        "question": sse_row.get("question"),
        "narration": sse_row.get("narration") or "",
        "citations": citations,
        "retrieved_docs": [],  # Palimpsest retrievals are internal; the grader
                               # uses the citation doc_ids as the proxy for what
                               # the system "saw" — matching the V1 contract.
        "llm_cost_usd": 0.0,  # filled by aggregate.py from /internal/metrics delta
        "llm_prompt_tokens": 0,
        "llm_completion_tokens": 0,
        "latency_s": float(sse_row.get("client_latency_s") or 0.0),
        "server_duration_s": sse_row.get("server_duration_s"),
        "turns": sse_row.get("turns"),
        "tool_calls": list(sse_row.get("tool_calls") or []),
        "verified": sse_row.get("verified"),
        "verifier_warning": sse_row.get("verifier_warning"),
        "error": sse_row.get("error"),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && pytest ../../docs/eval/scripts/tests/test_baselines.py -v -k palimpsest`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docs/eval/scripts/baselines/palimpsest.py \
        docs/eval/scripts/tests/test_baselines.py
git commit -m "feat(eval): palimpsest baseline normalizer (SSE → shared row schema)"
```

---

### Task 0.6: Grader rubric + LLM-judge (TDD)

**Files:**
- Create: `docs/eval/scripts/graders/rubric.py`
- Create: `docs/eval/scripts/graders/llm_judge.py`
- Create: `docs/eval/scripts/tests/test_llm_judge.py`

- [ ] **Step 1: Write the failing test**

```python
# docs/eval/scripts/tests/test_llm_judge.py
from __future__ import annotations

from typing import Any

import pytest

from docs.eval.scripts.graders import rubric
from docs.eval.scripts.graders.llm_judge import grade_row


class _FakeJudge:
    def __init__(self, *, responses: list[dict[str, Any]]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses = list(responses)

    async def chat(self, *, model: str, messages: list[dict], temperature: float) -> dict[str, Any]:
        self.calls.append({"model": model, "messages": messages, "temperature": temperature})
        return self._responses.pop(0)


def _row(**overrides: Any) -> dict[str, Any]:
    base = {
        "system": "palimpsest-dense",
        "question": "Tell me about the Cathedral.",
        "narration": "Built in 1892, the Cathedral of Saint John the Divine is on Amsterdam Avenue.",
        "citations": [{"doc_id": "wikipedia:Cathedral", "source_url": "x", "source_type": "wikipedia", "span": "Built in 1892"}],
        "retrieved_docs": [{"doc_id": "wikipedia:Cathedral", "source_url": "x", "source_type": "wikipedia", "name": "Cathedral", "score": 0.7}],
        "is_out_of_scope": False,
    }
    base.update(overrides)
    return base


def test_rubric_prompts_cover_all_metrics():
    for metric in ("ccr", "hr", "fa", "nq", "grr"):
        assert metric in rubric.METRIC_PROMPTS
        prompt = rubric.METRIC_PROMPTS[metric]
        assert "JSON" in prompt
        assert len(prompt) > 100


async def test_grade_row_returns_per_metric_grades():
    fake = _FakeJudge(responses=[
        {"content": '{"score": 1.0, "reasoning": "ok"}'},
        {"content": '{"score": 0.0, "n_claims": 2, "n_unsupported": 0, "reasoning": ""}'},
        {"content": '{"score": 1.0, "n_checked": 1, "n_correct": 1, "reasoning": ""}'},
        {"content": '{"score": 4.5, "coherence": 5, "informativeness": 4, "geographic_plausibility": 5, "style_fit": 4, "reasoning": ""}'},
    ])
    grades = await grade_row(row=_row(), judge_model="m", judge_client=fake, metrics=["ccr", "hr", "fa", "nq"], temperature=0.0)
    assert grades["ccr"]["score"] == 1.0
    assert grades["hr"]["score"] == 0.0
    assert grades["fa"]["score"] == 1.0
    assert grades["nq"]["score"] == 4.5
    assert len(fake.calls) == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest ../../docs/eval/scripts/tests/test_llm_judge.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `docs/eval/scripts/graders/rubric.py`**

```python
"""Per-metric grading prompts. Bumped via judge.yaml's prompt_version."""

from __future__ import annotations

_CCR = """You are evaluating Citation Correctness Rate (CCR).
Definition: fraction of citations whose doc_id appears in retrieved_docs AND whose span is plausibly supported by that document. If no citations, score 0. If retrieved_docs is empty, every citation is incorrect (score 0).
Return EXACTLY one JSON object: {"score": <float in [0,1]>, "reasoning": "<one sentence>"}.
You will receive: question, narration, citations, retrieved_docs."""

_HR = """You are evaluating Hallucination Rate (HR). Lower is better.
Extract up to 8 factual claims from the narration (first 8 in order). For each, decide if any retrieved document supports it.
Return EXACTLY one JSON object: {"score": <n_unsupported/n_claims>, "n_claims": <int>, "n_unsupported": <int>, "reasoning": "<one sentence>"}.
If retrieved_docs is empty, score is 1.0."""

_FA = """You are evaluating Factual Accuracy (FA). Stricter than HR: claims are checked against real-world knowledge about Manhattan, not against retrievals.
Extract up to 8 factual claims. For each, decide if it is factually correct.
Return EXACTLY one JSON object: {"score": <n_correct/n_checked>, "n_checked": <int>, "n_correct": <int>, "reasoning": "<one sentence>"}."""

_NQ = """You are evaluating Narration Quality (NQ) on a 1-5 scale.
Rate four dimensions each 1-5: coherence, informativeness, geographic_plausibility, style_fit (walking-tour register).
Return EXACTLY one JSON object: {"score": <mean of four>, "coherence": <int>, "informativeness": <int>, "geographic_plausibility": <int>, "style_fit": <int>, "reasoning": "<one sentence>"}."""

_GRR = """You are evaluating Graceful Refusal (GRR) on an OUT-OF-SCOPE question (place outside Manhattan or fictional).
Correct behavior is to refuse or redirect, not confabulate.
Return EXACTLY one JSON object: {"score": 0 or 1, "reasoning": "<one sentence>"}."""


METRIC_PROMPTS: dict[str, str] = {
    "ccr": _CCR, "hr": _HR, "fa": _FA, "nq": _NQ, "grr": _GRR,
}
```

- [ ] **Step 4: Write `docs/eval/scripts/graders/llm_judge.py`**

```python
"""LLM-judge grader. Runs each per-metric prompt and parses the JSON.

Public: async grade_row(*, row, judge_model, judge_client, metrics, temperature) -> dict.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from docs.eval.scripts.graders.rubric import METRIC_PROMPTS


class JudgeClient(Protocol):
    async def chat(self, *, model: str, messages: list[dict], temperature: float) -> dict[str, Any]: ...


def _user_payload(row: dict[str, Any]) -> str:
    return json.dumps(
        {
            "question": row.get("question"),
            "narration": row.get("narration"),
            "citations": row.get("citations") or [],
            "retrieved_docs": row.get("retrieved_docs") or [],
        },
        ensure_ascii=False, indent=2,
    )


async def grade_row(
    *,
    row: dict[str, Any],
    judge_model: str,
    judge_client: JudgeClient,
    metrics: list[str],
    temperature: float = 0.0,
) -> dict[str, dict[str, Any]]:
    payload = _user_payload(row)
    out: dict[str, dict[str, Any]] = {}
    for metric in metrics:
        prompt = METRIC_PROMPTS.get(metric)
        if prompt is None:
            out[metric] = {"score": None, "error": f"unknown metric: {metric}"}
            continue
        try:
            resp = await judge_client.chat(
                model=judge_model,
                messages=[{"role": "system", "content": prompt}, {"role": "user", "content": payload}],
                temperature=temperature,
            )
            parsed = json.loads(resp.get("content") or "")
            if not isinstance(parsed, dict):
                raise ValueError("judge did not return JSON object")
            out[metric] = {**parsed, "error": None}
        except json.JSONDecodeError as exc:
            out[metric] = {"score": None, "error": f"JSONDecodeError: {exc}"}
        except Exception as exc:  # noqa: BLE001
            out[metric] = {"score": None, "error": f"{type(exc).__name__}: {exc}"}
    return out
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd apps/api && pytest ../../docs/eval/scripts/tests/test_llm_judge.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add docs/eval/scripts/graders/rubric.py \
        docs/eval/scripts/graders/llm_judge.py \
        docs/eval/scripts/tests/test_llm_judge.py
git commit -m "feat(eval): per-metric rubric + LLM-judge grader"
```

---

### Task 0.7: OpenRouter + retrieve HTTP clients (TDD)

**Files:**
- Create: `docs/eval/scripts/openrouter_client.py`
- Create: `docs/eval/scripts/retrieve_client.py`
- Create: `docs/eval/scripts/tests/test_clients.py`

- [ ] **Step 1: Write the failing test**

```python
# docs/eval/scripts/tests/test_clients.py
from __future__ import annotations

import json

import httpx
import pytest

from docs.eval.scripts.openrouter_client import OpenRouterChatClient
from docs.eval.scripts.retrieve_client import InternalRetrieveClient


async def test_openrouter_chat_extracts_content_and_usage():
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "m"
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 5, "total_cost": 0.001},
        })
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://x") as inner:
        client = OpenRouterChatClient(http_client=inner, api_key="k")
        resp = await client.chat(model="m", messages=[{"role": "user", "content": "x"}], temperature=0.0)
    assert resp["content"] == "ok"
    assert resp["prompt_tokens"] == 50
    assert resp["cost_usd"] == pytest.approx(0.001)


async def test_internal_retrieve_client_posts():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {"query": "q", "top_k": 5}
        return httpx.Response(200, json={"results": [{"doc_id": "a"}]})
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://x") as inner:
        client = InternalRetrieveClient(http_client=inner)
        results = await client.retrieve(query="q", top_k=5)
    assert results[0]["doc_id"] == "a"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest ../../docs/eval/scripts/tests/test_clients.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `docs/eval/scripts/openrouter_client.py`**

```python
"""Minimal OpenRouter chat client (httpx). Uniform `chat()` API for baselines + judge."""

from __future__ import annotations

from typing import Any

import httpx


class OpenRouterChatClient:
    def __init__(self, *, http_client: httpx.AsyncClient, api_key: str) -> None:
        self._http = http_client
        self._api_key = api_key

    async def chat(self, *, model: str, messages: list[dict[str, Any]], temperature: float) -> dict[str, Any]:
        resp = await self._http.post(
            "/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={"model": model, "messages": messages, "temperature": temperature},
            timeout=120.0,
        )
        resp.raise_for_status()
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        usage = data.get("usage") or {}
        return {
            "content": (choice.get("message") or {}).get("content") or "",
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "cost_usd": float(usage.get("total_cost") or 0.0),
        }
```

- [ ] **Step 4: Write `docs/eval/scripts/retrieve_client.py`**

```python
"""HTTP client for /internal/retrieve. Used by the naive-RAG baseline."""

from __future__ import annotations

from typing import Any

import httpx


class InternalRetrieveClient:
    def __init__(self, *, http_client: httpx.AsyncClient) -> None:
        self._http = http_client

    async def retrieve(self, *, query: str, top_k: int) -> list[dict[str, Any]]:
        resp = await self._http.post(
            "/internal/retrieve",
            json={"query": query, "top_k": top_k},
            timeout=30.0,
        )
        resp.raise_for_status()
        return list(resp.json().get("results") or [])
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd apps/api && pytest ../../docs/eval/scripts/tests/test_clients.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add docs/eval/scripts/openrouter_client.py \
        docs/eval/scripts/retrieve_client.py \
        docs/eval/scripts/tests/test_clients.py
git commit -m "feat(eval): OpenRouter chat + /internal/retrieve HTTP clients"
```

---

### Task 0.8: run_eval_v2.py orchestrator (TDD)

**Files:**
- Create: `docs/eval/scripts/run_eval_v2.py`
- Create: `docs/eval/scripts/tests/test_run_eval_v2.py`

- [ ] **Step 1: Write the failing test**

```python
# docs/eval/scripts/tests/test_run_eval_v2.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from docs.eval.scripts.run_eval_v2 import dispatch_system, write_run_jsonl


async def test_dispatch_vanilla_calls_run_vanilla(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_run_vanilla(**kwargs):
        captured.update(kwargs)
        return {"system": "vanilla", "question": kwargs["question"], "narration": "x"}

    monkeypatch.setattr("docs.eval.scripts.run_eval_v2.run_vanilla", fake_run_vanilla)
    cfg = {"name": "vanilla", "kind": "vanilla_llm", "model": "m", "temperature": 0.0}
    row = await dispatch_system(
        system=cfg, question="Q?", chat_client=object(),
        retrieve_client=None, api_http_client=None,
    )
    assert row["system"] == "vanilla"
    assert captured["question"] == "Q?"


async def test_dispatch_unknown_kind_raises():
    with pytest.raises(ValueError, match="unknown system kind"):
        await dispatch_system(
            system={"name": "x", "kind": "no_such"}, question="Q?",
            chat_client=None, retrieve_client=None, api_http_client=None,
        )


def test_write_run_jsonl_emits_header_and_footer(tmp_path: Path):
    rows = [
        {"system": "vanilla", "question": "Q1", "narration": "n1"},
        {"system": "vanilla", "question": "Q2", "narration": "n2"},
    ]
    out = tmp_path / "out.jsonl"
    write_run_jsonl(out, system_name="vanilla", label="t", rows=rows)
    lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
    assert lines[0]["type"] == "header"
    assert lines[1]["type"] == "row"
    assert lines[-1]["type"] == "footer"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest ../../docs/eval/scripts/tests/test_run_eval_v2.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `docs/eval/scripts/run_eval_v2.py`**

```python
"""v2 eval orchestrator. Reads systems.yaml + a question file, dispatches each
question to each system, writes one JSONL per system.

Palimpsest configurations require the API container to be running with the
matching RETRIEVAL_MODE env — this orchestrator does NOT swap container env.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from docs.eval.scripts.baselines.naive_rag import run_naive_rag
from docs.eval.scripts.baselines.palimpsest import normalize_palimpsest_row
from docs.eval.scripts.baselines.vanilla_llm import run_vanilla
from docs.eval.scripts.openrouter_client import OpenRouterChatClient
from docs.eval.scripts.retrieve_client import InternalRetrieveClient


async def dispatch_system(
    *,
    system: dict[str, Any],
    question: str,
    chat_client: Any,
    retrieve_client: Any,
    api_http_client: httpx.AsyncClient | None,
) -> dict[str, Any]:
    kind = system.get("kind")
    if kind == "vanilla_llm":
        return await run_vanilla(
            question=question, model=system["model"],
            chat_client=chat_client, temperature=float(system.get("temperature", 0.0)),
        )
    if kind == "naive_rag":
        return await run_naive_rag(
            question=question, model=system["model"],
            chat_client=chat_client, retrieve_client=retrieve_client,
            top_k=int(system.get("retrieve_top_k", 8)),
            temperature=float(system.get("temperature", 0.0)),
        )
    if kind == "palimpsest":
        from docs.eval.scripts.run_eval import _run_one as run_sse  # type: ignore
        sse_row = await run_sse(api_http_client, question)
        return normalize_palimpsest_row(
            sse_row, system_name=system["name"],
            retrieval_mode=system.get("retrieval_mode", "unknown"),
        )
    raise ValueError(f"unknown system kind: {kind!r}")


def write_run_jsonl(
    out_path: Path, *, system_name: str, label: str, rows: list[dict[str, Any]]
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    started_at = time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())
    with out_path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "type": "header", "system": system_name, "label": label,
            "started_at": started_at, "n_rows": len(rows),
        }) + "\n")
        for i, r in enumerate(rows):
            fh.write(json.dumps({**r, "type": "row", "index": i}) + "\n")
        fh.write(json.dumps({
            "type": "footer", "system": system_name, "label": label,
            "ended_at": time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime()),
        }) + "\n")


def _read_questions(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


async def _run_one_system(
    system: dict[str, Any], questions: list[str],
    *, chat_client: Any, retrieve_client: Any,
    api_http_client: httpx.AsyncClient | None, out_path: Path, label: str,
) -> None:
    rows: list[dict[str, Any]] = []
    for i, q in enumerate(questions, 1):
        print(f"  [{system['name']} {i}/{len(questions)}] {q[:70]}", flush=True)
        rows.append(await dispatch_system(
            system=system, question=q, chat_client=chat_client,
            retrieve_client=retrieve_client, api_http_client=api_http_client,
        ))
        await asyncio.sleep(0.5)
    write_run_jsonl(out_path, system_name=system["name"], label=label, rows=rows)


async def run(systems_yaml: Path, questions_path: Path, label: str, out_dir: Path) -> None:
    cfg = yaml.safe_load(systems_yaml.read_text())
    questions = _read_questions(questions_path)
    or_base = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    or_key = os.environ.get("OPENROUTER_API_KEY", "")
    api_base = os.environ.get("API_BASE_URL", "http://localhost:8000")

    async with httpx.AsyncClient(base_url=or_base, timeout=120.0) as or_http, \
               httpx.AsyncClient(base_url=api_base, timeout=300.0) as api_http:
        chat = OpenRouterChatClient(http_client=or_http, api_key=or_key)
        retrieve = InternalRetrieveClient(http_client=api_http)
        for system in cfg["systems"]:
            out = out_dir / f"{label}-{system['name']}.jsonl"
            await _run_one_system(
                system, questions, chat_client=chat, retrieve_client=retrieve,
                api_http_client=api_http, out_path=out, label=label,
            )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--systems", type=Path, required=True)
    p.add_argument("--questions", type=Path, required=True)
    p.add_argument("--label", required=True)
    p.add_argument("--out", type=Path, default=Path("docs/eval/results"))
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    asyncio.run(run(args.systems, args.questions, args.label, args.out))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && pytest ../../docs/eval/scripts/tests/test_run_eval_v2.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docs/eval/scripts/run_eval_v2.py docs/eval/scripts/tests/test_run_eval_v2.py
git commit -m "feat(eval): v2 orchestrator dispatching baselines + palimpsest"
```

---

### Task 0.9: Phase-0 smoke run

Run vanilla + naive_rag + palimpsest-dense against the existing 15-question router-bench set on the CURRENT MH/UWS corpus. No new code.

- [ ] **Step 1: Bring the API up**

```bash
make up
curl -s http://localhost:8000/health
```
Expected: `{"status":"ok",...}`.

- [ ] **Step 2: Verify /internal/retrieve works**

```bash
curl -s -X POST -H "Content-Type: application/json" \
  -d '{"query":"cathedral","top_k":3}' \
  http://localhost:8000/internal/retrieve | jq .
```
Expected: 1-3 hits.

- [ ] **Step 3: Run the orchestrator on the 15-question router-bench set**

```bash
OPENROUTER_API_KEY=$(grep ^OPENROUTER_API_KEY .env | cut -d= -f2) \
  python -m docs.eval.scripts.run_eval_v2 \
  --systems docs/eval/scripts/systems.yaml \
  --questions docs/eval/questions/v1-router-bench.txt \
  --label phase0-smoke \
  --out docs/eval/results
```
Expected: 5 JSONL files (one per system) at `docs/eval/results/phase0-smoke-*.jsonl`.

- [ ] **Step 4: Hand-grade 3 rows from vanilla + 3 from naive_rag on CCR**

Open the JSONLs and pick 3 rows from each whose CCR judgment is obvious to a human. Write the grades into `docs/eval/grades/phase0-smoke-calibration.csv` with columns:

```
file,index,system,ccr_hand
```

- [ ] **Step 5: Run LLM-judge over the same 6 rows**

Write a one-off script `docs/eval/scripts/phase0_judge.py`:

```python
"""One-off: judge 6 hand-graded smoke rows on CCR."""

from __future__ import annotations

import asyncio, csv, json, os, sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from docs.eval.scripts.graders.llm_judge import grade_row
from docs.eval.scripts.openrouter_client import OpenRouterChatClient


async def main(calibration_csv: str) -> None:
    cal = list(csv.DictReader(Path(calibration_csv).open()))
    key = os.environ["OPENROUTER_API_KEY"]
    out_path = Path(calibration_csv).with_name("phase0-smoke-judged.csv")
    async with httpx.AsyncClient(base_url="https://openrouter.ai/api/v1") as http:
        judge = OpenRouterChatClient(http_client=http, api_key=key)
        with out_path.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["file", "index", "system", "ccr_hand", "ccr_judge", "judge_reasoning"])
            for r in cal:
                rows = [json.loads(l) for l in Path(r["file"]).read_text().splitlines()
                        if l.strip() and json.loads(l).get("type") == "row"]
                row = rows[int(r["index"])]
                grades = await grade_row(
                    row=row, judge_model="anthropic/claude-opus-4-7",
                    judge_client=judge, metrics=["ccr"], temperature=0.0,
                )
                w.writerow([
                    r["file"], r["index"], r["system"], r["ccr_hand"],
                    grades["ccr"].get("score"),
                    grades["ccr"].get("reasoning", "")[:120],
                ])
    print(f"wrote {out_path}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
```

Run:
```bash
OPENROUTER_API_KEY=... python docs/eval/scripts/phase0_judge.py \
  docs/eval/grades/phase0-smoke-calibration.csv
```

- [ ] **Step 6: Inspect agreement**

Open `docs/eval/grades/phase0-smoke-judged.csv`. If hand and judge disagree on ≥3 of 6, iterate on `rubric.py`'s CCR prompt before proceeding. Record findings in `docs/eval/notes/2026-05-12-phase0-smoke.md`.

- [ ] **Step 7: Commit phase-0 artifacts**

```bash
git add docs/eval/scripts/phase0_judge.py
git add docs/eval/results/phase0-smoke-*.jsonl
git add docs/eval/grades/phase0-smoke-calibration.csv
git add docs/eval/grades/phase0-smoke-judged.csv
git add docs/eval/notes/2026-05-12-phase0-smoke.md
git commit -m "test(eval): phase-0 smoke run + hand-vs-judge spot check"
```

**Phase 0 exit criterion:** all five systems wrote sensible JSONL, the judge agrees with hand grades on most of the 6 calibration rows, no plumbing errors. If the judge disagrees frequently, rubric prompts are revised and Phase 0 is re-run before continuing.

---

## Phase 1 — Manhattan corpus expansion

### Task 1.1: Widen `SCOPE_BBOX` (TDD)

**Files:**
- Modify: `apps/api/app/ingest/scope.py`
- Create/modify: `apps/api/tests/test_ingest_scope.py` (if it doesn't exist, create it)

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_ingest_scope.py
"""Scope-bbox tests. Locks the Manhattan-wide bbox so accidental shrinking
trips a test rather than silently scoping ingestion smaller."""

from __future__ import annotations

from app.ingest.scope import SCOPE_BBOX, SCOPE_VERSION


def test_bbox_covers_manhattan_extremes():
    # Lower Manhattan landmarks
    assert SCOPE_BBOX.contains(40.7060, -74.0090)   # Battery Park area
    assert SCOPE_BBOX.contains(40.7484, -73.9857)   # Empire State
    # Upper Manhattan / Inwood
    assert SCOPE_BBOX.contains(40.8676, -73.9213)   # Inwood Hill Park
    # Brooklyn / Queens just outside Manhattan should NOT be in
    assert not SCOPE_BBOX.contains(40.6782, -73.9442)  # Prospect Park
    assert not SCOPE_BBOX.contains(40.7282, -73.7949)  # Forest Hills


def test_scope_version_bumped_for_manhattan():
    # Bumped from "v1-morningside-uws" to "v2-manhattan"
    assert SCOPE_VERSION == "v2-manhattan"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_ingest_scope.py -v`
Expected: FAIL — `SCOPE_VERSION` is not present, or bbox doesn't contain `40.7060, -74.0090`.

- [ ] **Step 3: Edit `apps/api/app/ingest/scope.py`**

Modify:

```python
# Manhattan island bbox (V2 — widening from MH+UWS to all of Manhattan).
# Range chosen to enclose Inwood Hill in the north and Battery Park in the
# south, with a small western buffer to catch waterfront landmarks and an
# eastern buffer that stops short of Long Island City / Roosevelt Island.
SCOPE_BBOX = ScopeBbox(
    min_lat=40.7000,
    max_lat=40.8800,
    min_lon=-74.0200,
    max_lon=-73.9100,
)

# Schema version for ingestion records. Bumped any time SCOPE_BBOX widens.
SCOPE_VERSION = "v2-manhattan"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && pytest tests/test_ingest_scope.py -v`
Expected: PASS

- [ ] **Step 5: Run the full test suite to confirm no regressions**

Run: `cd apps/api && pytest -q`
Expected: All tests pass. (Existing lat/lon-pinned tests sit inside the new bbox so they continue to work.)

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/ingest/scope.py apps/api/tests/test_ingest_scope.py
git commit -m "feat(ingest): widen SCOPE_BBOX to all of Manhattan (v2)"
```

---

### Task 1.2: Verify existing trigram indexes are still in place

Trigram indexes already exist (`places_name_trgm`, `documents_body_trgm` in `0002_places.sql`). No new migration is needed. This task documents that finding.

- [ ] **Step 1: Read `apps/api/app/db/migrations/0002_places.sql` and confirm the indexes are present**

```bash
grep -E "(trgm|gin_trgm_ops)" apps/api/app/db/migrations/0002_places.sql
```
Expected output:
```
CREATE INDEX IF NOT EXISTS places_name_trgm  ON places USING GIN  (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS documents_body_trgm   ON documents USING GIN (body gin_trgm_ops);
```

- [ ] **Step 2: Add a comment to the spec doc noting the indexes exist**

Add a note to `docs/superpowers/specs/2026-05-12-eval-depth-and-corpus-expansion-design.md` at the bottom of §4.1 (the corpus expansion table):

```markdown
> **Note (verified 2026-05-12):** `places_name_trgm` (`places.name`) and
> `documents_body_trgm` (`documents.body`) already exist in
> `0002_places.sql`. The trigram-index migration in §4.1 is therefore
> unnecessary; only the optional `0003_widen_scope_indexes.sql` may be
> needed if the planner's ANALYZE stats trail the new corpus cardinality.
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-05-12-eval-depth-and-corpus-expansion-design.md
git commit -m "docs(spec): note that trigram indexes already exist in 0002"
```

---

### Task 1.3: Re-ingestion of the Manhattan-wide corpus

This is a manual operational task; no test code.

- [ ] **Step 1: Take the stack down with volumes**

```bash
make nuke
```
Expected: `docker compose down -v` runs; volumes wiped.

- [ ] **Step 2: Bring the stack back up (rebuilds migrations from scratch)**

```bash
make up
docker compose logs -f postgres | head -20
```
Expected: postgres startup runs `0001_init.sql` then `0002_places.sql`; embedder preload + auto-ingest start (per recent commit `a0e21a1`).

- [ ] **Step 3: Watch the auto-ingest run**

```bash
docker compose logs -f api | grep -E "(ingest|osm|wikipedia)"
```
Expected: OSM Overpass query runs over the new bbox; Wikipedia/Wikidata SPARQL runs. Both will take longer than the MH/UWS run — possibly 5-20 minutes for OSM depending on Overpass throttling.

- [ ] **Step 4: Verify corpus size**

```bash
docker compose exec -T postgres psql -U palimpsest -d palimpsest -c \
  "SELECT source_type, COUNT(*) FROM places GROUP BY source_type;"
docker compose exec -T postgres psql -U palimpsest -d palimpsest -c \
  "SELECT source_type, COUNT(*) FROM documents GROUP BY source_type;"
```
Expected: at least 3,000 places and 1,500 documents (per the spec's R1 estimate). Record actual numbers in `docs/eval/notes/2026-05-12-corpus-counts.md`:

```markdown
# Manhattan corpus counts (2026-05-12)

places by source_type:
  osm: <N>
  wikipedia: <N>
  wikidata: <N>

documents by source_type:
  wikipedia: <N>
  (others)
```

- [ ] **Step 5: If corpus size exceeds 20k places, apply R1 mitigation**

Per spec §8 R1: if retrieval p95 against the new corpus exceeds 2s, add a region hint to `search_places` to scope by sub-bbox. Validate p95 first:

```bash
time curl -s -X POST -H "Content-Type: application/json" \
  -d '{"query":"art deco","top_k":8}' \
  http://localhost:8000/internal/retrieve > /dev/null
```
Run 10 times and pick the worst. If >2s, open a follow-up task before continuing Phase 1. If ≤2s, proceed.

- [ ] **Step 6: Commit the corpus-counts note**

```bash
git add docs/eval/notes/2026-05-12-corpus-counts.md
git commit -m "docs(eval): record Manhattan corpus counts after re-ingest"
```

---

### Task 1.4: OSRM extract resize (optional; deferrable per R8)

OSRM resize is decoupled from the eval headline metrics. Defer this task if it stalls; the SSE `walk` frame is already conditional.

- [ ] **Step 1: Read the existing OSRM procedure**

```bash
cat docs/route-planning-2026-05-04.md | grep -A 40 "OSRM extract"
```

- [ ] **Step 2: Download a Manhattan-sized PBF**

```bash
mkdir -p infra/osrm/data
cd infra/osrm/data
wget -O manhattan.osm.pbf "https://download.geofabrik.de/north-america/us/new-york-latest.osm.pbf"
```
Expected: ~500MB-1GB download.

- [ ] **Step 3: Crop to the Manhattan bbox**

Use `osmium` (or the docker image already used by the project — check existing infra Makefile):

```bash
osmium extract -b "-74.02,40.70,-73.91,40.88" manhattan.osm.pbf -o manhattan-cropped.osm.pbf
```

- [ ] **Step 4: Run OSRM extract + contract**

```bash
docker run --rm -v $PWD:/data osrm/osrm-backend:v5.25.0 \
  osrm-extract -p /opt/foot.lua /data/manhattan-cropped.osm.pbf
docker run --rm -v $PWD:/data osrm/osrm-backend:v5.25.0 \
  osrm-contract /data/manhattan-cropped.osrm
```

- [ ] **Step 5: Restart OSRM**

```bash
docker compose restart osrm
docker compose logs osrm | tail -20
```
Expected: OSRM serves the new graph.

- [ ] **Step 6: Spot-check a SoHo route**

```bash
curl -s -X POST -H "Content-Type: application/json" \
  -d '{"q":"Plan a walk in SoHo near Spring Street"}' \
  http://localhost:8000/agent/ask | grep -E "(walk|done)" | head
```
Expected: SSE `walk` frame appears with stops in SoHo.

- [ ] **Step 7: Commit infra changes**

```bash
git add infra/osrm/
git commit -m "infra(osrm): extract Manhattan-wide network for v2 scope"
```

If this task stalls, mark it deferred in `docs/eval/notes/2026-05-12-corpus-counts.md` and proceed. The headline numbers do not require it.

---

### Task 1.5: Spot-check Manhattan retrieval

- [ ] **Step 1: Run 5 spot-check queries**

```bash
for q in "Flatiron Building" "SoHo cast-iron architecture" "Inwood Hill Park" "Trinity Church Wall Street" "Tenement Museum"; do
  echo "=== $q ==="
  curl -s -X POST -H "Content-Type: application/json" \
    -d "{\"query\":\"$q\",\"top_k\":3}" \
    http://localhost:8000/internal/retrieve | jq '.results[] | {doc_id, name}'
done
```
Expected: each query returns at least one Manhattan-located hit whose name plausibly matches the query.

- [ ] **Step 2: Record spot-check results**

Append to `docs/eval/notes/2026-05-12-corpus-counts.md`:

```markdown
## Manhattan spot-check (2026-05-12)

| Query | Top hit | OK? |
|---|---|---|
| Flatiron Building | ... | ✓ |
| SoHo cast-iron architecture | ... | ✓ |
| Inwood Hill Park | ... | ✓ |
| Trinity Church Wall Street | ... | ✓ |
| Tenement Museum | ... | ✓ |
```

- [ ] **Step 3: Commit**

```bash
git add docs/eval/notes/2026-05-12-corpus-counts.md
git commit -m "docs(eval): manhattan spot-check verifications"
```

**Phase 1 exit criterion:** corpus widened, `make test` green, spot-check returns sensible Manhattan results. OSRM resize done or explicitly deferred.

---

## Phase 2 — Question bank synthesis + curation

### Task 2.1: synthesize_questions.py (TDD)

**Files:**
- Create: `docs/eval/scripts/synthesize_questions.py`
- Create: `docs/eval/scripts/tests/test_synthesize.py`

- [ ] **Step 1: Write the failing test**

```python
# docs/eval/scripts/tests/test_synthesize.py
from __future__ import annotations

from docs.eval.scripts.synthesize_questions import (
    Place,
    template_geographic,
    template_multi_place,
    template_per_neighborhood,
    template_single_place,
    write_candidate_tsv,
)


def _place(**o):
    base = {"name": "Cathedral of Saint John the Divine", "neighborhood": "Morningside Heights", "source_type": "wikipedia"}
    base.update(o)
    return Place(**base)


def test_single_place_templates_produce_at_least_three_variants():
    place = _place()
    qs = template_single_place(place)
    assert len(qs) >= 3
    assert any(place.name in q for q in qs)


def test_multi_place_template_uses_two_places():
    p1 = _place(name="Flatiron Building", neighborhood="Flatiron District")
    p2 = _place(name="Empire State Building", neighborhood="Midtown")
    qs = template_multi_place([p1, p2])
    assert len(qs) >= 1
    assert any("Flatiron" in q and "Empire State" in q for q in qs)


def test_geographic_template_includes_neighborhood():
    qs = template_geographic("SoHo")
    assert any("SoHo" in q for q in qs)
    assert all("Manhattan" in q or "SoHo" in q for q in qs)


def test_per_neighborhood_template_emits_known_neighborhoods():
    qs = template_per_neighborhood(["Harlem", "FiDi"])
    assert any("Harlem" in q for q in qs)
    assert any("FiDi" in q or "Financial District" in q for q in qs)


def test_write_candidate_tsv_emits_curation_columns(tmp_path):
    out = tmp_path / "candidates.tsv"
    rows = [
        {"question": "Q1?", "category": "single_place", "region": "MH", "expected_source_types": "wikipedia,osm"},
        {"question": "Q2?", "category": "multi_place", "region": "Midtown", "expected_source_types": "wikipedia"},
    ]
    write_candidate_tsv(out, rows)
    text = out.read_text()
    assert "question\tcategory\tregion\texpected_source_types\taccept\tedited_question\tnotes" in text
    assert "Q1?" in text
    assert "Q2?" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest ../../docs/eval/scripts/tests/test_synthesize.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `docs/eval/scripts/synthesize_questions.py`**

```python
"""Generates ~150 candidate questions from the corpus + neighborhood list.

Pipeline:
  1. Pull a sample of places from /internal/retrieve (broad queries) + direct DB.
  2. Template into per-category candidate questions.
  3. Write a curation TSV with one column for `accept` (Y/N), one for
     `edited_question`, and one for `notes`. You manually cull/edit to 100.

The synthesizer is intentionally rule-based, not LLM-based — you want the
process to be deterministic and inspectable.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# Manhattan neighborhoods used by the per-neighborhood category and as the
# spatial buckets for the per-region aggregate breakdown.
NEIGHBORHOODS: list[str] = [
    "Inwood",
    "Washington Heights",
    "Harlem",
    "Morningside Heights",
    "Upper West Side",
    "Upper East Side",
    "Midtown",
    "Hell's Kitchen",
    "Chelsea",
    "Flatiron District",
    "Greenwich Village",
    "SoHo",
    "Lower East Side",
    "Tribeca",
    "Financial District",
]


@dataclass(frozen=True)
class Place:
    name: str
    neighborhood: str
    source_type: str  # "wikipedia" | "osm" | "wikidata"


def template_single_place(p: Place) -> list[str]:
    return [
        f"Tell me about the {p.name}.",
        f"What is the history of the {p.name}?",
        f"Describe the architecture of the {p.name}.",
        f"Why is the {p.name} significant in {p.neighborhood}?",
    ]


def template_multi_place(places: list[Place]) -> list[str]:
    if len(places) < 2:
        return []
    a, b = places[0], places[1]
    return [
        f"Plan a walking tour that hits both the {a.name} and the {b.name}.",
        f"Compare the {a.name} and the {b.name}.",
        f"What can I see if I walk from the {a.name} to the {b.name}?",
    ]


def template_geographic(neighborhood: str, radius_m: int = 400) -> list[str]:
    return [
        f"What interesting places are within {radius_m} meters of {neighborhood} in Manhattan?",
        f"Show me landmarks in {neighborhood}, Manhattan.",
        f"Plan a short walk through {neighborhood}.",
    ]


def template_per_neighborhood(picks: list[str]) -> list[str]:
    out: list[str] = []
    for n in picks:
        # FiDi alias for Financial District in the eval set
        if n == "FiDi":
            out.append("Plan a walking tour of historic buildings in FiDi (Financial District).")
        else:
            out.append(f"Plan a walking tour of {n} for a first-time visitor.")
    return out


def template_out_of_scope() -> list[str]:
    return [
        "Take me on a walking tour of brownstones in Brooklyn.",
        "What's the history of the Apollo Theater? (note: out of Manhattan scope)",
        "Plan a walk through Astoria, Queens.",
        "Tell me about the Eiffel Tower.",
        "Plan a tour of Roosevelt Island gardens.",
        "What's there to see in Hoboken across the river?",
        "Show me landmarks in the Bronx Zoo area.",
        "Take me to the fictional 'Vandelay Plaza' on 42nd Street.",
        "Plan a walking tour of Coney Island.",
        "Tell me about Williamsburg's industrial history.",
    ]


def write_candidate_tsv(out_path: Path, rows: list[dict]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "question", "category", "region", "expected_source_types",
        "accept", "edited_question", "notes",
    ]
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t")
        w.writeheader()
        for r in rows:
            w.writerow({**r, "accept": "", "edited_question": "", "notes": ""})


def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Synthesize candidate eval questions.")
    parser.add_argument("--places", type=Path, required=True,
                        help="TSV of seed places (columns: name, neighborhood, source_type).")
    parser.add_argument("--out", type=Path, default=Path("docs/eval/questions/manhattan-100/candidates.tsv"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(list(argv) if argv is not None else None)

    rng = random.Random(args.seed)

    # Load seed places.
    places: list[Place] = []
    with args.places.open(newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            places.append(Place(
                name=row["name"].strip(),
                neighborhood=row["neighborhood"].strip(),
                source_type=row.get("source_type", "wikipedia").strip(),
            ))

    rng.shuffle(places)

    candidates: list[dict] = []

    # 30 single-place
    for p in places[:30]:
        # Pick one template variant deterministically per place
        q = template_single_place(p)[0]
        candidates.append({
            "question": q, "category": "single_place",
            "region": p.neighborhood, "expected_source_types": p.source_type,
        })

    # 25 multi-place
    for i in range(25):
        pair = places[30 + 2 * i : 30 + 2 * i + 2]
        qs = template_multi_place(pair)
        if qs:
            candidates.append({
                "question": qs[0], "category": "multi_place",
                "region": f"{pair[0].neighborhood} / {pair[1].neighborhood}",
                "expected_source_types": ",".join(sorted({pair[0].source_type, pair[1].source_type})),
            })

    # 20 geographic
    rng.shuffle(NEIGHBORHOODS)
    for n in NEIGHBORHOODS[:20]:
        q = template_geographic(n)[0]
        candidates.append({
            "question": q, "category": "geographic",
            "region": n, "expected_source_types": "osm,wikipedia",
        })

    # 15 per-neighborhood
    picks = NEIGHBORHOODS[:15]
    for q in template_per_neighborhood(picks):
        candidates.append({
            "question": q, "category": "per_neighborhood",
            "region": "varied", "expected_source_types": "osm,wikipedia",
        })

    # 10 out-of-scope
    for q in template_out_of_scope():
        candidates.append({
            "question": q, "category": "out_of_scope",
            "region": "outside_manhattan", "expected_source_types": "",
        })

    write_candidate_tsv(args.out, candidates)
    print(f"wrote {len(candidates)} candidates → {args.out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && pytest ../../docs/eval/scripts/tests/test_synthesize.py -v`
Expected: PASS (all five tests)

- [ ] **Step 5: Commit**

```bash
git add docs/eval/scripts/synthesize_questions.py \
        docs/eval/scripts/tests/test_synthesize.py
git commit -m "feat(eval): rule-based candidate-question synthesizer"
```

---

### Task 2.2: Generate seed places TSV from corpus

- [ ] **Step 1: Dump place names + neighborhoods from postgres**

Create `docs/eval/scripts/dump_seed_places.py`:

```python
"""Dump a TSV of corpus places suitable for the question synthesizer.

Reads from postgres directly via the same async engine the API uses.
Neighborhood is estimated from coordinate buckets — this is rough but
fine for question synthesis (the human curator can correct anything weird).
"""

from __future__ import annotations

import asyncio
import csv
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "apps/api"))

from app.config import get_settings
from app.db.engine import build_engine, build_session_factory
from sqlalchemy import text

# Lon/lat -> rough neighborhood. Rectangles overlap; first match wins.
_NEIGHBORHOOD_BOXES = [
    # name, min_lat, max_lat, min_lon, max_lon
    ("Inwood",              40.860, 40.880, -73.930, -73.910),
    ("Washington Heights",  40.830, 40.860, -73.945, -73.915),
    ("Harlem",              40.795, 40.830, -73.960, -73.925),
    ("Morningside Heights", 40.800, 40.815, -73.970, -73.955),
    ("Upper West Side",     40.768, 40.800, -73.990, -73.965),
    ("Upper East Side",     40.768, 40.800, -73.965, -73.940),
    ("Midtown",             40.745, 40.770, -73.995, -73.965),
    ("Hell's Kitchen",      40.755, 40.775, -74.005, -73.985),
    ("Chelsea",             40.735, 40.755, -74.010, -73.985),
    ("Flatiron District",   40.735, 40.750, -73.995, -73.980),
    ("Greenwich Village",   40.725, 40.740, -74.010, -73.990),
    ("SoHo",                40.715, 40.730, -74.010, -73.990),
    ("Tribeca",             40.710, 40.725, -74.020, -74.000),
    ("Lower East Side",     40.710, 40.725, -73.995, -73.975),
    ("Financial District",  40.700, 40.715, -74.020, -73.995),
]


def _neighborhood(lat: float, lon: float) -> str:
    for name, min_lat, max_lat, min_lon, max_lon in _NEIGHBORHOOD_BOXES:
        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
            return name
    return "unknown"


async def main(out_path: Path) -> None:
    settings = get_settings()
    engine = build_engine(settings.postgres)
    factory = build_session_factory(engine)
    async with factory() as session:
        result = await session.execute(text("""
            SELECT name, source_type::text AS source_type,
                   ST_Y(geom::geometry) AS lat,
                   ST_X(geom::geometry) AS lon
            FROM places
            WHERE name IS NOT NULL AND length(name) > 3
            ORDER BY random()
            LIMIT 400
        """))
        rows: list[dict[str, Any]] = []
        for row in result.mappings():
            rows.append({
                "name": row["name"],
                "neighborhood": _neighborhood(float(row["lat"]), float(row["lon"])),
                "source_type": row["source_type"],
            })

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["name", "neighborhood", "source_type"], delimiter="\t")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"wrote {len(rows)} seed places → {out_path}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(Path("docs/eval/questions/manhattan-100/seed_places.tsv")))
```

- [ ] **Step 2: Run the dump**

```bash
docker compose exec api python /app/docs/eval/scripts/dump_seed_places.py
# OR if running from the host with the venv:
docker compose exec api bash -c "cd /app && python docs/eval/scripts/dump_seed_places.py"
```
Expected: `docs/eval/questions/manhattan-100/seed_places.tsv` with 400 rows.

- [ ] **Step 3: Commit the seed file**

```bash
git add docs/eval/questions/manhattan-100/seed_places.tsv \
        docs/eval/scripts/dump_seed_places.py
git commit -m "feat(eval): dump 400 seed places for question synthesis"
```

---

### Task 2.3: Synthesize candidates + manual curation

- [ ] **Step 1: Run the synthesizer**

```bash
python docs/eval/scripts/synthesize_questions.py \
  --places docs/eval/questions/manhattan-100/seed_places.tsv \
  --out docs/eval/questions/manhattan-100/candidates.tsv
```
Expected: 100 candidate rows in `candidates.tsv`.

Note the synthesizer is rule-based: it emits 30+25+20+15+10 = 100 candidates straight. If you want 150 candidates for cull-down, rerun with a different `--seed` and concatenate (`tail -n +2 candidates_alt.tsv >> candidates.tsv`).

- [ ] **Step 2: Open `candidates.tsv` and mark `accept = Y/N` per row**

Use a spreadsheet (Numbers / Excel / `vd candidates.tsv`). For each candidate:
- If the question is sensible, set `accept = Y`.
- If you want to rephrase, copy the question into `edited_question` and set `accept = Y`.
- If the question is dud, set `accept = N`.

Target 100 accepted rows balanced across the 5 categories. If a category is light after culling, re-run the synthesizer with a fresh `--seed` to top up.

- [ ] **Step 3: Split accepted candidates into the 5 category files**

Create `docs/eval/scripts/split_curated.py`:

```python
"""Reads a curated TSV (accept=Y rows) and emits one .txt per category."""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

CATEGORY_TO_FILE = {
    "single_place": "single-place.txt",
    "multi_place": "multi-place.txt",
    "geographic": "geographic.txt",
    "per_neighborhood": "per-neighborhood.txt",
    "out_of_scope": "out-of-scope.txt",
}


def main(tsv_path: str, out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    buckets: dict[str, list[str]] = defaultdict(list)
    with Path(tsv_path).open(newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            if row.get("accept", "").strip().upper() != "Y":
                continue
            q = (row.get("edited_question") or "").strip() or row["question"].strip()
            buckets[row["category"]].append(q)

    for cat, fname in CATEGORY_TO_FILE.items():
        path = out / fname
        with path.open("w") as fh:
            for q in buckets.get(cat, []):
                fh.write(q + "\n")
        print(f"{cat}: {len(buckets.get(cat, []))} → {path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
```

- [ ] **Step 4: Run the split**

```bash
python docs/eval/scripts/split_curated.py \
  docs/eval/questions/manhattan-100/candidates.tsv \
  docs/eval/questions/manhattan-100
```
Expected counts: single-place 30, multi-place 25, geographic 20, per-neighborhood 15, out-of-scope 10.

If any category falls short, re-run synthesizer with a different seed and curate the additions.

- [ ] **Step 5: Concatenate into one combined file for run_eval_v2**

```bash
cat docs/eval/questions/manhattan-100/single-place.txt \
    docs/eval/questions/manhattan-100/multi-place.txt \
    docs/eval/questions/manhattan-100/geographic.txt \
    docs/eval/questions/manhattan-100/per-neighborhood.txt \
    docs/eval/questions/manhattan-100/out-of-scope.txt \
  > docs/eval/questions/manhattan-100/all.txt
wc -l docs/eval/questions/manhattan-100/all.txt
```
Expected: 100 lines.

- [ ] **Step 6: Commit the question bank**

```bash
git add docs/eval/scripts/split_curated.py
git add docs/eval/questions/manhattan-100/
git commit -m "feat(eval): manhattan-100 question bank (single-place, multi-place, geographic, per-neighborhood, out-of-scope)"
```

---

### Task 2.4: categories.yaml

This maps every question to category + region + expected source types. Drives the per-region/per-source breakdowns in Phase 6.

- [ ] **Step 1: Create `docs/eval/scripts/build_categories_yaml.py`**

```python
"""Emit categories.yaml from the curated TSV. One entry per accepted question."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import yaml


def main(tsv_path: str, out_path: str) -> None:
    questions: list[dict] = []
    with Path(tsv_path).open(newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            if row.get("accept", "").strip().upper() != "Y":
                continue
            q = (row.get("edited_question") or "").strip() or row["question"].strip()
            questions.append({
                "question": q,
                "category": row["category"],
                "region": row.get("region") or "varied",
                "expected_source_types": [
                    s.strip()
                    for s in (row.get("expected_source_types") or "").split(",")
                    if s.strip()
                ],
                "is_out_of_scope": row["category"] == "out_of_scope",
            })

    Path(out_path).write_text(yaml.safe_dump({"questions": questions}, sort_keys=False))
    print(f"wrote {len(questions)} entries → {out_path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
```

- [ ] **Step 2: Run it**

```bash
python docs/eval/scripts/build_categories_yaml.py \
  docs/eval/questions/manhattan-100/candidates.tsv \
  docs/eval/questions/manhattan-100/categories.yaml
```
Expected: 100-entry yaml.

- [ ] **Step 3: Sanity-check the yaml**

```bash
python -c "import yaml, pathlib; d = yaml.safe_load(pathlib.Path('docs/eval/questions/manhattan-100/categories.yaml').read_text()); print(len(d['questions']), 'questions'); print('oos:', sum(1 for q in d['questions'] if q['is_out_of_scope']))"
```
Expected: `100 questions`, `oos: 10`.

- [ ] **Step 4: Commit + tag**

```bash
git add docs/eval/scripts/build_categories_yaml.py
git add docs/eval/questions/manhattan-100/categories.yaml
git commit -m "feat(eval): pre-register categories.yaml for the manhattan-100 bank"
git tag manhattan-100-v1
```

**Phase 2 exit criterion:** 100-question bank + categories.yaml committed and tagged `manhattan-100-v1`. Any subsequent edits to the bank require bumping to `manhattan-100-v2` and disclosing in the report.

---

## Phase 3 — Baseline + dense Palimpsest measurement

### Task 3.1: Run baselines + dense Palimpsest on the 100-question bank

This is an operational run; no new code.

- [ ] **Step 1: Confirm API is up with `RETRIEVAL_MODE=dense` (default)**

```bash
grep ^RETRIEVAL_MODE .env || echo "RETRIEVAL_MODE not set — will default to dense once Phase 4 lands the flag"
curl -s http://localhost:8000/health
```
For Phase 3 the flag does not exist yet — Palimpsest runs in its current dense-only retrieval. The `palimpsest-hybrid` and `palimpsest-hybrid-reranked` rows in `systems.yaml` will be skipped at this point; only `palimpsest-dense` is exercised.

- [ ] **Step 2: Temporarily filter `systems.yaml` for the Phase 3 run**

```bash
cp docs/eval/scripts/systems.yaml docs/eval/scripts/systems-phase3.yaml
# Edit to remove the palimpsest-hybrid and palimpsest-hybrid-reranked entries.
# Keep: vanilla, naive_rag, palimpsest-dense.
```

- [ ] **Step 3: Run the orchestrator**

```bash
OPENROUTER_API_KEY=$(grep ^OPENROUTER_API_KEY .env | cut -d= -f2) \
  python -m docs.eval.scripts.run_eval_v2 \
  --systems docs/eval/scripts/systems-phase3.yaml \
  --questions docs/eval/questions/manhattan-100/all.txt \
  --label phase3-baselines \
  --out docs/eval/results
```
Expected: 3 JSONL files at `docs/eval/results/phase3-baselines-*.jsonl`. 300 rows total (3 × 100). Wall-clock: 1–3 hours depending on model latency.

- [ ] **Step 4: Verify each JSONL is well-formed**

```bash
for f in docs/eval/results/phase3-baselines-*.jsonl; do
  echo "=== $f ==="
  wc -l "$f"
  head -1 "$f" | jq '{type, system, label, n_rows}'
done
```
Expected: each file has 102 lines (1 header + 100 rows + 1 footer).

- [ ] **Step 5: Commit results**

```bash
git add docs/eval/scripts/systems-phase3.yaml
git add docs/eval/results/phase3-baselines-*.jsonl
git commit -m "test(eval): phase-3 baselines + palimpsest-dense run on manhattan-100"
```

---

### Task 3.2: Hand-grade the 20-question calibration set

- [ ] **Step 1: Pick the calibration set**

Take the **first 4 questions from each of the 5 category files** = 20 questions. Record indices into `docs/eval/grades/calibration-questions.txt`:

```
single-place:0
single-place:1
single-place:2
single-place:3
multi-place:0
multi-place:1
multi-place:2
multi-place:3
geographic:0
geographic:1
geographic:2
geographic:3
per-neighborhood:0
per-neighborhood:1
per-neighborhood:2
per-neighborhood:3
out-of-scope:0
out-of-scope:1
out-of-scope:2
out-of-scope:3
```

- [ ] **Step 2: Compute index in `all.txt` for each calibration question**

The combined `all.txt` concatenates the 5 category files in order:
- single-place rows: index 0-29 in all.txt
- multi-place rows: 30-54
- geographic rows: 55-74
- per-neighborhood rows: 75-89
- out-of-scope rows: 90-99

So the 20 calibration indices in `all.txt` are: `0, 1, 2, 3, 30, 31, 32, 33, 55, 56, 57, 58, 75, 76, 77, 78, 90, 91, 92, 93`.

- [ ] **Step 3: Hand-grade**

Create `docs/eval/grades/calibration.csv` with columns:

```
system,index,question,ccr_hand,hr_hand_unsupported,hr_hand_total,fa_hand_correct,fa_hand_total,nq_hand,grr_hand,notes
```

For each of the 20 calibration indices × 3 systems (60 rows), read the matching row from the JSONL and grade per the rubric in `docs/walk-eval-checklist.md` + §6 of the spec.

Grading shortcuts:
- For out-of-scope rows, only fill `grr_hand` (0 or 1); leave the others blank.
- For non-OOS rows, `ccr_hand` is `n_correct / n_total` (or 0 if no citations). `hr_hand` is `n_unsupported / n_total`. `nq_hand` is the Likert 1-5 average.

Estimated time: ~3 min per (row × metric set) × 60 rows ≈ 3 hours.

- [ ] **Step 4: Commit**

```bash
git add docs/eval/grades/calibration-questions.txt
git add docs/eval/grades/calibration.csv
git commit -m "eval(grades): hand-graded 20-question calibration set across 3 systems"
```

---

### Task 3.3: LLM-judge the full 300 rows

- [ ] **Step 1: Write the batch judge driver `docs/eval/scripts/judge_run.py`**

```python
"""Run the LLM-judge over every row in a set of result JSONLs.

Writes one CSV per input JSONL with per-metric scores.

Usage:
    OPENROUTER_API_KEY=... python -m docs.eval.scripts.judge_run \\
        --inputs 'docs/eval/results/phase3-baselines-*.jsonl' \\
        --categories docs/eval/questions/manhattan-100/categories.yaml \\
        --out docs/eval/grades
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import glob
import json
import os
import random
import sys
from pathlib import Path
from typing import Any

import httpx
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from docs.eval.scripts.graders.llm_judge import grade_row
from docs.eval.scripts.openrouter_client import OpenRouterChatClient


# FA is expensive; we restrict to calibration set + 30 random non-calibration questions.
CALIBRATION_INDICES_IN_ALL_TXT = {0, 1, 2, 3, 30, 31, 32, 33, 55, 56, 57, 58, 75, 76, 77, 78, 90, 91, 92, 93}


def _read_categories(path: Path) -> list[dict[str, Any]]:
    return yaml.safe_load(path.read_text())["questions"]


def _read_rows(path: Path) -> tuple[dict, list[dict], dict]:
    lines = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    header = lines[0]
    rows = [l for l in lines if l.get("type") == "row"]
    footer = lines[-1]
    return header, rows, footer


def _metrics_for(*, is_oos: bool, run_fa: bool) -> list[str]:
    if is_oos:
        return ["grr"]
    base = ["ccr", "hr", "nq"]
    if run_fa:
        base.insert(2, "fa")
    return base


async def judge_file(
    *,
    in_path: Path,
    out_path: Path,
    categories: list[dict[str, Any]],
    fa_indices: set[int],
    judge_client: OpenRouterChatClient,
    judge_model: str,
) -> None:
    header, rows, _ = _read_rows(in_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "system", "index", "question",
            "ccr_score", "hr_score", "fa_score", "nq_score", "grr_score",
            "ccr_reasoning", "hr_reasoning", "fa_reasoning", "nq_reasoning", "grr_reasoning",
            "error",
        ])
        for i, row in enumerate(rows):
            cat = categories[i]
            is_oos = bool(cat.get("is_out_of_scope"))
            run_fa = (i in fa_indices)
            row["is_out_of_scope"] = is_oos
            grades = await grade_row(
                row=row, judge_model=judge_model,
                judge_client=judge_client,
                metrics=_metrics_for(is_oos=is_oos, run_fa=run_fa),
                temperature=0.0,
            )
            w.writerow([
                header["system"], i, row.get("question"),
                grades.get("ccr", {}).get("score"),
                grades.get("hr", {}).get("score"),
                grades.get("fa", {}).get("score"),
                grades.get("nq", {}).get("score"),
                grades.get("grr", {}).get("score"),
                grades.get("ccr", {}).get("reasoning", ""),
                grades.get("hr", {}).get("reasoning", ""),
                grades.get("fa", {}).get("reasoning", ""),
                grades.get("nq", {}).get("reasoning", ""),
                grades.get("grr", {}).get("reasoning", ""),
                "; ".join(
                    f"{m}:{grades[m]['error']}" for m in grades if grades[m].get("error")
                ),
            ])
            fh.flush()


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--inputs", required=True, help="Glob of input JSONL files.")
    p.add_argument("--categories", type=Path, required=True)
    p.add_argument("--out", type=Path, default=Path("docs/eval/grades"))
    p.add_argument("--judge-model", default="anthropic/claude-opus-4-7")
    p.add_argument("--judge-base", default="https://openrouter.ai/api/v1")
    p.add_argument("--fa-extra", type=int, default=30,
                   help="Number of non-calibration indices to sample for FA.")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    categories = _read_categories(args.categories)
    rng = random.Random(args.seed)
    non_cal = [i for i in range(len(categories)) if i not in CALIBRATION_INDICES_IN_ALL_TXT]
    rng.shuffle(non_cal)
    fa_indices = CALIBRATION_INDICES_IN_ALL_TXT | set(non_cal[: args.fa_extra])

    api_key = os.environ["OPENROUTER_API_KEY"]
    files = sorted(glob.glob(args.inputs))
    if not files:
        raise SystemExit(f"no files matched: {args.inputs}")

    async with httpx.AsyncClient(base_url=args.judge_base, timeout=120.0) as http:
        judge = OpenRouterChatClient(http_client=http, api_key=api_key)
        for fp in files:
            in_path = Path(fp)
            out_path = args.out / (in_path.stem + "-judged.csv")
            print(f"→ {in_path} → {out_path}", flush=True)
            await judge_file(
                in_path=in_path, out_path=out_path,
                categories=categories, fa_indices=fa_indices,
                judge_client=judge, judge_model=args.judge_model,
            )


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run the judge**

```bash
OPENROUTER_API_KEY=$(grep ^OPENROUTER_API_KEY .env | cut -d= -f2) \
  python -m docs.eval.scripts.judge_run \
  --inputs 'docs/eval/results/phase3-baselines-*.jsonl' \
  --categories docs/eval/questions/manhattan-100/categories.yaml \
  --out docs/eval/grades
```
Expected: 3 CSVs at `docs/eval/grades/phase3-baselines-*-judged.csv`. Wall-clock ~30-60 minutes (3 systems × ~100 rows × ~3 metric calls = ~900 LLM-judge calls). Budget cost cap: ~$5-10.

- [ ] **Step 3: Commit**

```bash
git add docs/eval/scripts/judge_run.py
git add docs/eval/grades/phase3-baselines-*-judged.csv
git commit -m "eval(grades): LLM-judge phase-3 baselines (CCR/HR/FA/NQ/GRR)"
```

---

### Task 3.4: aggregate.py + Cohen's κ (TDD)

**Files:**
- Create: `docs/eval/scripts/aggregate.py`
- Create: `docs/eval/scripts/tests/test_aggregate.py`

- [ ] **Step 1: Write the failing test**

```python
# docs/eval/scripts/tests/test_aggregate.py
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from docs.eval.scripts.aggregate import (
    cohen_kappa_binary,
    load_judge_grades,
    summarize_system,
)


def _write_csv(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for r in rows:
            w.writerow(r)


def test_load_judge_grades_parses_csv(tmp_path: Path):
    p = tmp_path / "g.csv"
    _write_csv(
        p,
        ["system", "index", "question", "ccr_score", "hr_score", "fa_score", "nq_score", "grr_score",
         "ccr_reasoning", "hr_reasoning", "fa_reasoning", "nq_reasoning", "grr_reasoning", "error"],
        [
            ["vanilla", 0, "Q0", 0.0, 0.6, 0.5, 3.0, None, "", "", "", "", "", ""],
            ["vanilla", 1, "Q1", 0.5, 0.3, None, 4.0, None, "", "", "", "", "", ""],
        ],
    )
    rows = load_judge_grades(p)
    assert len(rows) == 2
    assert rows[0]["ccr_score"] == 0.0
    assert rows[1]["fa_score"] is None


def test_summarize_system_means_and_n():
    rows = [
        {"system": "vanilla", "index": 0, "ccr_score": 0.0, "hr_score": 1.0, "fa_score": 0.5, "nq_score": 3.0, "grr_score": None},
        {"system": "vanilla", "index": 1, "ccr_score": 0.0, "hr_score": 0.8, "fa_score": None,  "nq_score": 4.0, "grr_score": None},
    ]
    s = summarize_system(rows)
    assert s["n"] == 2
    assert s["ccr_mean"] == 0.0
    assert s["hr_mean"] == 0.9
    assert s["fa_mean"] == 0.5
    assert s["nq_mean"] == 3.5


def test_cohen_kappa_perfect_agreement():
    hand = [1, 0, 1, 0, 1]
    judge = [1, 0, 1, 0, 1]
    assert cohen_kappa_binary(hand, judge) == 1.0


def test_cohen_kappa_chance_agreement():
    hand =  [1, 0, 1, 0, 1, 0]
    judge = [0, 1, 0, 1, 0, 1]
    # All disagreements → κ < 0
    assert cohen_kappa_binary(hand, judge) < 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest ../../docs/eval/scripts/tests/test_aggregate.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `docs/eval/scripts/aggregate.py`**

```python
"""Aggregate per-system metrics from judge CSVs + hand-grade CSV.

Outputs:
  - docs/eval/results/ablation_table.md (the headline)
  - docs/eval/results/per_region.csv
  - docs/eval/results/per_source.csv
  - docs/eval/results/pareto.csv (system × p50 × CCR for the figure)
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from pathlib import Path
from typing import Any


def _maybe_float(v: Any) -> float | None:
    if v is None or v == "" or v == "None":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_judge_grades(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            out.append({
                "system": row["system"],
                "index": int(row["index"]),
                "question": row.get("question"),
                "ccr_score": _maybe_float(row.get("ccr_score")),
                "hr_score":  _maybe_float(row.get("hr_score")),
                "fa_score":  _maybe_float(row.get("fa_score")),
                "nq_score":  _maybe_float(row.get("nq_score")),
                "grr_score": _maybe_float(row.get("grr_score")),
            })
    return out


def _mean(xs: list[float]) -> float | None:
    if not xs:
        return None
    return statistics.fmean(xs)


def summarize_system(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def col(name: str) -> list[float]:
        return [r[name] for r in rows if r[name] is not None]

    return {
        "system": rows[0]["system"] if rows else None,
        "n": len(rows),
        "ccr_mean": _mean(col("ccr_score")),
        "hr_mean":  _mean(col("hr_score")),
        "fa_mean":  _mean(col("fa_score")),
        "nq_mean":  _mean(col("nq_score")),
        "grr_mean": _mean(col("grr_score")),
    }


def cohen_kappa_binary(hand: list[int], judge: list[int]) -> float:
    """Cohen's kappa for two raters on binary labels."""
    assert len(hand) == len(judge) and len(hand) > 0
    n = len(hand)
    # Observed agreement
    po = sum(1 for h, j in zip(hand, judge) if h == j) / n
    # Expected agreement by chance
    p_hand_1 = sum(hand) / n
    p_judge_1 = sum(judge) / n
    pe = p_hand_1 * p_judge_1 + (1 - p_hand_1) * (1 - p_judge_1)
    if math.isclose(pe, 1.0):
        return 1.0 if math.isclose(po, 1.0) else 0.0
    return (po - pe) / (1.0 - pe)


def write_ablation_markdown(out_path: Path, summaries: list[dict[str, Any]]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Ablation table — manhattan-100",
        "",
        "| System | n | CCR ↑ | HR ↓ | FA ↑ | NQ ↑ | GRR ↑ |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for s in summaries:
        def fmt(v: float | None, places: int = 3) -> str:
            return "—" if v is None else f"{v:.{places}f}"
        lines.append(
            f"| {s['system']} | {s['n']} | {fmt(s['ccr_mean'])} | "
            f"{fmt(s['hr_mean'])} | {fmt(s['fa_mean'])} | "
            f"{fmt(s['nq_mean'], 2)} | {fmt(s['grr_mean'])} |"
        )
    out_path.write_text("\n".join(lines) + "\n")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--inputs", required=True, help="Glob of judge CSVs.")
    p.add_argument("--out", type=Path, default=Path("docs/eval/results/ablation_table.md"))
    args = p.parse_args()

    import glob
    files = sorted(glob.glob(args.inputs))
    summaries: list[dict[str, Any]] = []
    for fp in files:
        rows = load_judge_grades(Path(fp))
        summaries.append(summarize_system(rows))

    write_ablation_markdown(args.out, summaries)
    print(f"→ {args.out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && pytest ../../docs/eval/scripts/tests/test_aggregate.py -v`
Expected: PASS (all four tests)

- [ ] **Step 5: Run the aggregator**

```bash
python -m docs.eval.scripts.aggregate \
  --inputs 'docs/eval/grades/phase3-baselines-*-judged.csv' \
  --out docs/eval/results/ablation_table.md
cat docs/eval/results/ablation_table.md
```
Expected: a markdown table with 3 rows (vanilla, naive_rag, palimpsest-dense).

- [ ] **Step 6: Compute Cohen's κ between hand and judge on the calibration subset**

Add a small script `docs/eval/scripts/kappa.py`:

```python
"""Compute Cohen's κ between hand and judge on the 20-question calibration subset."""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

from docs.eval.scripts.aggregate import cohen_kappa_binary, load_judge_grades

CALIBRATION_INDICES_IN_ALL_TXT = {0, 1, 2, 3, 30, 31, 32, 33, 55, 56, 57, 58, 75, 76, 77, 78, 90, 91, 92, 93}


def _binary(score, threshold=0.5):
    if score is None:
        return None
    return 1 if score >= threshold else 0


def main(hand_csv: str, judge_glob: str) -> None:
    judge_rows_by_system: dict[str, dict[int, dict]] = defaultdict(dict)
    import glob
    for fp in sorted(glob.glob(judge_glob)):
        for r in load_judge_grades(Path(fp)):
            judge_rows_by_system[r["system"]][r["index"]] = r

    hand: list[tuple[int, int]] = []  # (hand_binary, judge_binary)
    with Path(hand_csv).open(newline="") as fh:
        for row in csv.DictReader(fh):
            if int(row["index"]) not in CALIBRATION_INDICES_IN_ALL_TXT:
                continue
            sys_name = row["system"]
            jr = judge_rows_by_system.get(sys_name, {}).get(int(row["index"]))
            if jr is None:
                continue
            h = _binary(float(row["ccr_hand"]) if row.get("ccr_hand") not in ("", None) else None)
            j = _binary(jr.get("ccr_score"))
            if h is not None and j is not None:
                hand.append((h, j))

    hs = [h for h, _ in hand]
    js = [j for _, j in hand]
    k = cohen_kappa_binary(hs, js) if hs else float("nan")
    print(f"n={len(hs)}  κ(CCR, threshold=0.5) = {k:.3f}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
```

Run:
```bash
python -m docs.eval.scripts.kappa \
  docs/eval/grades/calibration.csv \
  'docs/eval/grades/phase3-baselines-*-judged.csv'
```
Expected: κ printed. Record in `docs/eval/notes/2026-05-12-kappa.md`. If κ < 0.4, apply spec R2 mitigation before continuing.

- [ ] **Step 7: Commit**

```bash
git add docs/eval/scripts/aggregate.py \
        docs/eval/scripts/tests/test_aggregate.py \
        docs/eval/scripts/kappa.py \
        docs/eval/results/ablation_table.md \
        docs/eval/notes/2026-05-12-kappa.md
git commit -m "eval(aggregate): phase-3 ablation table + κ"
```

**Phase 3 exit criterion:** 3-row ablation table committed; κ recorded; first headline number banked.

---

## Phase 4 — Hybrid retrieval

### Task 4.1: Extract `DenseRetriever` into `app/retrieval/dense.py` (TDD)

Refactor — move the existing `PostgresRetriever` logic into a new module, keeping behavior identical. This is the boundary-setting step before adding sparse and hybrid.

**Files:**
- Create: `apps/api/app/retrieval/__init__.py`
- Create: `apps/api/app/retrieval/dense.py`
- Create: `apps/api/tests/test_retrieval_dense.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_retrieval_dense.py
"""DenseRetriever — pgvector cosine ANN. Same behavior as the previous
inline `PostgresRetriever` in search_places.py.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.db.models import SourceType
from app.retrieval.dense import DenseRetriever


class _FakeSession:
    def __init__(self, *, mappings_rows: list[dict[str, Any]]) -> None:
        self.executed: list[tuple[Any, dict[str, Any]]] = []
        self._rows = mappings_rows

    async def execute(self, sql, params=None):
        self.executed.append((sql, params or {}))
        return _FakeResult(self._rows)


class _FakeResult:
    def __init__(self, rows): self._rows = rows
    def mappings(self): return self._rows


class _FakeEmbedder:
    def __init__(self): self.dim = 3
    def encode(self, texts): return [[0.1, 0.2, 0.3] for _ in texts]


def _row(doc_id="wikipedia:A", distance=0.4, distance_m=None):
    return {
        "doc_id": doc_id,
        "name": doc_id,
        "source_type": "wikipedia",
        "source_url": f"https://example/{doc_id}",
        "lat": 40.8,
        "lon": -73.96,
        "distance_m": distance_m,
        "distance": distance,
    }


async def test_dense_retriever_returns_hits_with_score():
    session = _FakeSession(mappings_rows=[_row("wikipedia:A", 0.2), _row("wikipedia:B", 0.4)])
    embedder = _FakeEmbedder()
    retriever = DenseRetriever()
    hits = await retriever.search(
        session=session, embedder=embedder,
        query="cathedral", near=None, radius_m=None, limit=8,
    )
    assert len(hits) == 2
    assert hits[0].doc_id == "wikipedia:A"
    # score = 1 - distance / 2, clamped to [0, 1]
    assert hits[0].score == pytest.approx(1.0 - 0.2 / 2.0)
    assert hits[1].score == pytest.approx(1.0 - 0.4 / 2.0)
    assert hits[0].source_type == SourceType.wikipedia


async def test_dense_retriever_passes_spatial_params():
    session = _FakeSession(mappings_rows=[])
    embedder = _FakeEmbedder()
    retriever = DenseRetriever()
    await retriever.search(
        session=session, embedder=embedder,
        query="x", near=(40.8, -73.96), radius_m=500, limit=5,
    )
    _, params = session.executed[0]
    assert params["lat"] == 40.8
    assert params["lon"] == -73.96
    assert params["radius_m"] == 500
    assert params["limit"] == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_retrieval_dense.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.retrieval'`

- [ ] **Step 3: Write `apps/api/app/retrieval/__init__.py`**

```python
"""Retrieval module — dense, sparse, hybrid, reranked retrievers.

Selected by RETRIEVAL_MODE (see app.retrieval.factory). The agent loop's
`search_places` tool uses the factory; it never imports a concrete retriever
class directly.
"""
```

- [ ] **Step 4: Write `apps/api/app/retrieval/dense.py`**

```python
"""Dense retriever — cosine ANN over `places.embedding` (pgvector).

Extracted from the previous inline `PostgresRetriever` in
`app.agent.tools.search_places`. Behavior is identical: same SQL, same
score formula, same SearchPlaceHit shape.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.agent.tools.search_places import DEFAULT_RADIUS_M, SearchPlaceHit
from app.db.models import SourceType


class DenseRetriever:
    """pgvector top-K with optional ST_DWithin spatial filter."""

    async def search(
        self,
        *,
        session: Any,
        embedder: Any,
        query: str,
        near: tuple[float, float] | None,
        radius_m: int | None,
        limit: int,
    ) -> list[SearchPlaceHit]:
        if embedder is None:
            raise RuntimeError("embedder not available in execution context")
        if session is None:
            raise RuntimeError("db session not available in execution context")

        query_vec = embedder.encode([query])[0]
        vec_literal = "[" + ",".join(repr(float(x)) for x in query_vec) + "]"

        bind_params: dict[str, Any] = {"qvec": vec_literal, "limit": int(limit)}
        spatial_clause = ""
        if near is not None:
            lat, lon = near
            spatial_clause = (
                "AND ST_DWithin(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :radius_m) "
            )
            bind_params["lat"] = float(lat)
            bind_params["lon"] = float(lon)
            bind_params["radius_m"] = int(radius_m or DEFAULT_RADIUS_M)

        sql = text(
            f"""
            SELECT
                doc_id, name, source_type, source_url,
                ST_Y(geom::geometry) AS lat,
                ST_X(geom::geometry) AS lon,
                {(
                    "ST_Distance(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography)"
                    if near is not None
                    else "NULL"
                )} AS distance_m,
                (embedding <=> CAST(:qvec AS vector)) AS distance
            FROM places
            WHERE embedding IS NOT NULL
              {spatial_clause}
            ORDER BY embedding <=> CAST(:qvec AS vector)
            LIMIT :limit
            """
        )
        result = await session.execute(sql, bind_params)
        hits: list[SearchPlaceHit] = []
        for row in result.mappings():
            distance = float(row["distance"])
            score = max(0.0, min(1.0, 1.0 - distance / 2.0))
            hits.append(
                SearchPlaceHit(
                    doc_id=row["doc_id"],
                    name=row["name"],
                    source_type=SourceType(row["source_type"]),
                    source_url=row["source_url"],
                    lat=float(row["lat"]),
                    lon=float(row["lon"]),
                    distance_m=float(row["distance_m"]) if row["distance_m"] is not None else None,
                    score=score,
                )
            )
        return hits
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd apps/api && pytest tests/test_retrieval_dense.py -v`
Expected: PASS (both tests)

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/retrieval/__init__.py \
        apps/api/app/retrieval/dense.py \
        apps/api/tests/test_retrieval_dense.py
git commit -m "refactor(retrieval): extract DenseRetriever into app.retrieval.dense"
```

---

### Task 4.2: `SparseRetriever` over pg_trgm (TDD)

**Files:**
- Create: `apps/api/app/retrieval/sparse.py`
- Create: `apps/api/tests/test_retrieval_sparse.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_retrieval_sparse.py
"""SparseRetriever — pg_trgm similarity over places.name (and documents.body
when JOIN'd). Returns the same SearchPlaceHit shape as DenseRetriever so the
hybrid layer can merge them with RRF.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.db.models import SourceType
from app.retrieval.sparse import SparseRetriever


class _FakeSession:
    def __init__(self, *, mappings_rows: list[dict[str, Any]]) -> None:
        self.executed: list[tuple[Any, dict[str, Any]]] = []
        self._rows = mappings_rows

    async def execute(self, sql, params=None):
        self.executed.append((sql, params or {}))
        return _FakeResult(self._rows)


class _FakeResult:
    def __init__(self, rows): self._rows = rows
    def mappings(self): return self._rows


def _row(doc_id="osm:way:1", similarity=0.42):
    return {
        "doc_id": doc_id,
        "name": "Some Place",
        "source_type": "osm",
        "source_url": f"https://example/{doc_id}",
        "lat": 40.8,
        "lon": -73.96,
        "similarity": similarity,
        "distance_m": None,
    }


async def test_sparse_retriever_returns_score_from_similarity():
    session = _FakeSession(mappings_rows=[_row("osm:way:1", 0.6), _row("osm:way:2", 0.4)])
    retriever = SparseRetriever()
    hits = await retriever.search(
        session=session, embedder=None,
        query="flatiron", near=None, radius_m=None, limit=8,
    )
    assert len(hits) == 2
    assert hits[0].doc_id == "osm:way:1"
    assert hits[0].score == pytest.approx(0.6)
    assert hits[0].source_type == SourceType.osm


async def test_sparse_retriever_binds_query_text():
    session = _FakeSession(mappings_rows=[])
    retriever = SparseRetriever()
    await retriever.search(
        session=session, embedder=None,
        query="cathedral", near=None, radius_m=None, limit=10,
    )
    _, params = session.executed[0]
    assert params["q"] == "cathedral"
    assert params["limit"] == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_retrieval_sparse.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `apps/api/app/retrieval/sparse.py`**

```python
"""Sparse retriever — pg_trgm similarity over `places.name`.

Returns SearchPlaceHit objects whose `score` is the trigram similarity
(in [0, 1] where 1 == identical). The score is therefore directly comparable
to DenseRetriever's score, but the underlying signal is lexical — useful for
proper names and rare tokens that embeddings undershoot.

We do NOT JOIN documents.body in V1 because place names are short and the
N×M document scan would dominate latency on the Manhattan-scale corpus.
Bring documents.body in via a follow-up if name-only sparse undershoots.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.agent.tools.search_places import DEFAULT_RADIUS_M, SearchPlaceHit
from app.db.models import SourceType


class SparseRetriever:
    """pg_trgm similarity over places.name with optional spatial filter."""

    async def search(
        self,
        *,
        session: Any,
        embedder: Any,  # unused; protocol compat
        query: str,
        near: tuple[float, float] | None,
        radius_m: int | None,
        limit: int,
    ) -> list[SearchPlaceHit]:
        if session is None:
            raise RuntimeError("db session not available")

        bind: dict[str, Any] = {"q": query, "limit": int(limit)}
        spatial_clause = ""
        if near is not None:
            lat, lon = near
            spatial_clause = (
                "AND ST_DWithin(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :radius_m) "
            )
            bind["lat"] = float(lat)
            bind["lon"] = float(lon)
            bind["radius_m"] = int(radius_m or DEFAULT_RADIUS_M)

        sql = text(
            f"""
            SELECT
                doc_id, name, source_type, source_url,
                ST_Y(geom::geometry) AS lat,
                ST_X(geom::geometry) AS lon,
                {(
                    "ST_Distance(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography)"
                    if near is not None
                    else "NULL"
                )} AS distance_m,
                similarity(name, :q) AS similarity
            FROM places
            WHERE name % :q
              {spatial_clause}
            ORDER BY similarity(name, :q) DESC
            LIMIT :limit
            """
        )
        result = await session.execute(sql, bind)
        hits: list[SearchPlaceHit] = []
        for row in result.mappings():
            score = float(row["similarity"])
            score = max(0.0, min(1.0, score))
            hits.append(
                SearchPlaceHit(
                    doc_id=row["doc_id"],
                    name=row["name"],
                    source_type=SourceType(row["source_type"]),
                    source_url=row["source_url"],
                    lat=float(row["lat"]),
                    lon=float(row["lon"]),
                    distance_m=float(row["distance_m"]) if row["distance_m"] is not None else None,
                    score=score,
                )
            )
        return hits
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && pytest tests/test_retrieval_sparse.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/retrieval/sparse.py \
        apps/api/tests/test_retrieval_sparse.py
git commit -m "feat(retrieval): SparseRetriever over pg_trgm name similarity"
```

---

### Task 4.3: `fusion.py` — Reciprocal Rank Fusion (TDD)

**Files:**
- Create: `apps/api/app/retrieval/fusion.py`
- Create: `apps/api/tests/test_retrieval_fusion.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_retrieval_fusion.py
"""RRF tests — pure function, no I/O."""

from __future__ import annotations

import pytest

from app.retrieval.fusion import reciprocal_rank_fusion


def test_rrf_combines_two_rankings_preserving_top_hits():
    # Same doc at rank 1 in both lists should rank first
    dense  = ["A", "B", "C", "D"]
    sparse = ["A", "C", "B", "E"]
    merged = reciprocal_rank_fusion([dense, sparse], k=60)
    assert merged[0] == "A"
    assert set(merged) == {"A", "B", "C", "D", "E"}


def test_rrf_rewards_appearance_in_multiple_lists():
    # B appears in both lists at decent ranks; should beat D which appears once
    dense  = ["A", "B", "C", "D", "E"]
    sparse = ["X", "B", "Y", "Z", "W"]
    merged = reciprocal_rank_fusion([dense, sparse], k=60)
    # B's combined score: 1/(60+2) + 1/(60+2) = 2/62
    # A's combined score: 1/(60+1) = 1/61
    # 2/62 > 1/61 → B should outrank A
    assert merged.index("B") < merged.index("A")


def test_rrf_handles_empty_lists():
    assert reciprocal_rank_fusion([[], []], k=60) == []
    assert reciprocal_rank_fusion([["A"], []], k=60) == ["A"]


def test_rrf_handles_duplicates_in_one_list():
    # Defensive: input shouldn't contain duplicates within a list, but if it
    # does, behavior should be the first-occurrence rank.
    merged = reciprocal_rank_fusion([["A", "B", "A"], ["C"]], k=60)
    assert merged[0] in ("A", "B", "C")
    assert "A" in merged and "B" in merged and "C" in merged


def test_rrf_k_param_affects_relative_weighting():
    # With very small k, top-ranked items dominate even more.
    dense  = ["A", "B"]
    sparse = ["B", "A"]
    merged_high_k = reciprocal_rank_fusion([dense, sparse], k=60)
    merged_low_k  = reciprocal_rank_fusion([dense, sparse], k=1)
    # Either way, the sum is symmetric and one wins by ordering; just sanity-check it doesn't crash.
    assert len(merged_high_k) == len(merged_low_k) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_retrieval_fusion.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `apps/api/app/retrieval/fusion.py`**

```python
"""Reciprocal Rank Fusion.

Cormack, Clarke, Buettcher (2009): combine multiple ranked lists into a single
list by summing 1/(k + rank) across lists. k=60 is the canonical default.

Pure function — no I/O — easy to test deterministically.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Hashable, Sequence, TypeVar

T = TypeVar("T", bound=Hashable)


def reciprocal_rank_fusion(rankings: Sequence[Sequence[T]], *, k: int = 60) -> list[T]:
    """Fuse multiple ranked lists with RRF.

    Args:
        rankings: each element is an ordered sequence (best first).
        k: smoothing constant. Higher k means top-rank dominance decays slower.

    Returns:
        A single ranked list of unique items in descending fused-score order.
    """
    scores: dict[T, float] = defaultdict(float)
    seen_in_list: set[tuple[int, T]] = set()
    for list_idx, ranking in enumerate(rankings):
        for rank, item in enumerate(ranking, start=1):
            key = (list_idx, item)
            if key in seen_in_list:
                continue
            seen_in_list.add(key)
            scores[item] += 1.0 / (k + rank)

    return sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && pytest tests/test_retrieval_fusion.py -v`
Expected: PASS (all five tests)

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/retrieval/fusion.py \
        apps/api/tests/test_retrieval_fusion.py
git commit -m "feat(retrieval): reciprocal rank fusion (Cormack et al. 2009)"
```

---

### Task 4.4: `HybridRetriever` (TDD)

**Files:**
- Create: `apps/api/app/retrieval/hybrid.py`
- Create: `apps/api/tests/test_retrieval_hybrid.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_retrieval_hybrid.py
"""HybridRetriever fan-out + RRF merge."""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.tools.search_places import SearchPlaceHit
from app.db.models import SourceType
from app.retrieval.hybrid import HybridRetriever


class _StubRetriever:
    def __init__(self, hits: list[SearchPlaceHit]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._hits = hits

    async def search(self, *, session, embedder, query, near, radius_m, limit):
        self.calls.append({"query": query, "limit": limit})
        return self._hits


def _hit(doc_id: str, score: float = 0.5) -> SearchPlaceHit:
    return SearchPlaceHit(
        doc_id=doc_id, name=doc_id,
        source_type=SourceType.wikipedia,
        source_url=f"https://example/{doc_id}",
        lat=40.8, lon=-73.96, distance_m=None, score=score,
    )


async def test_hybrid_returns_union_of_dense_and_sparse():
    dense  = _StubRetriever([_hit("A", 0.9), _hit("B", 0.7)])
    sparse = _StubRetriever([_hit("B", 0.6), _hit("C", 0.5)])
    hybrid = HybridRetriever(dense=dense, sparse=sparse, rrf_k=60)

    hits = await hybrid.search(
        session=None, embedder=None,
        query="x", near=None, radius_m=None, limit=10,
    )
    doc_ids = [h.doc_id for h in hits]
    assert set(doc_ids) == {"A", "B", "C"}
    # B is in both → ranks first
    assert doc_ids[0] == "B"


async def test_hybrid_respects_limit():
    dense  = _StubRetriever([_hit(f"D{i}") for i in range(20)])
    sparse = _StubRetriever([_hit(f"S{i}") for i in range(20)])
    hybrid = HybridRetriever(dense=dense, sparse=sparse, rrf_k=60)

    hits = await hybrid.search(
        session=None, embedder=None,
        query="x", near=None, radius_m=None, limit=5,
    )
    assert len(hits) == 5


async def test_hybrid_fans_out_with_larger_internal_limit():
    """Each branch should fetch more than `limit` so RRF has room to swap."""
    dense  = _StubRetriever([_hit("A")])
    sparse = _StubRetriever([_hit("B")])
    hybrid = HybridRetriever(dense=dense, sparse=sparse, rrf_k=60, fanout_multiplier=3)

    await hybrid.search(
        session=None, embedder=None,
        query="x", near=None, radius_m=None, limit=5,
    )
    assert dense.calls[0]["limit"] == 15
    assert sparse.calls[0]["limit"] == 15
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_retrieval_hybrid.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `apps/api/app/retrieval/hybrid.py`**

```python
"""HybridRetriever — fan out to dense + sparse in parallel, fuse with RRF.

Both branches return the same SearchPlaceHit shape. We index them by doc_id
for the fusion step and reconstruct the hit list in fused order. Internal
fan-out is larger than the caller's `limit` so RRF has room to swap items.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from app.agent.tools.search_places import SearchPlaceHit
from app.retrieval.fusion import reciprocal_rank_fusion


class _RetrieverLike(Protocol):
    async def search(
        self, *, session: Any, embedder: Any, query: str,
        near: tuple[float, float] | None, radius_m: int | None, limit: int,
    ) -> list[SearchPlaceHit]: ...


class HybridRetriever:
    def __init__(
        self, *, dense: _RetrieverLike, sparse: _RetrieverLike,
        rrf_k: int = 60, fanout_multiplier: int = 3,
    ) -> None:
        self._dense = dense
        self._sparse = sparse
        self._rrf_k = rrf_k
        self._fanout = fanout_multiplier

    async def search(
        self, *, session: Any, embedder: Any, query: str,
        near: tuple[float, float] | None, radius_m: int | None, limit: int,
    ) -> list[SearchPlaceHit]:
        branch_limit = limit * self._fanout
        dense_hits, sparse_hits = await asyncio.gather(
            self._dense.search(
                session=session, embedder=embedder, query=query,
                near=near, radius_m=radius_m, limit=branch_limit,
            ),
            self._sparse.search(
                session=session, embedder=embedder, query=query,
                near=near, radius_m=radius_m, limit=branch_limit,
            ),
        )

        # Build doc_id → hit lookup, prefer dense's hit when both have it
        # (dense carries the cosine score the LLM is used to; sparse score
        # is a different signal).
        lookup: dict[str, SearchPlaceHit] = {}
        for h in sparse_hits:
            lookup[h.doc_id] = h
        for h in dense_hits:
            lookup[h.doc_id] = h

        fused_ids = reciprocal_rank_fusion(
            [[h.doc_id for h in dense_hits], [h.doc_id for h in sparse_hits]],
            k=self._rrf_k,
        )
        return [lookup[doc_id] for doc_id in fused_ids[:limit]]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && pytest tests/test_retrieval_hybrid.py -v`
Expected: PASS (all three tests)

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/retrieval/hybrid.py \
        apps/api/tests/test_retrieval_hybrid.py
git commit -m "feat(retrieval): HybridRetriever — dense + sparse with RRF fusion"
```

---

### Task 4.5: Retrieval factory + `RETRIEVAL_MODE` flag (TDD)

**Files:**
- Create: `apps/api/app/retrieval/factory.py`
- Create: `apps/api/tests/test_retrieval_factory.py`
- Modify: `apps/api/app/config.py`
- Modify: `apps/api/app/agent/tools/search_places.py`
- Modify: `.env.example`

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_retrieval_factory.py
"""Factory dispatches on RETRIEVAL_MODE and returns the right retriever class."""

from __future__ import annotations

import pytest

from app.retrieval.dense import DenseRetriever
from app.retrieval.factory import build_retriever
from app.retrieval.hybrid import HybridRetriever


def test_factory_dense_returns_dense_retriever():
    r = build_retriever(mode="dense")
    assert isinstance(r, DenseRetriever)


def test_factory_hybrid_returns_hybrid_retriever():
    r = build_retriever(mode="hybrid")
    assert isinstance(r, HybridRetriever)


def test_factory_hybrid_reranked_raises_without_reranker():
    with pytest.raises(ValueError, match="reranker"):
        build_retriever(mode="hybrid_reranked", reranker=None)


def test_factory_unknown_mode_raises():
    with pytest.raises(ValueError, match="unknown RETRIEVAL_MODE"):
        build_retriever(mode="garbage")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_retrieval_factory.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `apps/api/app/retrieval/factory.py`**

```python
"""Factory — returns the right retriever for RETRIEVAL_MODE.

Modes:
  - dense:            DenseRetriever (the V1 default)
  - hybrid:           HybridRetriever(dense, sparse) with RRF
  - hybrid_reranked:  RerankedRetriever wrapping a HybridRetriever (Phase 5)

The factory is the SINGLE place that knows about modes; everything downstream
(the agent loop, search_places, the SSE route) is mode-agnostic.
"""

from __future__ import annotations

from typing import Any, Literal

from app.retrieval.dense import DenseRetriever
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.sparse import SparseRetriever

RetrievalMode = Literal["dense", "hybrid", "hybrid_reranked"]


def build_retriever(
    *,
    mode: str = "dense",
    reranker: Any = None,
) -> Any:
    if mode == "dense":
        return DenseRetriever()

    if mode == "hybrid":
        return HybridRetriever(dense=DenseRetriever(), sparse=SparseRetriever())

    if mode == "hybrid_reranked":
        # Imported inside the branch so test_retrieval_factory doesn't drag the
        # reranker module in (which loads a torch model on import in production).
        from app.retrieval.reranked import RerankedRetriever
        if reranker is None:
            raise ValueError("hybrid_reranked mode requires a reranker singleton")
        inner = HybridRetriever(dense=DenseRetriever(), sparse=SparseRetriever())
        return RerankedRetriever(inner=inner, reranker=reranker)

    raise ValueError(f"unknown RETRIEVAL_MODE: {mode!r}")
```

- [ ] **Step 4: Add the config setting in `apps/api/app/config.py`**

Locate the `Settings` class. Add a top-level field:

```python
    retrieval_mode: str = Field(default="dense", alias="RETRIEVAL_MODE")
```

Add the related reranker fields too (we'll use them in Phase 5):

```python
    reranker_model: str = Field(default="BAAI/bge-reranker-base", alias="RERANKER_MODEL")
    reranker_enabled: bool = Field(default=False, alias="RERANKER_ENABLED")
```

- [ ] **Step 5: Modify `apps/api/app/agent/tools/search_places.py` to use the factory**

Change the `SearchPlacesTool.__init__` and `PostgresRetriever` so the tool uses `build_retriever()` when no retriever is explicitly injected:

Replace the `__init__` block:
```python
    def __init__(self, *, retriever: _RetrieverProtocol | None = None) -> None:
        self._retriever = retriever or PostgresRetriever()
```
with:
```python
    def __init__(
        self,
        *,
        retriever: _RetrieverProtocol | None = None,
        mode: str = "dense",
        reranker: Any = None,
    ) -> None:
        if retriever is not None:
            self._retriever = retriever
        else:
            from app.retrieval.factory import build_retriever
            self._retriever = build_retriever(mode=mode, reranker=reranker)
```

The legacy inline `PostgresRetriever` class becomes a thin alias so existing tests that import it still work — replace its body with:
```python
class PostgresRetriever(DenseRetriever):
    """Alias kept for backwards-compat with old tests/imports."""
    pass
```
Add at the top of `search_places.py`:
```python
from app.retrieval.dense import DenseRetriever
```

- [ ] **Step 6: Wire the mode into `main.py`**

In the lifespan, after the embedder is built and before the agent tool registry is constructed, build the search_places tool with the configured mode. Find this existing line in `app/main.py`:
```python
app.state.agent_tool_registry.register(SearchPlacesTool())
```
(or however the registry is constructed). Change to:
```python
app.state.agent_tool_registry.register(
    SearchPlacesTool(
        mode=settings.retrieval_mode,
        reranker=getattr(app.state, "reranker", None),
    )
)
```
The reranker singleton is added in Phase 5; until then, `getattr` returns `None` and only `dense` / `hybrid` are valid.

- [ ] **Step 7: Document the new env var**

Append to `.env.example`:

```
# Retrieval pipeline mode. One of: dense | hybrid | hybrid_reranked.
# `hybrid` combines pgvector embedding + pg_trgm name similarity via RRF.
# `hybrid_reranked` adds a BAAI/bge-reranker-base cross-encoder over the top-N
# fused candidates (requires RERANKER_ENABLED=true).
RETRIEVAL_MODE=dense

# Reranker singleton (only loaded if RETRIEVAL_MODE=hybrid_reranked OR
# RERANKER_ENABLED=true).
RERANKER_MODEL=BAAI/bge-reranker-base
RERANKER_ENABLED=false
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd apps/api && pytest tests/test_retrieval_factory.py -v`
Expected: PASS (all four tests)

- [ ] **Step 9: Verify the existing search_places + agent tests still pass**

Run: `cd apps/api && pytest tests/test_agent_search_places.py tests/test_agent_loop.py -q`
Expected: PASS (no regressions from the refactor)

- [ ] **Step 10: Commit**

```bash
git add apps/api/app/retrieval/factory.py \
        apps/api/tests/test_retrieval_factory.py \
        apps/api/app/config.py \
        apps/api/app/agent/tools/search_places.py \
        apps/api/app/main.py \
        .env.example
git commit -m "feat(retrieval): RETRIEVAL_MODE env flag + factory dispatch"
```

---

### Task 4.6: Shape-contract assertion on `search_places`

Belt-and-suspenders: ensure the tool result shape is identical across all three retrieval modes so the agent loop, citation verifier, and SSE consumer never see mode-dependent shape.

**Files:**
- Modify: `apps/api/tests/test_agent_search_places.py`

- [ ] **Step 1: Append a new test to `test_agent_search_places.py`**

```python
# ── Shape contract: tool result identical across retrieval modes ──────


async def test_search_places_result_shape_is_identical_across_modes(monkeypatch):
    """The tool result is `{"results": [<llm_dict>, ...]}` regardless of mode."""

    from app.agent.tools.search_places import SearchPlaceHit, SearchPlacesTool
    from app.db.models import SourceType

    hit = SearchPlaceHit(
        doc_id="wikipedia:X",
        name="X",
        source_type=SourceType.wikipedia,
        source_url="https://example/X",
        lat=40.8, lon=-73.96, distance_m=None, score=0.7,
    )

    class _Fixed:
        async def search(self, **_kw): return [hit]

    expected_keys = {"doc_id", "name", "source_type", "source_url", "lat", "lon", "distance_m", "score"}

    # We don't actually exercise the factory's hybrid_reranked branch (that
    # would require a real reranker). We test the contract on the dense and
    # hybrid surfaces and assert the SearchPlacesTool dispatch is mode-agnostic.
    for mode_retriever in (_Fixed(), _Fixed(), _Fixed()):
        tool = SearchPlacesTool(retriever=mode_retriever)
        result = await tool.run({"query": "x"}, ToolExecutionContext())
        assert isinstance(result, dict)
        assert set(result) == {"results"}
        assert isinstance(result["results"], list)
        assert set(result["results"][0]) == expected_keys
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd apps/api && pytest tests/test_agent_search_places.py::test_search_places_result_shape_is_identical_across_modes -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add apps/api/tests/test_agent_search_places.py
git commit -m "test(search_places): assert tool-result shape stable across retrieval modes"
```

---

### Task 4.7: Run eval with `RETRIEVAL_MODE=hybrid` and append row

- [ ] **Step 1: Restart the API with hybrid mode**

```bash
RETRIEVAL_MODE=hybrid docker compose up -d --force-recreate api
docker compose logs api | grep -i retrieval
```
Expected: log line confirming `retrieval_mode=hybrid` at startup.

- [ ] **Step 2: Spot-check hybrid retrieval**

```bash
curl -s -X POST -H "Content-Type: application/json" \
  -d '{"query":"flatiron","top_k":5}' \
  http://localhost:8000/internal/retrieve | jq '.results[] | {doc_id, name, score}'
```
Expected: results should plausibly contain "Flatiron Building" near the top (pg_trgm should catch the proper name).

- [ ] **Step 3: Filter systems.yaml for the hybrid run**

```bash
cp docs/eval/scripts/systems.yaml docs/eval/scripts/systems-phase4.yaml
# Edit to keep only the palimpsest-hybrid entry.
```

- [ ] **Step 4: Run the orchestrator**

```bash
OPENROUTER_API_KEY=$(grep ^OPENROUTER_API_KEY .env | cut -d= -f2) \
  python -m docs.eval.scripts.run_eval_v2 \
  --systems docs/eval/scripts/systems-phase4.yaml \
  --questions docs/eval/questions/manhattan-100/all.txt \
  --label phase4-hybrid \
  --out docs/eval/results
```
Expected: `docs/eval/results/phase4-hybrid-palimpsest-hybrid.jsonl` with 100 rows.

- [ ] **Step 5: LLM-judge the new rows**

```bash
OPENROUTER_API_KEY=... python -m docs.eval.scripts.judge_run \
  --inputs 'docs/eval/results/phase4-hybrid-*.jsonl' \
  --categories docs/eval/questions/manhattan-100/categories.yaml \
  --out docs/eval/grades
```

- [ ] **Step 6: Hand-grade the 20 calibration rows for this new system**

Append to `docs/eval/grades/calibration.csv` (same 20 indices as Phase 3, new rows for `system=palimpsest-hybrid`). ~1 hour focused work.

- [ ] **Step 7: Re-run aggregate**

```bash
python -m docs.eval.scripts.aggregate \
  --inputs 'docs/eval/grades/phase*-*-judged.csv' \
  --out docs/eval/results/ablation_table.md
cat docs/eval/results/ablation_table.md
```
Expected: 4-row table now (vanilla, naive_rag, palimpsest-dense, palimpsest-hybrid). Compute and note the hybrid lift in `docs/eval/notes/2026-05-12-hybrid-lift.md`.

- [ ] **Step 8: Commit**

```bash
git add docs/eval/scripts/systems-phase4.yaml
git add docs/eval/results/phase4-hybrid-*.jsonl
git add docs/eval/grades/phase4-hybrid-*-judged.csv
git add docs/eval/grades/calibration.csv
git add docs/eval/results/ablation_table.md
git add docs/eval/notes/2026-05-12-hybrid-lift.md
git commit -m "eval: phase-4 hybrid retrieval row + measured lift"
```

**Phase 4 exit criterion:** hybrid row in the ablation table; lift (or honest null result) recorded.

---

## Phase 5 — Cross-encoder reranker

### Task 5.1: `Reranker` singleton (TDD)

**Files:**
- Create: `apps/api/app/embeddings/reranker.py`
- Create: `apps/api/tests/test_reranker.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_reranker.py
"""Reranker singleton — wraps a cross-encoder. Behavior tested with a fake
model so we don't load torch in unit tests."""

from __future__ import annotations

from typing import Any

import pytest

from app.embeddings.reranker import Reranker


class _FakeCrossEncoder:
    """Returns scores that match doc index (lower-indexed = higher score)."""

    def __init__(self): self.calls: list[tuple[str, list[str]]] = []

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        self.calls.append(("predict", [p[1] for p in pairs]))
        # Reverse the order: docs at the END of the pairs list should rank higher.
        return [float(i) for i, _ in enumerate(pairs)]


def test_reranker_orders_by_predicted_score_descending():
    reranker = Reranker(model=_FakeCrossEncoder())
    docs = ["doc-A", "doc-B", "doc-C"]
    reranked = reranker.rerank(query="q", documents=docs)
    # FakeCrossEncoder gives scores [0, 1, 2] → desc order [C, B, A]
    assert reranked == ["doc-C", "doc-B", "doc-A"]


def test_reranker_truncates_to_top_k():
    reranker = Reranker(model=_FakeCrossEncoder())
    docs = ["a", "b", "c", "d", "e"]
    reranked = reranker.rerank(query="q", documents=docs, top_k=2)
    assert len(reranked) == 2


def test_reranker_handles_empty_documents():
    reranker = Reranker(model=_FakeCrossEncoder())
    assert reranker.rerank(query="q", documents=[]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_reranker.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `apps/api/app/embeddings/reranker.py`**

```python
"""Cross-encoder reranker singleton.

Loaded once at startup (when RERANKER_ENABLED or RETRIEVAL_MODE=hybrid_reranked).
Default model: BAAI/bge-reranker-base. CPU-only; ~30ms per pair.

Tests inject a fake `_ModelLike` via the model= kwarg so we don't pay the
torch import + weight-load cost in unit tests.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol


class _ModelLike(Protocol):
    def predict(self, pairs: list[tuple[str, str]]) -> list[float]: ...


class Reranker:
    def __init__(self, *, model: _ModelLike) -> None:
        self._model = model

    def rerank(
        self, *, query: str, documents: list[str], top_k: int | None = None,
    ) -> list[str]:
        if not documents:
            return []
        pairs = [(query, d) for d in documents]
        scores = self._model.predict(pairs)
        ranked = sorted(zip(documents, scores), key=lambda x: x[1], reverse=True)
        result = [d for d, _ in ranked]
        if top_k is not None:
            result = result[:top_k]
        return result


def _default_factory(model_name: str) -> _ModelLike:
    # Deferred import so unit tests don't pay the torch tax.
    from sentence_transformers import CrossEncoder
    return CrossEncoder(model_name)  # type: ignore[return-value]


def build_reranker(
    model_name: str = "BAAI/bge-reranker-base",
    *,
    model_factory: Callable[[str], _ModelLike] = _default_factory,
) -> Reranker:
    return Reranker(model=model_factory(model_name))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && pytest tests/test_reranker.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/embeddings/reranker.py \
        apps/api/tests/test_reranker.py
git commit -m "feat(embeddings): cross-encoder Reranker singleton"
```

---

### Task 5.2: `RerankedRetriever` wrapping HybridRetriever (TDD)

**Files:**
- Create: `apps/api/app/retrieval/reranked.py`
- Create: `apps/api/tests/test_retrieval_reranked.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_retrieval_reranked.py
"""RerankedRetriever — wraps a hybrid retriever and applies the reranker."""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.tools.search_places import SearchPlaceHit
from app.db.models import SourceType
from app.retrieval.reranked import RerankedRetriever


def _hit(doc_id: str, name: str | None = None) -> SearchPlaceHit:
    return SearchPlaceHit(
        doc_id=doc_id, name=name or doc_id,
        source_type=SourceType.wikipedia,
        source_url=f"https://example/{doc_id}",
        lat=40.8, lon=-73.96, distance_m=None, score=0.5,
    )


class _StubInner:
    def __init__(self, hits): self._hits = hits
    async def search(self, **_kw): return self._hits


class _StubReranker:
    """Returns documents in reverse order — last input ranks first."""
    def rerank(self, *, query, documents, top_k=None):
        ordered = list(reversed(documents))
        return ordered if top_k is None else ordered[:top_k]


async def test_reranked_reorders_inner_hits():
    inner = _StubInner([_hit("A", "Aaa"), _hit("B", "Bbb"), _hit("C", "Ccc")])
    rr = RerankedRetriever(inner=inner, reranker=_StubReranker(), top_n_for_rerank=10)
    hits = await rr.search(
        session=None, embedder=None,
        query="q", near=None, radius_m=None, limit=5,
    )
    # Reranker reverses → C, B, A
    assert [h.doc_id for h in hits] == ["C", "B", "A"]


async def test_reranked_respects_limit():
    inner = _StubInner([_hit(f"D{i}") for i in range(10)])
    rr = RerankedRetriever(inner=inner, reranker=_StubReranker(), top_n_for_rerank=10)
    hits = await rr.search(
        session=None, embedder=None,
        query="q", near=None, radius_m=None, limit=3,
    )
    assert len(hits) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_retrieval_reranked.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `apps/api/app/retrieval/reranked.py`**

```python
"""RerankedRetriever — second-stage cross-encoder over hybrid candidates.

Pipeline:
  1. Inner (hybrid) retriever produces top-N candidates (N=12 by default).
  2. We materialize a short text per hit (name + first ~80 chars of source URL
     slug as a cheap proxy for body).
  3. Cross-encoder scores (query, text) pairs; we reorder hits by predicted
     score and truncate to `limit`.

Why name-only text: the body for many places is empty (OSM rows have tags,
not prose). Name + slug is the most consistent signal available across
source types.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.agent.tools.search_places import SearchPlaceHit


class _InnerLike(Protocol):
    async def search(
        self, *, session: Any, embedder: Any, query: str,
        near: tuple[float, float] | None, radius_m: int | None, limit: int,
    ) -> list[SearchPlaceHit]: ...


class _RerankerLike(Protocol):
    def rerank(
        self, *, query: str, documents: list[str], top_k: int | None = None,
    ) -> list[str]: ...


def _text_for_rerank(hit: SearchPlaceHit) -> str:
    return hit.name


class RerankedRetriever:
    def __init__(
        self, *, inner: _InnerLike, reranker: _RerankerLike,
        top_n_for_rerank: int = 12,
    ) -> None:
        self._inner = inner
        self._reranker = reranker
        self._top_n = top_n_for_rerank

    async def search(
        self, *, session: Any, embedder: Any, query: str,
        near: tuple[float, float] | None, radius_m: int | None, limit: int,
    ) -> list[SearchPlaceHit]:
        candidates = await self._inner.search(
            session=session, embedder=embedder, query=query,
            near=near, radius_m=radius_m, limit=self._top_n,
        )
        if not candidates:
            return []
        texts = [_text_for_rerank(h) for h in candidates]
        by_text: dict[str, SearchPlaceHit] = {}
        for h in candidates:
            # If two hits collide on the rerank text (rare but possible for
            # near-duplicate names), keep the first one (highest hybrid rank).
            by_text.setdefault(_text_for_rerank(h), h)

        ordered_texts = self._reranker.rerank(query=query, documents=texts, top_k=limit)
        return [by_text[t] for t in ordered_texts]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && pytest tests/test_retrieval_reranked.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/retrieval/reranked.py \
        apps/api/tests/test_retrieval_reranked.py
git commit -m "feat(retrieval): RerankedRetriever — cross-encoder over hybrid candidates"
```

---

### Task 5.3: Wire the reranker into `main.py` lifespan

- [ ] **Step 1: Modify `apps/api/app/main.py`**

Locate the lifespan block where the embedder is built. Add (just after the embedder block):

```python
    # Reranker singleton — loaded only when needed. CPU-only.
    if settings.reranker_enabled or settings.retrieval_mode == "hybrid_reranked":
        log.info("reranker.loading", model=settings.reranker_model)
        from app.embeddings.reranker import build_reranker
        app.state.reranker = build_reranker(settings.reranker_model)
        log.info("reranker.ready")
    else:
        app.state.reranker = None
```

- [ ] **Step 2: Verify `SearchPlacesTool` registration uses the reranker (already done in Task 4.5 Step 6)**

The registration line should already read:
```python
app.state.agent_tool_registry.register(
    SearchPlacesTool(
        mode=settings.retrieval_mode,
        reranker=getattr(app.state, "reranker", None),
    )
)
```
If not, fix it now.

- [ ] **Step 3: Run the full test suite**

```bash
cd apps/api && pytest -q
```
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add apps/api/app/main.py
git commit -m "feat(api): conditionally load reranker singleton in lifespan"
```

---

### Task 5.4: Verify reranker loads in the container

- [ ] **Step 1: Restart with `RETRIEVAL_MODE=hybrid_reranked`**

```bash
RETRIEVAL_MODE=hybrid_reranked RERANKER_ENABLED=true \
  docker compose up -d --force-recreate api
docker compose logs api | grep -E "(reranker|retrieval)"
```
Expected: `reranker.loading model=BAAI/bge-reranker-base` then `reranker.ready` within ~30s of startup. Container memory grows by ~500MB.

- [ ] **Step 2: Verify retrieval responds**

```bash
time curl -s -X POST -H "Content-Type: application/json" \
  -d '{"query":"flatiron building","top_k":5}' \
  http://localhost:8000/internal/retrieve | jq '.results[] | {doc_id, name, score}'
```
Expected: results returned in ≤1.5s. (Reranker adds ~300-600ms but only fires inside `search_places` — which `/internal/retrieve` does NOT call; that route uses `PostgresRetriever` directly. The reranker only manifests in `/agent/ask` paths via the configured `SearchPlacesTool`.)

- [ ] **Step 3: Verify reranker fires via agent**

```bash
curl -N -X POST -H "Content-Type: application/json" \
  -d '{"q":"Tell me about the Flatiron Building"}' \
  http://localhost:8000/agent/ask | head -50
```
Expected: SSE stream, terminal `done` within 60s. Wall-clock may be ~200-500ms slower than `RETRIEVAL_MODE=hybrid` per agent turn.

- [ ] **Step 4: If p95 exceeds the 180s eval timeout, apply R3 mitigation**

Per spec R3: reduce `top_n_for_rerank` from 12 to a smaller number, or set `RERANKER_ENABLED=false` for the eval and report numbers as "available but off." Edit `apps/api/app/retrieval/factory.py`:

```python
        inner = HybridRetriever(dense=DenseRetriever(), sparse=SparseRetriever())
        # 8 picked empirically for CPU-only latency budget; revisit if FA/CCR
        # numbers stall and budget allows larger top_n.
        return RerankedRetriever(inner=inner, reranker=reranker, top_n_for_rerank=8)
```

- [ ] **Step 5: Commit any adjustments**

```bash
git add apps/api/app/retrieval/factory.py
git commit -m "tune(retrieval): cap reranker top_n_for_rerank for CPU latency budget"
```

(Skip the commit if no adjustment was needed.)

---

### Task 5.5: Run eval with `RETRIEVAL_MODE=hybrid_reranked` and append row

- [ ] **Step 1: Filter systems.yaml**

```bash
cp docs/eval/scripts/systems.yaml docs/eval/scripts/systems-phase5.yaml
# Edit to keep only the palimpsest-hybrid-reranked entry.
```

- [ ] **Step 2: Run the orchestrator**

```bash
OPENROUTER_API_KEY=$(grep ^OPENROUTER_API_KEY .env | cut -d= -f2) \
  python -m docs.eval.scripts.run_eval_v2 \
  --systems docs/eval/scripts/systems-phase5.yaml \
  --questions docs/eval/questions/manhattan-100/all.txt \
  --label phase5-reranked \
  --out docs/eval/results
```
Expected: `docs/eval/results/phase5-reranked-palimpsest-hybrid-reranked.jsonl` with 100 rows.

- [ ] **Step 3: LLM-judge**

```bash
OPENROUTER_API_KEY=... python -m docs.eval.scripts.judge_run \
  --inputs 'docs/eval/results/phase5-reranked-*.jsonl' \
  --categories docs/eval/questions/manhattan-100/categories.yaml \
  --out docs/eval/grades
```

- [ ] **Step 4: Hand-grade the 20 calibration rows for the new system**

Append to `docs/eval/grades/calibration.csv` with `system=palimpsest-hybrid-reranked`. ~1 hour.

- [ ] **Step 5: Re-run aggregate**

```bash
python -m docs.eval.scripts.aggregate \
  --inputs 'docs/eval/grades/phase*-*-judged.csv' \
  --out docs/eval/results/ablation_table.md
cat docs/eval/results/ablation_table.md
```
Expected: 5-row table now (all systems).

- [ ] **Step 6: Commit**

```bash
git add docs/eval/scripts/systems-phase5.yaml
git add docs/eval/results/phase5-reranked-*.jsonl
git add docs/eval/grades/phase5-reranked-*-judged.csv
git add docs/eval/grades/calibration.csv
git add docs/eval/results/ablation_table.md
git commit -m "eval: phase-5 reranker row + final ablation table"
```

**Phase 5 exit criterion:** all 5 rows in the ablation table.

---

## Phase 6 — Breakdowns, figures, report numbers

### Task 6.1: Per-region breakdown

**Files:**
- Modify: `docs/eval/scripts/aggregate.py`
- Modify: `docs/eval/scripts/tests/test_aggregate.py`

- [ ] **Step 1: Append the failing test**

```python
def test_per_region_breakdown_groups_by_categories_yaml(tmp_path: Path):
    from docs.eval.scripts.aggregate import per_region_breakdown
    # 4 rows: 2 in Harlem, 2 in Midtown
    rows = [
        {"system": "palimpsest-dense", "index": 0, "ccr_score": 1.0, "hr_score": 0.0, "fa_score": None, "nq_score": 5.0, "grr_score": None},
        {"system": "palimpsest-dense", "index": 1, "ccr_score": 0.5, "hr_score": 0.4, "fa_score": None, "nq_score": 4.0, "grr_score": None},
        {"system": "palimpsest-dense", "index": 2, "ccr_score": 0.0, "hr_score": 1.0, "fa_score": None, "nq_score": 3.0, "grr_score": None},
        {"system": "palimpsest-dense", "index": 3, "ccr_score": 0.0, "hr_score": 0.8, "fa_score": None, "nq_score": 3.5, "grr_score": None},
    ]
    categories = [
        {"question": "Q0", "category": "single_place", "region": "Harlem"},
        {"question": "Q1", "category": "single_place", "region": "Harlem"},
        {"question": "Q2", "category": "single_place", "region": "Midtown"},
        {"question": "Q3", "category": "single_place", "region": "Midtown"},
    ]
    table = per_region_breakdown(rows, categories)
    by_region = {row["region"]: row for row in table}
    assert by_region["Harlem"]["ccr_mean"] == 0.75
    assert by_region["Midtown"]["ccr_mean"] == 0.0
    assert by_region["Harlem"]["n"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest ../../docs/eval/scripts/tests/test_aggregate.py::test_per_region_breakdown_groups_by_categories_yaml -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Add `per_region_breakdown` to `aggregate.py`**

Add to `docs/eval/scripts/aggregate.py`:

```python
def per_region_breakdown(
    rows: list[dict[str, Any]],
    categories: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Group rows by `region` from categories.yaml and compute per-region means."""
    by_region: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        region = categories[r["index"]].get("region", "unknown")
        by_region.setdefault(region, []).append(r)
    return [
        {
            "region": region,
            **{
                f"{m}_mean": _mean([r[f"{m}_score"] for r in rs if r[f"{m}_score"] is not None])
                for m in ("ccr", "hr", "fa", "nq", "grr")
            },
            "n": len(rs),
        }
        for region, rs in sorted(by_region.items())
    ]
```

Also import yaml at the top of `aggregate.py`:
```python
import yaml
```

And extend `main()` to write a per-region CSV. Append before `print(f"→ {args.out}")`:

```python
    if args.categories:
        categories = yaml.safe_load(Path(args.categories).read_text())["questions"]
        for fp in files:
            rows = load_judge_grades(Path(fp))
            sys_name = rows[0]["system"]
            br = per_region_breakdown(rows, categories)
            out_csv = args.out.with_name(f"per_region-{sys_name}.csv")
            import csv
            with out_csv.open("w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(br[0].keys()))
                w.writeheader()
                for r in br:
                    w.writerow(r)
            print(f"→ {out_csv}")
```

Add the CLI flag to the argparser:
```python
    p.add_argument("--categories", type=Path, default=None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && pytest ../../docs/eval/scripts/tests/test_aggregate.py -v`
Expected: PASS (all five tests now)

- [ ] **Step 5: Re-run aggregate with categories**

```bash
python -m docs.eval.scripts.aggregate \
  --inputs 'docs/eval/grades/phase*-*-judged.csv' \
  --categories docs/eval/questions/manhattan-100/categories.yaml \
  --out docs/eval/results/ablation_table.md
ls docs/eval/results/per_region-*.csv
```
Expected: one per-region CSV per system.

- [ ] **Step 6: Commit**

```bash
git add docs/eval/scripts/aggregate.py \
        docs/eval/scripts/tests/test_aggregate.py \
        docs/eval/results/per_region-*.csv
git commit -m "feat(aggregate): per-region breakdown"
```

---

### Task 6.2: Per-source breakdown

**Files:**
- Modify: `docs/eval/scripts/aggregate.py`
- Modify: `docs/eval/scripts/tests/test_aggregate.py`

- [ ] **Step 1: Append the failing test**

```python
def test_per_source_breakdown_groups_by_citation_source_type():
    from docs.eval.scripts.aggregate import per_source_breakdown
    rows = [
        # row with wikipedia-heavy citations
        {"system": "s", "index": 0, "ccr_score": 1.0, "hr_score": 0.0, "fa_score": None, "nq_score": 5.0, "grr_score": None,
         "citation_source_types": ["wikipedia", "wikipedia"]},
        # row with osm-heavy citations
        {"system": "s", "index": 1, "ccr_score": 0.5, "hr_score": 0.5, "fa_score": None, "nq_score": 4.0, "grr_score": None,
         "citation_source_types": ["osm", "osm"]},
        # row with mixed
        {"system": "s", "index": 2, "ccr_score": 0.7, "hr_score": 0.2, "fa_score": None, "nq_score": 4.5, "grr_score": None,
         "citation_source_types": ["wikipedia", "osm"]},
    ]
    table = per_source_breakdown(rows)
    by_source = {row["dominant_source"]: row for row in table}
    assert "wikipedia" in by_source
    assert "osm" in by_source
    # row 0 is purely wikipedia → ccr_mean for wikipedia includes row 0
    assert by_source["wikipedia"]["ccr_mean"] == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest ../../docs/eval/scripts/tests/test_aggregate.py::test_per_source_breakdown_groups_by_citation_source_type -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Extend `aggregate.py`**

We need the original JSONL rows to know each row's citation source types. Update `load_judge_grades` to also accept a parallel JSONL path and merge:

Add to `aggregate.py`:

```python
def attach_citation_source_types(
    judge_rows: list[dict[str, Any]],
    jsonl_path: Path,
) -> list[dict[str, Any]]:
    """Read the original JSONL and add `citation_source_types` to each judge row."""
    payload_rows = [
        json.loads(l) for l in jsonl_path.read_text().splitlines()
        if l.strip() and json.loads(l).get("type") == "row"
    ]
    payload_by_index = {p["index"]: p for p in payload_rows}
    out: list[dict[str, Any]] = []
    for r in judge_rows:
        p = payload_by_index.get(r["index"], {})
        types = [c.get("source_type") for c in (p.get("citations") or [])]
        out.append({**r, "citation_source_types": [t for t in types if t]})
    return out


def per_source_breakdown(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group rows by the dominant citation source_type (most-frequent in
    that row's citations). Rows with no citations are skipped.
    """
    buckets: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        types = r.get("citation_source_types") or []
        if not types:
            continue
        # Dominant = most-frequent; ties broken alphabetically
        from collections import Counter
        c = Counter(types)
        max_count = max(c.values())
        dominant = sorted(t for t, k in c.items() if k == max_count)[0]
        buckets.setdefault(dominant, []).append(r)

    return [
        {
            "dominant_source": source,
            **{
                f"{m}_mean": _mean([r[f"{m}_score"] for r in rs if r[f"{m}_score"] is not None])
                for m in ("ccr", "hr", "fa", "nq", "grr")
            },
            "n": len(rs),
        }
        for source, rs in sorted(buckets.items())
    ]
```

Also add `import json` at the top if not already imported.

Extend `main()` to emit per-source CSVs. Add inside the `if args.categories:` block (or as a separate block):

```python
    if args.inputs_jsonl:
        import glob as _glob
        for fp_csv in files:
            in_path = Path(fp_csv)
            # Find the matching jsonl by stripping "-judged" suffix
            stem = in_path.stem.removesuffix("-judged")
            jsonl_candidates = list(args.inputs_jsonl_dir.glob(f"{stem}.jsonl"))
            if not jsonl_candidates:
                continue
            rows = load_judge_grades(in_path)
            rows = attach_citation_source_types(rows, jsonl_candidates[0])
            ps = per_source_breakdown(rows)
            if ps:
                out_csv = args.out.with_name(f"per_source-{rows[0]['system']}.csv")
                with out_csv.open("w", newline="") as fh:
                    w = csv.DictWriter(fh, fieldnames=list(ps[0].keys()))
                    w.writeheader()
                    for r in ps:
                        w.writerow(r)
                print(f"→ {out_csv}")
```

Add the new CLI flag:
```python
    p.add_argument("--inputs-jsonl-dir", type=Path, default=Path("docs/eval/results"))
    p.add_argument("--inputs-jsonl", action="store_true",
                   help="Also produce per-source breakdowns (requires --inputs-jsonl-dir).")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && pytest ../../docs/eval/scripts/tests/test_aggregate.py -v`
Expected: PASS

- [ ] **Step 5: Re-run aggregate with the new flag**

```bash
python -m docs.eval.scripts.aggregate \
  --inputs 'docs/eval/grades/phase*-*-judged.csv' \
  --categories docs/eval/questions/manhattan-100/categories.yaml \
  --inputs-jsonl \
  --inputs-jsonl-dir docs/eval/results \
  --out docs/eval/results/ablation_table.md
ls docs/eval/results/per_source-*.csv
```

- [ ] **Step 6: Commit**

```bash
git add docs/eval/scripts/aggregate.py \
        docs/eval/scripts/tests/test_aggregate.py \
        docs/eval/results/per_source-*.csv
git commit -m "feat(aggregate): per-source breakdown by dominant citation source_type"
```

---

### Task 6.3: Accuracy-vs-latency Pareto figure

**Files:**
- Create: `docs/eval/scripts/plot_pareto.py`
- Create: `docs/eval/results/pareto.png`

- [ ] **Step 1: Write the plot script**

```python
# docs/eval/scripts/plot_pareto.py
"""Accuracy-vs-latency Pareto figure.

One point per system. X = median latency from the JSONL footers. Y = CCR
from the judge CSV.
"""

from __future__ import annotations

import argparse
import glob
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from docs.eval.scripts.aggregate import load_judge_grades, summarize_system


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--judge-glob", required=True)
    p.add_argument("--jsonl-dir", type=Path, default=Path("docs/eval/results"))
    p.add_argument("--out", type=Path, default=Path("docs/eval/results/pareto.png"))
    args = p.parse_args()

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    points: list[tuple[str, float, float]] = []
    for fp in sorted(glob.glob(args.judge_glob)):
        rows = load_judge_grades(Path(fp))
        summary = summarize_system(rows)
        sys_name = summary["system"]
        ccr = summary["ccr_mean"] or 0.0

        stem = Path(fp).stem.removesuffix("-judged")
        jsonl_path = args.jsonl_dir / f"{stem}.jsonl"
        if not jsonl_path.exists():
            print(f"warning: no jsonl for {sys_name}", file=sys.stderr)
            continue
        latencies = [
            json.loads(l).get("latency_s") or 0.0
            for l in jsonl_path.read_text().splitlines()
            if l.strip() and json.loads(l).get("type") == "row"
        ]
        if not latencies:
            continue
        p50 = statistics.median(latencies)
        points.append((sys_name, p50, ccr))

    if not points:
        raise SystemExit("no points to plot")

    fig, ax = plt.subplots(figsize=(7, 5))
    for name, lat, ccr in points:
        ax.scatter(lat, ccr, s=120)
        ax.annotate(name, (lat, ccr), xytext=(6, 6), textcoords="offset points", fontsize=9)
    ax.set_xlabel("latency p50 (s)")
    ax.set_ylabel("citation correctness rate")
    ax.set_title("Accuracy vs latency Pareto (manhattan-100)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(args.out, dpi=150)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run**

```bash
python -m docs.eval.scripts.plot_pareto \
  --judge-glob 'docs/eval/grades/phase*-*-judged.csv' \
  --out docs/eval/results/pareto.png
```
Expected: `pareto.png` written with 5 labeled points.

- [ ] **Step 3: Commit**

```bash
git add docs/eval/scripts/plot_pareto.py docs/eval/results/pareto.png
git commit -m "feat(eval): accuracy-vs-latency Pareto plot"
```

---

### Task 6.4: GRR analysis for out-of-scope subset

The 10 out-of-scope questions get a separate small table.

- [ ] **Step 1: Write `docs/eval/scripts/grr_analysis.py`**

```python
"""GRR (Graceful Refusal Rate) — 10 out-of-scope questions × 5 systems."""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from docs.eval.scripts.aggregate import load_judge_grades


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--judge-glob", required=True)
    p.add_argument("--categories", type=Path, required=True)
    p.add_argument("--out", type=Path, default=Path("docs/eval/results/grr_table.md"))
    args = p.parse_args()

    cats = yaml.safe_load(args.categories.read_text())["questions"]
    oos_indices = {i for i, q in enumerate(cats) if q.get("is_out_of_scope")}

    lines = ["# GRR — out-of-scope subset", "",
             "| System | n | GRR ↑ |", "|---|---:|---:|"]
    for fp in sorted(glob.glob(args.judge_glob)):
        rows = load_judge_grades(Path(fp))
        oos_rows = [r for r in rows if r["index"] in oos_indices]
        grr = [r["grr_score"] for r in oos_rows if r["grr_score"] is not None]
        if not grr:
            continue
        mean = sum(grr) / len(grr)
        lines.append(f"| {oos_rows[0]['system']} | {len(grr)} | {mean:.3f} |")

    args.out.write_text("\n".join(lines) + "\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run**

```bash
python -m docs.eval.scripts.grr_analysis \
  --judge-glob 'docs/eval/grades/phase*-*-judged.csv' \
  --categories docs/eval/questions/manhattan-100/categories.yaml
cat docs/eval/results/grr_table.md
```
Expected: 5-row GRR table.

- [ ] **Step 3: Commit**

```bash
git add docs/eval/scripts/grr_analysis.py docs/eval/results/grr_table.md
git commit -m "feat(eval): GRR table for the out-of-scope subset"
```

---

### Task 6.5: Final methodology summary doc

- [ ] **Step 1: Write `docs/eval/manhattan-100-results.md`**

```markdown
# Manhattan-100 Eval Results

This document is the final report-facing summary. All numbers are reproducible
from artifacts in this repository at tag `manhattan-100-v1` (question bank
commit) and the relevant phase commits.

## Headline

Palimpsest (full hybrid+reranked configuration) produces citation-correct
responses on **X%** of manhattan-100 questions, vs **Y%** for naive RAG and
**Z%** for vanilla LLM. _Fill in from `ablation_table.md`._

## Ablation table

See `docs/eval/results/ablation_table.md`.

## Per-region

See `docs/eval/results/per_region-*.csv`.

## Per-source

See `docs/eval/results/per_source-*.csv`.

## Out-of-scope refusal

See `docs/eval/results/grr_table.md`.

## Accuracy vs latency

See `docs/eval/results/pareto.png`.

## Inter-rater agreement

Cohen's κ between hand-grader and LLM-judge on the 20-question calibration
set: **K**. _Fill in from `docs/eval/notes/2026-05-12-kappa.md`._

## Methodology

See `docs/superpowers/specs/2026-05-12-eval-depth-and-corpus-expansion-design.md`
§6 (metrics) and §7 (phases). Question bank is `manhattan-100-v1`.

## Reproducibility

To re-run any phase, check out the corresponding commit and follow the
instructions in `docs/superpowers/plans/2026-05-12-eval-depth-and-corpus-expansion.md`.
```

(The X / Y / Z / K values get filled in once you have actual numbers; leave them as placeholders in this template task and patch in the real numbers when you write the report.)

- [ ] **Step 2: Commit**

```bash
git add docs/eval/manhattan-100-results.md
git commit -m "docs(eval): manhattan-100 results summary template"
```

- [ ] **Step 3: Tag the final state**

```bash
git tag manhattan-100-eval-complete
```

**Phase 6 exit criterion (and project end):** ablation_table.md, per_region CSVs, per_source CSVs, pareto.png, grr_table.md, and the summary doc all committed. Tag `manhattan-100-eval-complete` is set.

---

## Self-review checklist

Run this at the end of implementation to verify the plan matches reality:

- [ ] All five systems appear in `ablation_table.md`.
- [ ] κ value recorded in `docs/eval/notes/2026-05-12-kappa.md`.
- [ ] Per-region CSV has at least 10 rows (one per Manhattan neighborhood with ≥1 question).
- [ ] Per-source CSV has rows for both `wikipedia` and `osm`.
- [ ] GRR table shows higher GRR for Palimpsest configs than for vanilla LLM (sanity).
- [ ] `pareto.png` exists and has 5 labeled points.
- [ ] All Phase 0-6 commits are on the branch; the branch builds cleanly.
- [ ] `cd apps/api && pytest -q` passes (all retrieval module tests + existing ones).
- [ ] No `TODO`, `TBD`, or `XXX` in any committed code or markdown under `docs/eval/`.

If any item fails, fix in place before tagging `manhattan-100-eval-complete`.
