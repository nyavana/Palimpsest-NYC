"""Agent loop tests — drive the loop with a fake LLM router and assert
the produced sequence of messages, the tool dispatch, and the citation-
verification retry path.
"""

from __future__ import annotations

import uuid
from typing import Any, Iterator

import pytest

from app.agent.loop import AgentEvent, AgentLoop, AgentResult, MAX_TURNS_DEFAULT
from app.agent.tools.base import Tool, ToolExecutionContext, ToolRegistry
from app.llm.models import (
    ChatRequest,
    ChatResponse,
    ToolCall,
    Usage,
)


# ── Fake router ─────────────────────────────────────────────────────


class _ScriptedRouter:
    """Yields scripted ChatResponses in order."""

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._iter: Iterator[ChatResponse] = iter(responses)
        self.calls: list[ChatRequest] = []

    async def chat(self, req: ChatRequest) -> ChatResponse:
        self.calls.append(req)
        try:
            return next(self._iter)
        except StopIteration as e:
            raise AssertionError("router called more times than scripted") from e


def _resp(content: str | None = None, tool_calls: list[ToolCall] | None = None) -> ChatResponse:
    return ChatResponse(
        id=uuid.uuid4().hex,
        content=content,
        tool_calls=tool_calls or [],
        usage=Usage(),
        backend="openrouter",
        model="moonshotai/kimi-k2.6",
    )


# ── Fake tools ──────────────────────────────────────────────────────


class _FixedSearchTool(Tool):
    name = "search_places"
    description = "stub"
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {"query": {"type": "string", "minLength": 1}},
        "required": ["query"],
        "additionalProperties": True,
    }

    def __init__(self, hits: list[dict[str, Any]]) -> None:
        self._hits = hits

    async def execute(self, args: dict[str, Any], context: ToolExecutionContext) -> Any:
        return {"results": self._hits}


def _registry_with(tool: Tool) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(tool)
    return reg


def _hit(doc_id: str = "wikipedia:X") -> dict[str, Any]:
    return {
        "doc_id": doc_id,
        "name": "X",
        "source_type": "wikipedia",
        "source_url": f"https://en.wikipedia.org/wiki/{doc_id.split(':')[-1]}",
        "lat": 40.8,
        "lon": -73.96,
    }


def _final_message(doc_id: str, retrieval_turn: int = 1) -> str:
    """Build a valid final-response JSON the verifier accepts."""
    import json as _json

    slug = doc_id.split(":", 1)[-1]
    return _json.dumps(
        {
            "narration": "narration body",
            "citations": [
                {
                    "doc_id": doc_id,
                    "source_url": f"https://en.wikipedia.org/wiki/{slug}",
                    "source_type": "wikipedia",
                    "span": "intro",
                    "retrieval_turn": retrieval_turn,
                }
            ],
        }
    )


# ── V1 contract: single tool registered ─────────────────────────────


async def test_only_search_places_is_registered_with_llm():
    tool = _FixedSearchTool([_hit()])
    registry = _registry_with(tool)
    router = _ScriptedRouter(
        [
            _resp(
                tool_calls=[
                    ToolCall(id="c1", name="search_places", arguments={"query": "x"})
                ]
            ),
            _resp(content=_final_message("wikipedia:X")),
        ]
    )
    loop = AgentLoop(router=router, registry=registry)
    result = await loop.run("hello", context=ToolExecutionContext())

    # Every request to the LLM must register exactly one tool.
    for req in router.calls:
        assert req.tools is not None
        assert [t.name for t in req.tools] == ["search_places"]
    assert isinstance(result, AgentResult)
    assert result.verified is True


# ── Tool dispatch + retrieval ledger ────────────────────────────────


async def test_tool_call_dispatches_and_appends_tool_message():
    tool = _FixedSearchTool([_hit()])
    registry = _registry_with(tool)
    router = _ScriptedRouter(
        [
            _resp(
                tool_calls=[
                    ToolCall(id="c1", name="search_places", arguments={"query": "x"})
                ]
            ),
            _resp(content=_final_message("wikipedia:X")),
        ]
    )
    loop = AgentLoop(router=router, registry=registry)
    result = await loop.run("hi", context=ToolExecutionContext())

    # Second request includes the tool result message in its conversation
    second = router.calls[1]
    roles = [m.role for m in second.messages]
    assert "tool" in roles
    # The retrieval ledger picked up the search result
    assert "wikipedia:X" in {c.doc_id for c in result.citations}


# ── Unknown tool name → error message back to LLM (not a crash) ──────


