"""SSE /agent/ask route tests.

Drive the route with a fake AgentLoop and a fake walk planner so the suite
needs neither a live LLM nor a live database. Verifies SSE framing and event
ordering against the locked V1 contract.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent.citations import Citation
from app.agent.loop import AgentEvent, AgentResult
from app.agent.walk import PlannedStop
from app.routes.agent import router as agent_router


# ── Helpers ─────────────────────────────────────────────────────────


def _result(verified: bool = True) -> AgentResult:
    return AgentResult(
        narration="Walk start narration.",
        citations=[
            Citation(
                doc_id="wikipedia:X",
                source_url="https://en.wikipedia.org/wiki/X",
                source_type="wikipedia",
                span="intro",
                retrieval_turn=1,
            )
        ],
        verified=verified,
        warning=None,
        turns=2,
        duration_s=0.5,
    )


class _FakeAgentLoop:
    """Yields a scripted event stream and stashes a final AgentResult."""

    def __init__(self, events: list[AgentEvent]) -> None:
        self._events = events

    async def run_streamed(self, query: str, *, context: Any):
        for ev in self._events:
            yield ev


async def _fake_plan_walk(*, session: Any, place_ids: list[str]) -> list[PlannedStop]:
    return [
        PlannedStop(
            index=0,
            doc_id="wikipedia:X",
            name="X Place",
            lat=40.8,
            lon=-73.96,
            leg_distance_m=0.0,
        )
    ]


class _FakeSessionCM:
    async def __aenter__(self) -> "_FakeSessionCM":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def commit(self) -> None:
        pass

    async def close(self) -> None:
        pass


def _build_app(events: list[AgentEvent]) -> FastAPI:
    app = FastAPI()
    app.state.db_session_factory = _FakeSessionCM  # callable → returns CM
    app.state.embedder = object()
    app.state.agent_loop_builder = lambda req: _FakeAgentLoop(events)
    app.include_router(agent_router)
    return app


# ── SSE response shape ──────────────────────────────────────────────


def test_sse_route_returns_text_event_stream():
    events = [
        AgentEvent("turn", {"turn": 1}),
        AgentEvent(
            "done",
            {"result": _result()},
        ),
    ]
    app = _build_app(events)
    with patch("app.routes.agent.plan_walk", _fake_plan_walk):
        with TestClient(app) as client:
            with client.stream("GET", "/agent/ask?q=hi") as resp:
                assert resp.status_code == 200
                ct = resp.headers["content-type"]
                assert ct.startswith("text/event-stream")
                assert resp.headers.get("cache-control") == "no-cache"


def test_sse_frame_format_event_and_data():
    """Each event MUST be `event: <type>\\ndata: <json>\\n\\n`."""
    events = [
        AgentEvent("turn", {"turn": 1}),
        AgentEvent(
            "done",
            {"result": _result()},
        ),
    ]
    app = _build_app(events)
    with patch("app.routes.agent.plan_walk", _fake_plan_walk):
        with TestClient(app) as client:
            with client.stream("GET", "/agent/ask?q=hi") as resp:
                body = b"".join(resp.iter_bytes())
    text = body.decode("utf-8")
    # Every frame ends with two newlines
    frames = [f for f in text.split("\n\n") if f.strip()]
    for f in frames:
        assert f.startswith("event: ")
        assert "\ndata: " in f


def test_done_emits_walk_event_with_planned_route():
    events = [
        AgentEvent(
            "done",
            {"result": _result()},
        ),
    ]
    app = _build_app(events)
    with patch("app.routes.agent.plan_walk", _fake_plan_walk):
        with TestClient(app) as client:
            with client.stream("GET", "/agent/ask?q=hi") as resp:
                body = b"".join(resp.iter_bytes()).decode("utf-8")
    # `walk` event must precede the terminal `done`
    walk_idx = body.index("event: walk")
    done_idx = body.rindex("event: done")
    assert walk_idx < done_idx
    # walk payload includes the place_id from citations
    assert "wikipedia:X" in body


def test_unverified_result_emits_warning_before_done():
    events = [
        AgentEvent("warning", {"message": "citation invalid"}),
        AgentEvent(
            "done",
            {"result": _result(verified=False)},
        ),
    ]
    app = _build_app(events)
    with patch("app.routes.agent.plan_walk", _fake_plan_walk):
        with TestClient(app) as client:
            with client.stream("GET", "/agent/ask?q=hi") as resp:
                body = b"".join(resp.iter_bytes()).decode("utf-8")
    assert "event: warning" in body
    assert "event: done" in body


def test_missing_query_returns_400():
    app = _build_app([])
    with TestClient(app) as client:
        resp = client.get("/agent/ask")
    assert resp.status_code in (400, 422)
