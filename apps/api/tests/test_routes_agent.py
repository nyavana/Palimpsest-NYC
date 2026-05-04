"""SSE /agent/ask route tests.

Drive the route with a fake AgentLoop so the suite needs neither a live LLM
nor a live database. Verifies SSE framing and event ordering against the
locked V1 contract (post `agent-route-planning` Wave 4 amendment):

  - `walk` SSE frame is emitted only when `AgentResult.walk` is populated
    (i.e. the agent itself called `plan_walk`); informational queries with
    `walk=None` skip straight from `citations` to `done`.
  - `routing_backend` is plumbed into the per-request `ToolExecutionContext`.
  - SessionRecord is appended at end-of-conversation with the new
    `walk_intent_hint`, `plan_walk_called`, `routing_backend`, and
    `stop_ordering` fields populated from the AgentResult.
"""

from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Any

import pytest
from app.agent.citations import Citation
from app.agent.loop import AgentEvent, AgentResult
from app.agent.tools.base import ToolExecutionContext
from app.meta.session_log import SessionLogger
from app.routes.agent import router as agent_router
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── Helpers ─────────────────────────────────────────────────────────


def _result(
    *,
    verified: bool = True,
    walk: dict | None = None,
    walk_intent_hint: str = "neutral",
) -> AgentResult:
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
        walk=walk,
        walk_intent_hint=walk_intent_hint,  # type: ignore[arg-type]
    )


def _walk_payload() -> dict[str, Any]:
    """A minimal but realistic plan_walk tool result with GeoJSON geometry."""
    return {
        "stops": [
            {
                "index": 0,
                "doc_id": "wikipedia:X",
                "name": "X Place",
                "lat": 40.804,
                "lon": -73.962,
            },
            {
                "index": 1,
                "doc_id": "wikipedia:Y",
                "name": "Y Place",
                "lat": 40.811,
                "lon": -73.964,
            },
        ],
        "legs": [
            {
                "from_index": 0,
                "to_index": 1,
                "distance_m": 412,
                "duration_s": 295,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-73.962, 40.804], [-73.964, 40.811]],
                },
                "steps": [
                    {
                        "instruction": "Head east on West 110th Street for 80 m",
                        "distance_m": 80,
                        "duration_s": 60,
                        "maneuver_type": "depart",
                    }
                ],
            }
        ],
        "geometry": {
            "type": "LineString",
            "coordinates": [[-73.962, 40.804], [-73.964, 40.811]],
        },
        "total_distance_m": 412,
        "total_duration_s": 295,
        "routing_backend": "osrm",
        "stop_ordering": "input_order",
    }


class _FakeAgentLoop:
    """Yields a scripted event stream and stashes a final AgentResult."""

    last_context: ToolExecutionContext | None = None

    def __init__(self, events: list[AgentEvent]) -> None:
        self._events = events

    async def run_streamed(self, query: str, *, context: Any):
        # Capture the per-request context so tests can assert what the
        # SSE handler wired in (routing_backend in particular).
        type(self).last_context = context
        for ev in self._events:
            yield ev


class _FakeSessionCM:
    async def __aenter__(self) -> _FakeSessionCM:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def commit(self) -> None:
        pass

    async def close(self) -> None:
        pass


def _build_app(
    events: list[AgentEvent],
    *,
    routing_backend: Any = None,
    session_logger: SessionLogger | None = None,
) -> FastAPI:
    app = FastAPI()
    app.state.db_session_factory = _FakeSessionCM  # callable → returns CM
    app.state.embedder = object()
    app.state.routing_backend = routing_backend
    if session_logger is not None:
        app.state.session_logger = session_logger
    app.state.agent_loop_builder = lambda req: _FakeAgentLoop(events)
    app.include_router(agent_router)
    # Reset the captured context so cross-test leakage doesn't fool us.
    _FakeAgentLoop.last_context = None
    return app


# ── SSE response shape ──────────────────────────────────────────────


def test_sse_route_returns_text_event_stream():
    events = [
        AgentEvent("turn", {"turn": 1}),
        AgentEvent("done", {"result": _result()}),
    ]
    app = _build_app(events)
    with TestClient(app) as client, client.stream("GET", "/agent/ask?q=hi") as resp:
        assert resp.status_code == 200
        ct = resp.headers["content-type"]
        assert ct.startswith("text/event-stream")
        assert resp.headers.get("cache-control") == "no-cache"


