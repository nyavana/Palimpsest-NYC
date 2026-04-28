"""Agent loop — single-tool surface, citation-verified, SSE-friendly events.

V1 contract (locked):
  - Exactly one tool registered (`search_places`); other tool calls return
    an `UnknownToolError` message back to the LLM and the loop continues.
  - Turn cap = 6. Hitting the cap is a hard failure.
  - Terminal response is JSON `{narration, citations[]}`. The citation
    verifier rejects responses that violate the contract; the loop retries
    once with a corrective system message, and if the retry also fails the
    response is returned with `verified=False` and a `warning`.
  - The loop also exposes `run_streamed()` which yields `AgentEvent` objects
    suitable for the SSE handler — one event per turn, tool result,
    narration, citation set, and a final `done` marker.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from app.agent.citations import (
    Citation,
    CitationError,
    NarrationResponse,
    RetrievalLedger,
    parse_narration_response,
    verify_citations,
)
from app.agent.tools.base import (
    Tool,
    ToolArgError,
    ToolExecutionContext,
    ToolRegistry,
    UnknownToolError,
)
from app.llm.models import ChatRequest, ChatResponse, Message, ToolCall

MAX_TURNS_DEFAULT = 6
COMPLEXITY_DEFAULT = "complex"


class AgentLoopError(RuntimeError):
    """Catastrophic failure — turn cap hit, or the LLM returned no content
    AND no tool call so the conversation cannot make progress."""


# ── Router protocol ─────────────────────────────────────────────────


class _RouterLike(Protocol):
    async def chat(self, req: ChatRequest) -> ChatResponse: ...


# ── Events ──────────────────────────────────────────────────────────


@dataclass(slots=True)
class AgentEvent:
    type: Literal[
        "turn", "tool_call", "tool_result", "tool_error",
        "narration", "citations", "warning", "done",
    ]
    payload: dict[str, Any]


# ── Result ──────────────────────────────────────────────────────────


@dataclass(slots=True)
class AgentResult:
    narration: str
    citations: list[Citation]
    verified: bool
    warning: str | None
    turns: int
    duration_s: float
    ledger: RetrievalLedger = field(default_factory=RetrievalLedger)


# ── System prompt ───────────────────────────────────────────────────


_SYSTEM_PROMPT = """\
You are Palimpsest NYC's walking-tour agent for Morningside Heights and the Upper West Side of Manhattan.

You have ONE tool: `search_places`. You SHOULD call it 1-3 times to gather places, then COMMIT to your final answer.

You have a hard budget of 6 turns. Plan to finalize by turn 4 at the latest. Excessive searching wastes the user's time.

When you have enough information (typically after 1-3 search calls), return your FINAL answer as a strict JSON object with exactly two fields:
  - "narration": a concise (4-8 sentences) walking-tour description.
  - "citations": a non-empty array of citation objects.

Each citation MUST have all five fields:
  - "doc_id" (string) — copied verbatim from a search_places result.
  - "source_url" (string) — copied verbatim from the same result.
  - "source_type" (string) — copied verbatim ("wikipedia", "wikidata", or "osm").
  - "span" (string) — short free-form annotation (e.g. "intro", "first sentence", "").
  - "retrieval_turn" (integer) — the 1-based turn on which search_places returned this doc.

Rules:
  - You MUST call search_places at least once before producing the final JSON.
  - Every citation MUST reference a doc_id that was actually returned by search_places earlier in this conversation.
  - Output ONLY the JSON object as your final response — no prose, no markdown fences.
  - Do NOT cite a doc_id you did not retrieve, and do NOT invent doc_ids.
  - If your first 1-2 searches returned good results, STOP searching and emit the final JSON.
