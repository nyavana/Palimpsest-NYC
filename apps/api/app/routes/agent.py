"""Server-Sent Events `/agent/ask` endpoint (V1 transport, locked).

Pipeline:
  1. Build an AgentLoop (router + tool registry + embedder + DB session +
     routing_backend wired into the per-request `ToolExecutionContext`).
  2. Stream the loop's `AgentEvent`s as SSE frames as they arrive.
  3. On the terminal `done` event, emit a `walk` frame ONLY when the agent
     loop captured a `plan_walk` tool result onto `AgentResult.walk`
     (post route-planning amendment); otherwise the stream goes straight
     from `citations` to `done`. Either way, append-write a SessionRecord
     to the meta-instrumentation log so the §13.4 hand-grading harness
     and 2x3 confusion matrix have the (`walk_intent_hint`,
     `plan_walk_called`) covariates per session.

SSE framing: `event: <type>\\ndata: <json>\\n\\n`. Native browser
`EventSource` parses this directly. The route also sets
`X-Accel-Buffering: no` so any reverse proxy that respects it (nginx
included) flushes events immediately rather than batching them.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.agent.loop import AgentEvent, AgentLoopError, AgentResult
from app.agent.tools.base import ToolExecutionContext
from app.meta.session_log import SessionRecord

router = APIRouter()

SSE_HEADERS = {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # disable nginx buffering for live streaming
}


def _frame(event_type: str, payload: dict[str, Any]) -> bytes:
    return (
        f"event: {event_type}\n"
        f"data: {json.dumps(payload, default=str)}\n\n"
    ).encode("utf-8")


def _serialize_event(ev: AgentEvent) -> bytes:
    """Convert an AgentEvent into an SSE frame, unwrapping dataclasses."""
    payload = ev.payload
    if "result" in payload and isinstance(payload["result"], AgentResult):
        result = payload["result"]
        payload = {
            "result": {
                "narration": result.narration,
                "citations": [dataclasses.asdict(c) for c in result.citations],
                "verified": result.verified,
                "warning": result.warning,
                "turns": result.turns,
                "duration_s": result.duration_s,
            }
        }
    return _frame(ev.type, payload)


@router.get("/agent/ask", tags=["agent"])
async def agent_ask(
    request: Request,
    q: str = Query(..., min_length=1, description="User question"),
) -> StreamingResponse:
    if not q.strip():
        raise HTTPException(status_code=400, detail="empty query")

    return StreamingResponse(
        _stream(request, q),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


async def _stream(request: Request, q: str) -> AsyncIterator[bytes]:
    app = request.app
    session_factory = app.state.db_session_factory
    embedder = app.state.embedder
    loop_builder = app.state.agent_loop_builder
    # Wave 4 (§6.5): plumb the process-wide routing backend through the
    # per-request ToolExecutionContext so the `plan_walk` tool can reach
    # OSRM. The retrieval_ledger is per-conversation and is wired into
    # the context by the agent loop itself before each tool dispatch
    # (see app/agent/loop.py::run_streamed) — we do NOT set it here.
    routing_backend = getattr(app.state, "routing_backend", None)
    session_logger = getattr(app.state, "session_logger", None)
    started_at = datetime.now(tz=UTC)

    async with session_factory() as session:
        context = ToolExecutionContext(
            session=session,
            embedder=embedder,
            routing_backend=routing_backend,
        )
        loop = loop_builder(request)
        terminal_result: AgentResult | None = None

        try:
            async for ev in loop.run_streamed(q, context=context):
                if ev.type == "done":
                    # Defer emitting `done` until after we relay the
                    # captured walk (if any) so the client sees one
                    # terminal marker.
                    terminal_result = ev.payload["result"]
                    break
                yield _serialize_event(ev)
        except AgentLoopError as exc:
            # Turn-cap or empty-LLM-response — surface a graceful warning so
            # the client gets a terminal marker instead of a dropped connection.
            yield _frame("warning", {"message": str(exc)})

        if terminal_result is None:
            yield _frame("done", {"result": None})
            _record_session(
                session_logger=session_logger,
                started_at=started_at,
                query=q,
                result=None,
            )
            return

        # §7.1/§7.2: server-side unconditional `plan_walk` over citations is
        # gone. Emit the `walk` frame only when the agent itself called
        # `plan_walk` and a result was captured onto AgentResult.walk.
        # §7.4: AgentResult.walk is already a plain dict mirroring the wire
        # shape (see app/agent/loop.py::PlannedRoute = dict[str, Any] and
        # the plan_walk tool's serialized output), so we frame it directly
        # rather than going through _serialize_event — that helper is
        # designed for AgentEvent payloads, not the walk dict.
        if terminal_result.walk is not None:
            yield _frame("walk", terminal_result.walk)

        yield _serialize_event(AgentEvent("done", {"result": terminal_result}))

        _record_session(
            session_logger=session_logger,
            started_at=started_at,
            query=q,
            result=terminal_result,
        )


# ── Session telemetry ───────────────────────────────────────────────


def _record_session(
    *,
    session_logger: Any,
    started_at: datetime,
    query: str,
    result: AgentResult | None,
) -> None:
    """Append one SessionRecord per /agent/ask invocation.

    Per §9.2: `plan_walk_called`, `routing_backend`, and `stop_ordering`
    are derived from `result.walk`; `walk_intent_hint` is read from the
    AgentResult directly. Failures are swallowed — telemetry must never
    break the SSE response.
    """
    if session_logger is None:
        return
    try:
        ended_at = datetime.now(tz=UTC)
        if result is None:
            outcome = "failure"
            walk_intent_hint = "neutral"
            plan_walk_called = False
            routing_backend_tag: str | None = None
            stop_ordering: str | None = None
        else:
            outcome = "success" if result.verified else "partial"
            walk_intent_hint = result.walk_intent_hint
            plan_walk_called = result.walk is not None
            routing_backend_tag = (
                result.walk.get("routing_backend") if result.walk else None
            )
            stop_ordering = (
                result.walk.get("stop_ordering") if result.walk else None
            )
        record = SessionRecord(
            session_id=f"agent-ask-{uuid.uuid4().hex[:12]}",
            started_at=started_at.isoformat(),
            ended_at=ended_at.isoformat(),
            goal=query,
            outcome=outcome,  # type: ignore[arg-type]
            plan_walk_called=plan_walk_called,
            routing_backend=routing_backend_tag,
            stop_ordering=stop_ordering,
            walk_intent_hint=walk_intent_hint,
        )
        session_logger.append(record)
    except Exception:  # telemetry is best-effort; never break the SSE response
        return