async def test_unknown_tool_name_appends_error_and_lets_llm_retry():
    tool = _FixedSearchTool([_hit()])
    registry = _registry_with(tool)
    router = _ScriptedRouter(
        [
            _resp(
                tool_calls=[
                    ToolCall(id="c1", name="plan_walk", arguments={})
                ]
            ),
            _resp(
                tool_calls=[
                    ToolCall(id="c2", name="search_places", arguments={"query": "x"})
                ]
            ),
            # search_places ran on turn 2 (turn 1 was the rejected plan_walk),
            # so the citation's retrieval_turn must be ≥ 2.
            _resp(content=_final_message("wikipedia:X", retrieval_turn=2)),
        ]
    )
    loop = AgentLoop(router=router, registry=registry)
    result = await loop.run("hi", context=ToolExecutionContext())

    # Three calls happened; the second message includes an error tool result for plan_walk
    second = router.calls[1]
    tool_msgs = [m for m in second.messages if m.role == "tool"]
    assert tool_msgs
    assert any("plan_walk" in (m.content or "") for m in tool_msgs)
    assert "wikipedia:X" in {c.doc_id for c in result.citations}


# ── Citation verification retry ─────────────────────────────────────


async def test_invalid_citation_triggers_one_retry_with_correction():
    tool = _FixedSearchTool([_hit()])
    registry = _registry_with(tool)
    bad = _final_message("wikipedia:Made_Up")  # not in retrieval ledger
    good = _final_message("wikipedia:X")
    router = _ScriptedRouter(
        [
            _resp(
                tool_calls=[
                    ToolCall(id="c1", name="search_places", arguments={"query": "x"})
                ]
            ),
            _resp(content=bad),
            _resp(content=good),
        ]
    )
    loop = AgentLoop(router=router, registry=registry)
    result = await loop.run("hi", context=ToolExecutionContext())

    # Three router calls: tool, bad answer, retry → good answer
    assert len(router.calls) == 3
    assert "wikipedia:X" in {c.doc_id for c in result.citations}
    # The third call's last user message contains a corrective directive
    third = router.calls[2]
    last_user = next(m for m in reversed(third.messages) if m.role == "user")
    assert "citation" in (last_user.content or "").lower()


async def test_invalid_citation_after_retry_returns_warning_not_crash():
    tool = _FixedSearchTool([_hit()])
    registry = _registry_with(tool)
    bad = _final_message("wikipedia:Made_Up")
    router = _ScriptedRouter(
        [
            _resp(
                tool_calls=[
                    ToolCall(id="c1", name="search_places", arguments={"query": "x"})
                ]
            ),
            _resp(content=bad),
            _resp(content=bad),
        ]
    )
    loop = AgentLoop(router=router, registry=registry)
    result = await loop.run("hi", context=ToolExecutionContext())
    # The loop returns successfully with `verified=False` and a warning surfaced.
    assert result.verified is False
    assert result.warning is not None


# ── Turn cap ────────────────────────────────────────────────────────


async def test_turn_cap_enforced():
    tool = _FixedSearchTool([_hit()])
    registry = _registry_with(tool)
    # Always returns a tool call → never finishes naturally
    responses = [
        _resp(
            tool_calls=[
                ToolCall(id=f"c{i}", name="search_places", arguments={"query": "x"})
            ]
        )
        for i in range(MAX_TURNS_DEFAULT + 5)
    ]
    router = _ScriptedRouter(responses)
    loop = AgentLoop(router=router, registry=registry, max_turns=3)
    with pytest.raises(Exception) as ei:
        await loop.run("hi", context=ToolExecutionContext())
    assert "turn" in str(ei.value).lower()


# ── Event emission (used by SSE) ────────────────────────────────────


async def test_run_streamed_yields_status_and_final_events():
    tool = _FixedSearchTool([_hit()])
    registry = _registry_with(tool)
    router = _ScriptedRouter(
        [
            _resp(
                tool_calls=[
                    ToolCall(id="c1", name="search_places", arguments={"query": "x"})
                ]
            ),
            _resp(content=_final_message("wikipedia:X")),
        ]
    )
    loop = AgentLoop(router=router, registry=registry)
    events: list[AgentEvent] = []
    async for ev in loop.run_streamed("hi", context=ToolExecutionContext()):
        events.append(ev)
    types = [ev.type for ev in events]
    assert "turn" in types
    assert "tool_result" in types
    assert "narration" in types
    assert "citations" in types
    assert types[-1] == "done"
