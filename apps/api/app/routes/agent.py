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

SSE framing: `event: <type>\\ndata: <json>\\n\\n`. Browsers consume this
via fetch + ReadableStream (frontend) or a third-party SSE client. The
route also sets `X-Accel-Buffering: no` so any reverse proxy that
respects it (nginx included) flushes events immediately rather than
batching them.

BYOK transport (V1.1):
  - The endpoint is POST. The user question lives in the JSON body.
  - An optional `X-LLM-Credentials` request header, base64-encoded JSON
    of `{api_key, model, base_url?}`, drives a per-request LLMRouter so
    the user pays for their own LLM calls without the key ever appearing
    in URLs, query strings, or access logs.
  - When the server has no `OPENROUTER_API_KEY` configured (BYOK mode),
    requests without the header receive 400 `byok_required`.
"""

from __future__ import annotations

import base64
import binascii
import dataclasses
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.loop import AgentEvent, AgentLoopError, AgentResult
from app.agent.tools.base import ToolExecutionContext
from app.llm.router import LLMRouter, build_byok_router
from app.llm.models import Message
from app.meta.session_log import SessionRecord

router = APIRouter()

SSE_HEADERS = {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # disable nginx buffering for live streaming
}

# Header name (case-insensitive on the wire). Carries base64(JSON({api_key, model, base_url?})).
CREDENTIALS_HEADER = "X-LLM-Credentials"


# ── Request models ──────────────────────────────────────────────────


class AskBody(BaseModel):
    """JSON body of POST /agent/ask."""

    model_config = ConfigDict(extra="forbid")

    q: str = Field(..., min_length=1, description="User question")
    history: list["ConversationHistoryMessage"] = Field(
        default_factory=list,
        description="Prior user/assistant turns to preserve multi-turn context.",
    )


class ConversationHistoryMessage(BaseModel):
    """Client-supplied prior conversation context.

    Intentionally narrower than `app.llm.models.Message`: callers may only send
    plain user/assistant text turns. Tool/system messages stay server-owned.
    """

    model_config = ConfigDict(extra="forbid")

    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1)


AskBody.model_rebuild()


class UserCredentials(BaseModel):
    """Per-request LLM credentials decoded from X-LLM-Credentials.

    Held only for the lifetime of one request — no logging, no storage,
    no inclusion in telemetry tags. Future schema additions MUST NOT add
    fields that capture session state across requests.
    """

    model_config = ConfigDict(extra="forbid")

    api_key: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    base_url: str = Field(default="https://openrouter.ai/api/v1", min_length=1)


def _decode_credentials_header(raw: str | None) -> UserCredentials | None:
    """Decode the X-LLM-Credentials header.

    Returns None when the header is absent. Raises HTTPException(400) on
    a malformed header so misconfigured clients fail fast and don't silently
    fall back to the server key.
    """
    if raw is None:
        return None
    try:
        decoded = base64.b64decode(raw, validate=True).decode("utf-8")
        payload = json.loads(decoded)
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_credentials_header", "reason": str(exc)},
        ) from exc
    try:
        return UserCredentials.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_credentials_payload", "reason": exc.errors()},
        ) from exc


def _resolve_router(request: Request, creds: UserCredentials | None) -> tuple[LLMRouter, bool]:
    """Pick the router for this request and report whether it was built per-request.

    Returns (router, owns_router): owns_router=True means the caller must
    `await router.aclose()` once the stream finishes.
    """
    app = request.app
    singleton: LLMRouter | None = getattr(app.state, "llm_router", None)
    byok_required: bool = getattr(app.state, "byok_required", False)

    if creds is not None:
        settings = app.state.settings
        timeout_s = float(settings.openrouter.timeout_s)
        if singleton is not None:
            return (
                singleton.with_user_credentials(
                    api_key=creds.api_key,
                    model=creds.model,
                    base_url=creds.base_url,
                    timeout_s=timeout_s,
                ),
                True,
            )
        # BYOK-required mode: build a router from scratch using the shared
        # telemetry sink stashed on app.state by the lifespan.
        return (
            build_byok_router(
                api_key=creds.api_key,
                model=creds.model,
                base_url=creds.base_url,
                timeout_s=timeout_s,
                telemetry=app.state.llm_telemetry,
                cb_fail_threshold=settings.llm_router.cb_fail_threshold,
                cb_window_s=settings.llm_router.cb_window_s,
                cb_cooldown_s=settings.llm_router.cb_cooldown_s,
            ),
            True,
        )

    if byok_required:
        raise HTTPException(
            status_code=400,
            detail={"error": "byok_required", "header": CREDENTIALS_HEADER},
        )
    if singleton is None:
        # Defensive — shouldn't be reachable when byok_required is False.
        raise HTTPException(status_code=503, detail="llm_router_not_initialized")
    return singleton, False


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


@router.post("/agent/ask", tags=["agent"])
async def agent_ask(
    request: Request,
    body: AskBody,
    x_llm_credentials: str | None = Header(default=None, alias=CREDENTIALS_HEADER),
) -> StreamingResponse:
    q = body.q.strip()
    if not q:
        raise HTTPException(status_code=400, detail="empty query")
    history = [
        Message(role=msg.role, content=msg.content)
        for msg in body.history
    ]
    # Decoding upfront so the 400 is sent before headers are flushed.
    creds = _decode_credentials_header(x_llm_credentials)
    router_instance, owns_router = _resolve_router(request, creds)

    return StreamingResponse(
        _stream(
            request,
            q,
            history=history,
            router_instance=router_instance,
            owns_router=owns_router,
            byok=creds is not None,
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


async def _stream(
    request: Request,
    q: str,
    *,
    history: list[Message],
    router_instance: LLMRouter,
    owns_router: bool,
    byok: bool,
) -> AsyncIterator[bytes]:
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

    try:
        async with session_factory() as session:
            context = ToolExecutionContext(
                session=session,
                embedder=embedder,
                routing_backend=routing_backend,
            )
            loop = loop_builder(request, router_instance)
            terminal_result: AgentResult | None = None

            try:
                async for ev in loop.run_streamed(q, context=context, history_messages=history):
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
                    byok=byok,
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
                byok=byok,
            )
    finally:
        if owns_router:
            try:
                await router_instance.aclose()
            except Exception:  # noqa: BLE001 — best-effort cleanup
                pass


# ── Session telemetry ───────────────────────────────────────────────


def _record_session(
    *,
    session_logger: Any,
    started_at: datetime,
    query: str,
    result: AgentResult | None,
    byok: bool = False,
) -> None:
    """Append one SessionRecord per /agent/ask invocation.

    Per §9.2: `plan_walk_called`, `routing_backend`, and `stop_ordering`
    are derived from `result.walk`; `walk_intent_hint` is read from the
    AgentResult directly. Failures are swallowed — telemetry must never
    break the SSE response.

    SECURITY: future additions to SessionRecord MUST NOT include credentials,
    headers, or anything that could fingerprint a user's API key. The `byok`
    tag below is a boolean only.
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
            tags={"byok": "true"} if byok else {},
        )
        session_logger.append(record)
    except Exception:  # telemetry is best-effort; never break the SSE response
        return