def test_sse_frame_format_event_and_data():
    """Each event MUST be `event: <type>\\ndata: <json>\\n\\n`."""
    events = [
        AgentEvent("turn", {"turn": 1}),
        AgentEvent("done", {"result": _result()}),
    ]
    app = _build_app(events)
    with TestClient(app) as client, client.stream("GET", "/agent/ask?q=hi") as resp:
        body = b"".join(resp.iter_bytes())
    text = body.decode("utf-8")
    frames = [f for f in text.split("\n\n") if f.strip()]
    for f in frames:
        assert f.startswith("event: ")
        assert "\ndata: " in f


# ── Wave 4: conditional walk frame ──────────────────────────────────


def test_no_walk_frame_when_agent_did_not_call_plan_walk():
    """§7.1/§7.2: when AgentResult.walk is None, NO walk frame is emitted —
    the SSE stream goes straight from citations to done."""
    events = [
        AgentEvent("turn", {"turn": 1}),
        AgentEvent("done", {"result": _result(walk=None, walk_intent_hint="negative")}),
    ]
    app = _build_app(events)
    with (
        TestClient(app) as client,
        client.stream("GET", "/agent/ask?q=tell+me+about+X") as resp,
    ):
        body = b"".join(resp.iter_bytes()).decode("utf-8")
    assert "event: walk" not in body
    assert "event: done" in body


def test_walk_frame_emitted_when_agent_result_walk_is_populated():
    """§7.2/§7.3: when AgentResult.walk is a populated dict, the walk frame
    contains the dict's contents verbatim, with GeoJSON geometry as plain
    JSON objects (not nested dataclass shells)."""
    walk = _walk_payload()
    events = [
        AgentEvent("turn", {"turn": 1}),
        AgentEvent(
            "done",
            {"result": _result(walk=walk, walk_intent_hint="positive")},
        ),
    ]
    app = _build_app(events)
    with TestClient(app) as client, client.stream("GET", "/agent/ask?q=plan+a+walk") as resp:
        body = b"".join(resp.iter_bytes()).decode("utf-8")

    # walk frame appears, before the terminal done
    assert "event: walk" in body
    walk_idx = body.index("event: walk")
    done_idx = body.rindex("event: done")
    assert walk_idx < done_idx

    # Pluck the walk frame's data: line and parse it as JSON
    walk_segment = body[walk_idx:done_idx]
    data_line = next(
        line for line in walk_segment.splitlines() if line.startswith("data: ")
    )
    walk_json = _json.loads(data_line.removeprefix("data: "))

    # Stops/legs/geometry/totals all round-trip
    assert walk_json["stops"][0]["doc_id"] == "wikipedia:X"
    assert walk_json["routing_backend"] == "osrm"
    assert walk_json["stop_ordering"] == "input_order"
    assert walk_json["total_distance_m"] == 412
    # GeoJSON geometry is a plain JSON object, not a dataclass shell
    assert walk_json["geometry"] == {
        "type": "LineString",
        "coordinates": [[-73.962, 40.804], [-73.964, 40.811]],
    }
    assert walk_json["legs"][0]["geometry"]["type"] == "LineString"
    assert isinstance(walk_json["legs"][0]["geometry"]["coordinates"], list)


# ── Wave 4: routing_backend wired into ToolExecutionContext ─────────


def test_routing_backend_is_wired_into_tool_execution_context():
    """§6.5: the per-request ToolExecutionContext receives
    app.state.routing_backend."""
    sentinel_backend = object()
    events = [
        AgentEvent("done", {"result": _result()}),
    ]
    app = _build_app(events, routing_backend=sentinel_backend)
    with TestClient(app) as client, client.stream("GET", "/agent/ask?q=hi") as resp:
        # Drain the stream so the loop runs end-to-end
        b"".join(resp.iter_bytes())
    ctx = _FakeAgentLoop.last_context
    assert ctx is not None
    assert ctx.routing_backend is sentinel_backend


