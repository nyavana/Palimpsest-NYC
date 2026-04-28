"""Server-Sent Events `/agent/ask` endpoint (V1 transport, locked).

Pipeline:
  1. Build an AgentLoop (router + tool registry + embedder + DB session).
  2. Stream the loop's `AgentEvent`s as SSE frames as they arrive.
  3. On the terminal `done` event, run the server-side `plan_walk` over
     the cited place_ids, emit a `walk` event, then re-emit `done` so
     the client has a single terminal marker.

SSE framing: `event: <type>\\ndata: <json>\\n\\n`. Native browser
`EventSource` parses this directly. The route also sets
`X-Accel-Buffering: no` so any reverse proxy that respects it (nginx
included) flushes events immediately rather than batching them.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.agent.loop import AgentEvent, AgentLoopError, AgentResult
from app.agent.tools.base import ToolExecutionContext
from app.agent.walk import plan_walk

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

    async with session_factory() as session:
        context = ToolExecutionContext(session=session, embedder=embedder)
        loop = loop_builder(request)
        terminal_result: AgentResult | None = None

        try:
            async for ev in loop.run_streamed(q, context=context):
                if ev.type == "done":
                    # Defer emitting `done` until after we plan the walk so
                    # the client sees one terminal marker.
                    terminal_result = ev.payload["result"]
                    break
                yield _serialize_event(ev)
        except AgentLoopError as exc:
            # Turn-cap or empty-LLM-response — surface a graceful warning so
            # the client gets a terminal marker instead of a dropped connection.
            yield _frame("warning", {"message": str(exc)})

        if terminal_result is None:
            yield _frame("done", {"result": None})
            return

        place_ids = [c.doc_id for c in terminal_result.citations]
        try:
            stops = await plan_walk(session=session, place_ids=place_ids)
            yield _frame(
                "walk",
                {"stops": [dataclasses.asdict(s) for s in stops]},
            )
        except Exception as exc:  # noqa: BLE001
            # Walk planning is best-effort; failing it should not lose the
            # narration. Emit a warning and continue to `done`.
            yield _frame(
                "warning",
                {"message": f"plan_walk failed: {exc}"},
            )

        yield _serialize_event(AgentEvent("done", {"result": terminal_result}))
