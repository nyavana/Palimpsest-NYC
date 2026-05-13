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

pytestmark = pytest.mark.asyncio


class _FakeChatClient:
    """Stand-in for the OpenRouter chat client used by the baseline."""

    def __init__(self, *, response: dict[str, Any]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._response = response

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict],
        temperature: float,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "response_format": response_format,
            }
        )
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


async def test_vanilla_requests_json_object_response_format():
    """Baselines must pass response_format=json_object so OpenRouter constrains output."""
    fake = _FakeChatClient(
        response={
            "content": '{"narration": "n", "citations": []}',
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "cost_usd": 0.0,
        }
    )
    await run_vanilla(question="Q", model="m", chat_client=fake, temperature=0.0)
    assert fake.calls[0]["response_format"] == {"type": "json_object"}


async def test_vanilla_strips_fenced_json_block():
    """Phase-0 smoke run observed kimi wrapping its JSON in ```json ... ``` fences."""
    fenced = (
        "```json\n"
        '{"narration": "Fenced reply.", '
        '"citations": [{"doc_id": "wikipedia:Foo", '
        '"source_url": "https://en.wikipedia.org/wiki/Foo", '
        '"source_type": "wikipedia", "span": "x"}]}\n'
        "```"
    )
    fake = _FakeChatClient(
        response={
            "content": fenced,
            "prompt_tokens": 10,
            "completion_tokens": 10,
            "cost_usd": 0.0,
        }
    )
    row = await run_vanilla(question="Q", model="m", chat_client=fake, temperature=0.0)
    assert row["error"] is None
    assert row["narration"] == "Fenced reply."
    assert row["citations"][0]["doc_id"] == "wikipedia:Foo"


async def test_vanilla_strips_preamble_before_json():
    """A short preamble before the JSON object should not break parsing."""
    preamble = (
        "Here's the JSON you requested:\n"
        '{"narration": "Preamble reply.", "citations": []}'
    )
    fake = _FakeChatClient(
        response={"content": preamble, "prompt_tokens": 1, "completion_tokens": 1, "cost_usd": 0.0}
    )
    row = await run_vanilla(question="Q", model="m", chat_client=fake, temperature=0.0)
    assert row["error"] is None
    assert row["narration"] == "Preamble reply."


# --- naive_rag tests ---


class _FakeRetrieveClient:
    def __init__(self, *, results: list[dict]) -> None:
        self.calls: list[dict] = []
        self._results = results

    async def retrieve(self, *, query: str, top_k: int) -> list[dict]:
        self.calls.append({"query": query, "top_k": top_k})
        return self._results


async def test_naive_rag_row_shape_with_retrieval():
    from docs.eval.scripts.baselines.naive_rag import run_naive_rag

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
    # Phase-0 fix: baseline must pin response_format and the prompt forbids fences.
    assert chat.calls[0]["response_format"] == {"type": "json_object"}


async def test_naive_rag_strips_fenced_json_block():
    """Same fence-stripping fix as vanilla — observed in Phase 0 smoke."""
    from docs.eval.scripts.baselines.naive_rag import run_naive_rag

    retriever = _FakeRetrieveClient(
        results=[
            {
                "doc_id": "wikipedia:Cathedral",
                "name": "Cathedral",
                "source_type": "wikipedia",
                "source_url": "https://en.wikipedia.org/wiki/Cathedral",
                "lat": 40.8,
                "lon": -73.96,
                "score": 0.71,
            }
        ]
    )
    fenced = (
        "```json\n"
        '{"narration": "Fenced n.", '
        '"citations": [{"doc_id": "wikipedia:Cathedral", '
        '"source_url": "https://en.wikipedia.org/wiki/Cathedral", '
        '"source_type": "wikipedia", "span": "x"}]}\n'
        "```"
    )
    chat = _FakeChatClient(
        response={"content": fenced, "prompt_tokens": 1, "completion_tokens": 1, "cost_usd": 0.0}
    )
    row = await run_naive_rag(
        question="Q",
        model="m",
        chat_client=chat,
        retrieve_client=retriever,
        top_k=4,
        temperature=0.0,
    )
    assert row["error"] is None
    assert row["narration"] == "Fenced n."
    assert row["citations"][0]["doc_id"] == "wikipedia:Cathedral"


# --- palimpsest baseline tests ---

from docs.eval.scripts.baselines.palimpsest import (
    flatten_retrieved_docs,
    normalize_palimpsest_row,
    run_palimpsest,
)


def _tool_result_frame(name: str, result: dict) -> dict:
    return {"event": "tool_result", "data": {"name": name, "result": result}}