def test_routing_backend_defaults_to_none_when_app_state_missing():
    """If `app.state.routing_backend` is absent, the context's
    routing_backend is None — the plan_walk tool then fails loudly per
    its own contract (this route does not check)."""
    events = [
        AgentEvent("done", {"result": _result()}),
    ]
    # Build the app without setting routing_backend on app.state.
    app = FastAPI()
    app.state.db_session_factory = _FakeSessionCM
    app.state.embedder = object()
    app.state.agent_loop_builder = lambda req: _FakeAgentLoop(events)
    app.include_router(agent_router)
    _FakeAgentLoop.last_context = None
    with TestClient(app) as client, client.stream("GET", "/agent/ask?q=hi") as resp:
        b"".join(resp.iter_bytes())
    ctx = _FakeAgentLoop.last_context
    assert ctx is not None
    assert ctx.routing_backend is None


# ── Wave 4: SessionRecord population ────────────────────────────────


def test_session_record_records_positive_walk(tmp_path: Path):
    """§9.2: a positive-hint conversation with a populated walk produces
    a SessionRecord with plan_walk_called=True, the correct backend tag,
    stop_ordering, and walk_intent_hint='positive'."""
    walk = _walk_payload()
    events = [
        AgentEvent(
            "done",
            {"result": _result(walk=walk, walk_intent_hint="positive")},
        ),
    ]
    logger = SessionLogger(log_dir=str(tmp_path))
    app = _build_app(events, session_logger=logger)
    with TestClient(app) as client, client.stream("GET", "/agent/ask?q=plan+a+walk") as resp:
        b"".join(resp.iter_bytes())

    records = logger.iter_records()
    assert len(records) == 1
    rec = records[0]
    assert rec.plan_walk_called is True
    assert rec.routing_backend == "osrm"
    assert rec.stop_ordering == "input_order"
    assert rec.walk_intent_hint == "positive"
    assert rec.outcome == "success"


def test_session_record_records_negative_no_walk(tmp_path: Path):
    """§9.2: a negative-hint conversation with no walk produces a
    SessionRecord with plan_walk_called=False and routing_backend/
    stop_ordering=None."""
    events = [
        AgentEvent(
            "done",
            {"result": _result(walk=None, walk_intent_hint="negative")},
        ),
    ]
    logger = SessionLogger(log_dir=str(tmp_path))
    app = _build_app(events, session_logger=logger)
    with (
        TestClient(app) as client,
        client.stream("GET", "/agent/ask?q=tell+me+about+X") as resp,
    ):
        b"".join(resp.iter_bytes())

    records = logger.iter_records()
    assert len(records) == 1
    rec = records[0]
    assert rec.plan_walk_called is False
    assert rec.routing_backend is None
    assert rec.stop_ordering is None
    assert rec.walk_intent_hint == "negative"


def test_session_record_failure_when_no_terminal_result(tmp_path: Path):
    """When the loop produces no terminal `done` event, the session is
    recorded as a failure with default neutral hint and no walk."""
    events = [AgentEvent("turn", {"turn": 1})]  # no `done`
    logger = SessionLogger(log_dir=str(tmp_path))
    app = _build_app(events, session_logger=logger)
    with TestClient(app) as client, client.stream("GET", "/agent/ask?q=hi") as resp:
        b"".join(resp.iter_bytes())
    records = logger.iter_records()
    assert len(records) == 1
    rec = records[0]
    assert rec.outcome == "failure"
    assert rec.plan_walk_called is False
    assert rec.routing_backend is None
    assert rec.stop_ordering is None
    assert rec.walk_intent_hint == "neutral"


# ── Backwards-compat / error paths ──────────────────────────────────


def test_unverified_result_emits_warning_before_done():
    events = [
        AgentEvent("warning", {"message": "citation invalid"}),
        AgentEvent("done", {"result": _result(verified=False)}),
    ]
    app = _build_app(events)
    with TestClient(app) as client, client.stream("GET", "/agent/ask?q=hi") as resp:
        body = b"".join(resp.iter_bytes()).decode("utf-8")
    assert "event: warning" in body
    assert "event: done" in body


def test_missing_query_returns_400():
    app = _build_app([])
    with TestClient(app) as client:
        resp = client.get("/agent/ask")
    assert resp.status_code in (400, 422)


# Silence unused-import warnings if pytest plugins reorder collection
_ = pytest