"""


# ── Loop ────────────────────────────────────────────────────────────


class AgentLoop:
    """Drives the conversation, dispatches tool calls, verifies citations."""

    def __init__(
        self,
        *,
        router: _RouterLike,
        registry: ToolRegistry,
        max_turns: int = MAX_TURNS_DEFAULT,
        complexity: str = COMPLEXITY_DEFAULT,
    ) -> None:
        self._router = router
        self._registry = registry
        self._max_turns = max_turns
        self._complexity = complexity  # type: ignore[assignment]

    async def run(
        self, user_query: str, *, context: ToolExecutionContext
    ) -> AgentResult:
        events: list[AgentEvent] = []
        async for ev in self.run_streamed(user_query, context=context):
            events.append(ev)
        # The terminal `done` event carries the final result payload.
        done = events[-1]
        if done.type != "done":
            raise AgentLoopError("loop ended without a `done` event")
        return done.payload["result"]

    async def run_streamed(
        self, user_query: str, *, context: ToolExecutionContext
    ) -> AsyncIterator[AgentEvent]:
        t0 = time.perf_counter()
        ledger = RetrievalLedger()
        messages: list[Message] = [
            Message(role="system", content=_SYSTEM_PROMPT),
            Message(role="user", content=user_query),
        ]
        tools = self._registry.definitions()

        verify_attempts_remaining = 1  # one retry on bad citations
        retry_pending = False
        turn = 0
        while turn < self._max_turns or retry_pending:
            turn += 1
            retry_pending = False
            yield AgentEvent("turn", {"turn": turn})

            # On the final turn, strip the tool surface so the LLM is forced
            # to emit content. Some thinking models otherwise loop forever on
            # tool calls. (The verification-retry path already adds its own
            # corrective user message, so we don't double up.)
            is_final_turn = turn >= self._max_turns
            turn_messages = list(messages)
            already_has_user_directive = (
                turn_messages and turn_messages[-1].role == "user"
                and turn_messages[-1].content != user_query
            )
            if is_final_turn and not already_has_user_directive:
                turn_messages.append(
                    Message(
                        role="user",
                        content=(
                            "Stop searching. Using ONLY the search_places "
                            "results already in this conversation, emit the "
                            "final JSON object now with `narration` and "
                            "`citations`. Do not call any tool."
                        ),
                    )
                )

            response = await self._router.chat(
                ChatRequest(
                    messages=turn_messages,
                    complexity=self._complexity,  # type: ignore[arg-type]
                    tools=None if is_final_turn else tools,
                    # On the final turn the tool surface is gone, so
                    # response_format=json can't trick the model into
                    # short-circuiting a tool call — it just constrains the
                    # final content to valid JSON.
                    response_format="json" if is_final_turn else None,
                    # The final turn needs extra headroom because kimi-k2.6
                    # is an extended-thinking model: it spends a chunk of the
                    # max_tokens budget on reasoning before emitting the JSON.
                    # 2048 is enough for tool-call turns; the final JSON pass
                    # needs ~4x that to leave room for both reasoning and output.
                    max_tokens=8192 if is_final_turn else 2048,
                    tags={"agent_turn": str(turn)},
                )
            )

            if response.tool_calls:
                # Append the assistant's tool-call message verbatim
                messages.append(
                    Message(
                        role="assistant",
                        content=response.content,
                        tool_calls=response.tool_calls,
                    )
                )
                for call in response.tool_calls:
                    yield AgentEvent(
                        "tool_call",
                        {"name": call.name, "arguments": call.arguments},
                    )
                    msg, hits = await self._dispatch_tool(call, context, turn)
                    messages.append(msg)
                    if hits is not None:
                        ledger.add(turn=turn, hits=hits)
                        yield AgentEvent(
                            "tool_result",
                            {"name": call.name, "n_hits": len(hits)},
                        )
                    else:
                        yield AgentEvent(
                            "tool_error",
                            {"name": call.name, "message": msg.content},
                        )
                continue  # round-trip again so the LLM sees the tool result

            # No tool call — assume the LLM is producing a final answer.
            content = response.content or ""
            try:
                parsed = parse_narration_response(content)
                verify_citations(parsed, ledger=ledger, current_turn=turn)
                yield AgentEvent("narration", {"text": parsed.narration})
                yield AgentEvent(
                    "citations",
                    {"citations": [dataclasses.asdict(c) for c in parsed.citations]},
                )
                result = AgentResult(
                    narration=parsed.narration,
                    citations=parsed.citations,
                    verified=True,
                    warning=None,
                    turns=turn,
                    duration_s=time.perf_counter() - t0,
                    ledger=ledger,
                )
                yield AgentEvent("done", {"result": result})
                return
            except CitationError as exc:
                if verify_attempts_remaining <= 0:
                    # Surface the warning + the unverified narration.
                    parsed_or_none = _try_parse(content)
                    warning = f"citation verification failed: {exc}"
                    yield AgentEvent("warning", {"message": warning})
                    if parsed_or_none is not None:
                        yield AgentEvent(
                            "narration", {"text": parsed_or_none.narration}
                        )
                        yield AgentEvent(
                            "citations",
                            {
                                "citations": [
                                    dataclasses.asdict(c)
                                    for c in parsed_or_none.citations
                                ]
                            },
                        )
                    result = AgentResult(
                        narration=(
                            parsed_or_none.narration if parsed_or_none else ""
                        ),
                        citations=(
                            parsed_or_none.citations if parsed_or_none else []
                        ),
                        verified=False,
                        warning=warning,
                        turns=turn,
                        duration_s=time.perf_counter() - t0,
                        ledger=ledger,
                    )
                    yield AgentEvent("done", {"result": result})
                    return
                # Retry once with a corrective directive
                verify_attempts_remaining -= 1
                retry_pending = True
                messages.append(
                    Message(role="assistant", content=content)
                )
                messages.append(
                    Message(
                        role="user",
                        content=(
                            f"Your previous response failed citation verification: "
                            f"{exc}. Re-emit the JSON, copying citation fields "
                            f"verbatim from earlier search_places results. Do not "
                            f"cite doc_ids you did not retrieve."
                        ),
                    )
                )
                yield AgentEvent("warning", {"message": str(exc), "retry": True})
                continue

        raise AgentLoopError(f"agent loop hit turn cap of {self._max_turns}")

    # -- tool dispatch helper ------------------------------------------

    async def _dispatch_tool(
        self,
        call: ToolCall,
        context: ToolExecutionContext,
        turn: int,
    ) -> tuple[Message, list[dict[str, Any]] | None]:
        """Run a tool call, return (message-to-append, hits-or-None).

        `hits` is None when the call errored — caller emits a tool_error event.
        """
        try:
            tool = self._registry.get(call.name)
        except UnknownToolError:
            return (
                Message(
                    role="tool",
                    name=call.name,
                    tool_call_id=call.id,
                    content=json.dumps(
                        {
                            "error": "unknown_tool",
                            "message": (
                                f"Tool {call.name!r} is not in the V1 surface. "
                                f"Only `search_places` is available."
                            ),
                        }
                    ),
                ),
                None,
            )

        try:
            output = await tool.run(call.arguments, context)
        except ToolArgError as exc:
            return (
                Message(
                    role="tool",
                    name=call.name,
                    tool_call_id=call.id,
                    content=json.dumps({"error": "bad_args", "message": str(exc)}),
                ),
                None,
            )
        except Exception as exc:  # noqa: BLE001
            return (
                Message(
                    role="tool",
                    name=call.name,
                    tool_call_id=call.id,
                    content=json.dumps({"error": "internal", "message": str(exc)}),
                ),
                None,
            )

        hits: list[dict[str, Any]] = []
        if isinstance(output, dict) and isinstance(output.get("results"), list):
            hits = list(output["results"])

        return (
            Message(
                role="tool",
                name=call.name,
                tool_call_id=call.id,
                content=json.dumps(output, default=str),
            ),
            hits,
        )


# ── Helpers ─────────────────────────────────────────────────────────


def _try_parse(content: str) -> NarrationResponse | None:
    try:
        return parse_narration_response(content)
    except CitationError:
        return None


def response_format_okay() -> bool:
    """Carved out so a future env-driven kill-switch can disable the
    `response_format=json` hint if a backend dislikes it. Defaults to True
    because OpenRouter accepts the OpenAI flag and most modern models
    honor it; setting to False is a one-line override."""
    return True


_ = (asyncio, Tool)  # explicit re-imports / silence unused-import linter