def test_flatten_retrieved_docs_pulls_search_places_and_walk_stops():
    frames = [
        {"event": "turn", "data": {"index": 0}},
        _tool_result_frame("search_places", {"results": [
            {"doc_id": "wikipedia:Cathedral", "name": "Cathedral",
             "source_type": "wikipedia", "source_url": "u1",
             "lat": 40.8, "lon": -73.96, "score": 0.71},
            {"doc_id": "wikipedia:Riverside", "name": "Riverside",
             "source_type": "wikipedia", "source_url": "u2",
             "lat": 40.81, "lon": -73.96, "score": 0.62},
        ]}),
        _tool_result_frame("plan_walk", {
            "stops": [{"doc_id": "wikipedia:Cathedral"}],
            "discovered_stops": [
                {"doc_id": "osm:way/123", "name": "Park",
                 "source_type": "osm", "source_url": "u3",
                 "lat": 40.81, "lon": -73.95, "score": 0.4},
            ],
        }),
        _tool_result_frame("search_places", {"results": [
            # Duplicate of an earlier doc_id should be deduped (keep first hit).
            {"doc_id": "wikipedia:Cathedral", "name": "Cathedral",
             "source_type": "wikipedia", "source_url": "u1",
             "lat": 40.8, "lon": -73.96, "score": 0.85},
        ]}),
    ]
    docs = flatten_retrieved_docs(frames)
    assert [d["doc_id"] for d in docs] == [
        "wikipedia:Cathedral", "wikipedia:Riverside", "osm:way/123",
    ]
    # First-seen score should be preserved (0.71, not 0.85).
    assert docs[0]["score"] == 0.71


def test_normalize_palimpsest_row_carries_retrieved_docs():
    frames = [
        _tool_result_frame("search_places", {"results": [
            {"doc_id": "wikipedia:Cathedral", "name": "Cathedral",
             "source_type": "wikipedia", "source_url": "u",
             "lat": 40.8, "lon": -73.96, "score": 0.71},
        ]}),
        {"event": "citations", "data": {"citations": []}},
        {"event": "done", "data": {"result": {
            "narration": "Some narration.",
            "citations": [{"doc_id": "wikipedia:Cathedral", "source_url": "u",
                           "source_type": "wikipedia", "span": "x",
                           "retrieval_turn": 1}],
            "verified": True, "turns": 2, "duration_s": 9.4,
        }}},
    ]
    row = normalize_palimpsest_row(
        frames=frames, question="Q?", client_latency_s=12.5,
        system_name="palimpsest-dense", retrieval_mode="dense",
        body_excerpts={"wikipedia:Cathedral": "The Cathedral of Saint John…"},
        error=None,
    )
    assert row["system"] == "palimpsest-dense"
    assert row["retrieval_mode"] == "dense"
    assert row["narration"] == "Some narration."
    assert row["citations"][0]["doc_id"] == "wikipedia:Cathedral"
    assert row["latency_s"] == 12.5
    assert row["turns"] == 2
    assert row["verified"] is True
    assert row["error"] is None
    # Retrieved-doc flattening + enrichment:
    assert len(row["retrieved_docs"]) == 1
    assert row["retrieved_docs"][0]["doc_id"] == "wikipedia:Cathedral"
    assert row["retrieved_docs"][0]["body_excerpt"].startswith("The Cathedral")


async def test_run_palimpsest_drives_sse_and_enriches(monkeypatch):
    frames_in = [
        {"event": "turn", "data": {"index": 0}},
        _tool_result_frame("search_places", {"results": [
            {"doc_id": "wikipedia:Cathedral", "name": "Cathedral",
             "source_type": "wikipedia", "source_url": "u",
             "lat": 40.8, "lon": -73.96, "score": 0.71},
        ]}),
        {"event": "done", "data": {"result": {
            "narration": "n", "citations": [], "verified": True,
            "turns": 1, "duration_s": 0.5,
        }}},
    ]

    async def fake_stream(client, *, question, history=None, **_):
        for fr in frames_in:
            yield fr

    class _FakeDocClient:
        async def by_ids(self, doc_ids):
            return {d: f"body of {d}" for d in doc_ids}

    monkeypatch.setattr(
        "docs.eval.scripts.baselines.palimpsest.stream_agent_ask", fake_stream
    )

    row = await run_palimpsest(
        question="Q?", api_http_client=object(),
        doc_client=_FakeDocClient(),
        system_name="palimpsest-dense", retrieval_mode="dense",
    )
    assert row["narration"] == "n"
    assert row["retrieved_docs"][0]["body_excerpt"] == "body of wikipedia:Cathedral"
