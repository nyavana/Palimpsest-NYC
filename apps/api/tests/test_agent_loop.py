"""Agent loop tests — drive the loop with a fake LLM router and assert
the produced sequence of messages, the tool dispatch, and the citation-
verification retry path.
"""

from __future__ import annotations

import uuid
from typing import Any, Iterator

import pytest

from app.agent.intent import (
    INTENT_NOTE_NEGATIVE,
    INTENT_NOTE_POSITIVE,
)
from app.agent.loop import AgentEvent, AgentLoop, AgentResult, MAX_TURNS_DEFAULT
from app.agent.tools.base import Tool, ToolExecutionContext, ToolRegistry
from app.llm.models import (
    ChatRequest,
    ChatResponse,
    Message,
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


async def test_prior_history_messages_are_included_before_current_query():
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
    history = [
        Message(role="user", content="Tell me about Riverside Church"),
        Message(role="assistant", content="Riverside Church is a landmark."),
    ]

    await loop.run("Make it shorter", context=ToolExecutionContext(), history_messages=history)

    first = router.calls[0]
    assert [m.role for m in first.messages[:4]] == ["system", "user", "assistant", "user"]
    assert first.messages[1].content == "Tell me about Riverside Church"
    assert first.messages[2].content == "Riverside Church is a landmark."
    assert first.messages[3].content == "Make it shorter"


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


# ── plan_walk integration: tool surface + walk capture + intent hint ─


# Canned plan_walk return value mirroring the RouteResult dict shape.
_FAKE_WALK_RESULT: dict[str, Any] = {
    "stops": [
        {"index": 0, "doc_id": "wikipedia:A", "name": "A",
         "lat": 40.8, "lon": -73.96},
        {"index": 1, "doc_id": "wikipedia:B", "name": "B",
         "lat": 40.81, "lon": -73.97},
    ],
    "legs": [
        {"from_index": 0, "to_index": 1, "distance_m": 412,
         "duration_s": 295,
         "geometry": {"type": "LineString",
                      "coordinates": [[-73.96, 40.8], [-73.97, 40.81]]},
         "steps": [{"instruction": "Head east", "distance_m": 412,
                    "duration_s": 295, "maneuver_type": "depart"}]},
    ],
    "geometry": {"type": "LineString",
                 "coordinates": [[-73.96, 40.8], [-73.97, 40.81]]},
    "total_distance_m": 412,
    "total_duration_s": 295,
    "routing_backend": "osrm",
    "stop_ordering": "input_order",
}


class _FakePlanWalkTool(Tool):
    """In-test stand-in for `PlanWalkTool` with scripted return values.

    The real tool needs DB session + routing backend on the context; this
    fake only needs whatever the test-scripted responses ask for. Each
    `run()` invocation pops the next scripted response off the list.
    """

    name = "plan_walk"
    description = "stub"
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "place_ids": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 8,
            },
            "mode": {
                "type": "string",
                "enum": ["walking"],
                "default": "walking",
            },
        },
        "required": ["place_ids"],
        "additionalProperties": True,
    }

    def __init__(self, results: list[dict[str, Any]]) -> None:
        self._iter: Iterator[dict[str, Any]] = iter(results)
        self.calls: list[dict[str, Any]] = []

    async def execute(
        self, args: dict[str, Any], context: ToolExecutionContext
    ) -> Any:
        self.calls.append(dict(args))
        try:
            return next(self._iter)
        except StopIteration as e:
            raise AssertionError(
                "plan_walk fake called more times than scripted"
            ) from e


def _registry_with_search_and_plan(
    search: _FixedSearchTool,
    plan: _FakePlanWalkTool,
) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(search)
    reg.register(plan)
    return reg


def _hits_two() -> list[dict[str, Any]]:
    return [
        {
            "doc_id": "wikipedia:A",
            "name": "A",
            "source_type": "wikipedia",
            "source_url": "https://en.wikipedia.org/wiki/A",
            "lat": 40.8,
            "lon": -73.96,
        },
        {
            "doc_id": "wikipedia:B",
            "name": "B",
            "source_type": "wikipedia",
            "source_url": "https://en.wikipedia.org/wiki/B",
            "lat": 40.81,
            "lon": -73.97,
        },
    ]


def _final_message_two_citations(retrieval_turn: int = 1) -> str:
    """Final-response JSON citing both A and B."""
    # Mirrors `_final_message` above (same in-function-import style).
    import json as _json

    return _json.dumps(
        {
            "narration": "Walk from A to B.",
            "citations": [
                {
                    "doc_id": "wikipedia:A",
                    "source_url": "https://en.wikipedia.org/wiki/A",
                    "source_type": "wikipedia",
                    "span": "intro",
                    "retrieval_turn": retrieval_turn,
                },
                {
                    "doc_id": "wikipedia:B",
                    "source_url": "https://en.wikipedia.org/wiki/B",
                    "source_type": "wikipedia",
                    "span": "intro",
                    "retrieval_turn": retrieval_turn,
                },
            ],
        }
    )


# ── Default turn cap is 7 (spec) ─────────────────────────────────────


def test_max_turns_default_is_seven():
    """Spec: default cap raised from 6 to 7 to absorb the plan_walk round-trip."""
    assert MAX_TURNS_DEFAULT == 7


# ── (a) Tour-style positive query → plan_walk called, walk captured ───


async def test_positive_query_calls_plan_walk_and_captures_walk():
    """Tour-style query → hint=positive; loop dispatches plan_walk; walk captured.

    Sequence:
      turn 1: search_places → returns A and B
      turn 2: plan_walk(place_ids=[A,B]) → fake walk result
      turn 3: final JSON citing A and B
    """
    search = _FixedSearchTool(_hits_two())
    plan = _FakePlanWalkTool([_FAKE_WALK_RESULT])
    registry = _registry_with_search_and_plan(search, plan)
    router = _ScriptedRouter(
        [
            _resp(
                tool_calls=[
                    ToolCall(id="c1", name="search_places", arguments={"query": "x"})
                ]
            ),
            _resp(
                tool_calls=[
                    ToolCall(
                        id="c2",
                        name="plan_walk",
                        arguments={"place_ids": ["wikipedia:A", "wikipedia:B"]},
                    )
                ]
            ),
            _resp(content=_final_message_two_citations(retrieval_turn=1)),
        ]
    )
    loop = AgentLoop(router=router, registry=registry)
    result = await loop.run(
        "plan a walk through Morningside Heights",
        context=ToolExecutionContext(),
    )

    # Hint reflects the run-time classification.
    assert result.walk_intent_hint == "positive"
    # The walk dict was captured from the most recent successful plan_walk.
    assert result.walk == _FAKE_WALK_RESULT
    # The system prompt the LLM saw on turn 1 contains the positive NOTE.
    first_sys = next(m for m in router.calls[0].messages if m.role == "system")
    assert INTENT_NOTE_POSITIVE in (first_sys.content or "")
    # plan_walk was invoked exactly once with the LLM's argument list.
    # The tool base layers schema defaults (`mode="walking"`) before execute,
    # so the recorded args carry that field too.
    assert len(plan.calls) == 1
    assert plan.calls[0]["place_ids"] == ["wikipedia:A", "wikipedia:B"]
    # The narration cites both retrieved docs.
    assert {c.doc_id for c in result.citations} == {"wikipedia:A", "wikipedia:B"}


# ── (b) Informational negative query → plan_walk NOT called ──────────


async def test_negative_query_does_not_call_plan_walk():
    """Informational query → hint=negative; LLM (scripted) skips plan_walk."""
    search = _FixedSearchTool(_hits_two())
    plan = _FakePlanWalkTool([])  # never called
    registry = _registry_with_search_and_plan(search, plan)
    router = _ScriptedRouter(
        [
            _resp(
                tool_calls=[
                    ToolCall(id="c1", name="search_places", arguments={"query": "x"})
                ]
            ),
            _resp(content=_final_message_two_citations(retrieval_turn=1)),
        ]
    )
    loop = AgentLoop(router=router, registry=registry)
    result = await loop.run(
        "tell me about the Cathedral of St. John the Divine",
        context=ToolExecutionContext(),
    )

    assert result.walk_intent_hint == "negative"
    assert result.walk is None
    # The system prompt seen on turn 1 contains the negative NOTE.
    first_sys = next(m for m in router.calls[0].messages if m.role == "system")
    assert INTENT_NOTE_NEGATIVE in (first_sys.content or "")
    # plan_walk was never invoked.
    assert plan.calls == []


# ── (c) Ambiguous neutral query → no NOTE line, hint=neutral ─────────


async def test_neutral_query_appends_no_note_line():
    """Ambiguous query → hint=neutral; system prompt has no NOTE line."""
    search = _FixedSearchTool(_hits_two())
    plan = _FakePlanWalkTool([])  # not called
    registry = _registry_with_search_and_plan(search, plan)
    router = _ScriptedRouter(
        [
            _resp(
                tool_calls=[
                    ToolCall(id="c1", name="search_places", arguments={"query": "x"})
                ]
            ),
            _resp(content=_final_message_two_citations(retrieval_turn=1)),
        ]
    )
    loop = AgentLoop(router=router, registry=registry)
    # "Cathedral" alone has no walk-keyword and no informational prefix.
    result = await loop.run(
        "Cathedral of St. John the Divine",
        context=ToolExecutionContext(),
    )

    assert result.walk_intent_hint == "neutral"
    first_sys = next(m for m in router.calls[0].messages if m.role == "system")
    sys_content = first_sys.content or ""
    # Neither NOTE line should appear in the system prompt.
    assert INTENT_NOTE_POSITIVE not in sys_content
    assert INTENT_NOTE_NEGATIVE not in sys_content
    assert "NOTE:" not in sys_content


# ── (d) Two plan_walk calls — only the most recent is retained ───────


async def test_multiple_plan_walks_keep_only_most_recent():
    """Spec: most-recent successful plan_walk wins; earlier calls superseded."""
    search = _FixedSearchTool(_hits_two())

    refined_walk = dict(_FAKE_WALK_RESULT)
    refined_walk["total_distance_m"] = 999
    refined_walk["stop_ordering"] = "tsp_optimized"

    plan = _FakePlanWalkTool([_FAKE_WALK_RESULT, refined_walk])
    registry = _registry_with_search_and_plan(search, plan)
    router = _ScriptedRouter(
        [
            _resp(
                tool_calls=[
                    ToolCall(id="c1", name="search_places", arguments={"query": "x"})
                ]
            ),
            _resp(
                tool_calls=[
                    ToolCall(
                        id="c2",
                        name="plan_walk",
                        arguments={"place_ids": ["wikipedia:A", "wikipedia:B"]},
                    )
                ]
            ),
            _resp(
                tool_calls=[
                    ToolCall(
                        id="c3",
                        name="plan_walk",
                        arguments={"place_ids": ["wikipedia:B", "wikipedia:A"]},
                    )
                ]
            ),
            _resp(content=_final_message_two_citations(retrieval_turn=1)),
        ]
    )
    loop = AgentLoop(router=router, registry=registry)
    result = await loop.run(
        "plan a walk between A and B",
        context=ToolExecutionContext(),
    )

    # The tool base layers schema defaults onto the args before execute,
    # so we assert place_ids only and ignore the auto-added `mode` field.
    assert [c["place_ids"] for c in plan.calls] == [
        ["wikipedia:A", "wikipedia:B"],
        ["wikipedia:B", "wikipedia:A"],
    ]
    # AgentResult.walk is the SECOND (refined) result, not the first.
    assert result.walk is not None
    assert result.walk["total_distance_m"] == 999
    assert result.walk["stop_ordering"] == "tsp_optimized"


# ── (e) plan_walk error envelope → walk stays None, loop continues ───


async def test_plan_walk_error_envelope_keeps_walk_none():
    """Tool returns ``{"error": ..., "message": ...}`` → AgentResult.walk = None.

    The agent loop continues — the LLM may retry plan_walk or proceed
    straight to the final JSON.
    """
    search = _FixedSearchTool(_hits_two())
    error_envelope: dict[str, Any] = {
        "error": "unknown_place_id",
        "place_id": "wikipedia:GHOST",
        "message": "doc_id not in retrieval ledger",
    }
    plan = _FakePlanWalkTool([error_envelope])
    registry = _registry_with_search_and_plan(search, plan)
    router = _ScriptedRouter(
        [
            _resp(
                tool_calls=[
                    ToolCall(id="c1", name="search_places", arguments={"query": "x"})
                ]
            ),
            _resp(
                tool_calls=[
                    ToolCall(
                        id="c2",
                        name="plan_walk",
                        arguments={"place_ids": ["wikipedia:A", "wikipedia:GHOST"]},
                    )
                ]
            ),
            _resp(content=_final_message_two_citations(retrieval_turn=1)),
        ]
    )
    loop = AgentLoop(router=router, registry=registry)
    result = await loop.run(
        "plan me a tour of A and GHOST",
        context=ToolExecutionContext(),
    )

    # The error envelope did NOT update the captured walk.
    assert result.walk is None
    # And the loop still completed normally with verified citations.
    assert result.verified is True
    # The error message should be in the conversation the third call saw.
    third = router.calls[2]
    tool_msgs = [m for m in third.messages if m.role == "tool"]
    assert any(
        "unknown_place_id" in (m.content or "") for m in tool_msgs
    )


# ── (f) Turn cap stays hard at 7 + final-turn directive fires ────────


async def test_turn_cap_at_seven_with_final_directive():
    """At default cap, turn 7 strips tools, sets max_tokens=8192, asks for JSON.

    The agent never produces a parseable final response, so AgentLoopError
    is raised (matching the existing behaviour of the cap-hit path).
    """
    search = _FixedSearchTool(_hits_two())
    # plan list left empty — never called by this script.
    plan = _FakePlanWalkTool([])
    registry = _registry_with_search_and_plan(search, plan)
    # Always returns a tool call → never finishes naturally
    responses = [
        _resp(
            tool_calls=[
                ToolCall(
                    id=f"c{i}", name="search_places", arguments={"query": "x"}
                )
            ]
        )
        for i in range(MAX_TURNS_DEFAULT + 5)
    ]
    router = _ScriptedRouter(responses)
    loop = AgentLoop(router=router, registry=registry)  # cap == 7 by default
    with pytest.raises(Exception) as ei:
        await loop.run("hi", context=ToolExecutionContext())
    assert "turn" in str(ei.value).lower()

    # Exactly MAX_TURNS_DEFAULT requests went out before the cap raise.
    assert len(router.calls) == MAX_TURNS_DEFAULT == 7
    # The final-turn request stripped tools and forced JSON with 8192 tokens.
    final_req = router.calls[-1]
    assert final_req.tools is None
    assert final_req.response_format == "json"
    assert final_req.max_tokens == 8192
    # Earlier requests kept tools and the smaller token budget.
    earlier_req = router.calls[0]
    assert earlier_req.tools is not None
    assert earlier_req.max_tokens == 2048
    assert earlier_req.response_format is None
    # The final-turn message log ends with the "stop searching" directive.
    last_user = next(
        m for m in reversed(final_req.messages) if m.role == "user"
    )
    assert "stop searching" in (last_user.content or "").lower()


# ── ToolExecutionContext.retrieval_ledger gets populated by the loop ─


async def test_plan_walk_discovered_stops_enter_retrieval_ledger():
    """plan_walk's auto-discovered POIs become part of the citation pool.

    The LLM searches for A and B (turn 1), calls plan_walk on turn 2, and
    plan_walk returns a `discovered_stops[]` containing doc C. The final
    JSON cites C with retrieval_turn=2 — the verifier accepts it because
    the loop registered C in the ledger when plan_walk returned.
    """
    import json as _json

    search = _FixedSearchTool(_hits_two())

    enriched_walk: dict[str, Any] = dict(_FAKE_WALK_RESULT)
    enriched_walk["discovered_stops"] = [
        {
            "doc_id": "wikipedia:C",
            "name": "Columbia University",
            "source_type": "wikipedia",
            "source_url": "https://en.wikipedia.org/wiki/Columbia_University",
            "lat": 40.8075,
            "lon": -73.9626,
            "dist_to_route_m": 18.0,
        }
    ]

    plan = _FakePlanWalkTool([enriched_walk])
    registry = _registry_with_search_and_plan(search, plan)

    final_with_discovered = _json.dumps(
        {
            "narration": "Walk through Columbia from A to B.",
            "citations": [
                {
                    "doc_id": "wikipedia:A",
                    "source_url": "https://en.wikipedia.org/wiki/A",
                    "source_type": "wikipedia",
                    "span": "intro",
                    "retrieval_turn": 1,
                },
                {
                    "doc_id": "wikipedia:C",
                    "source_url": "https://en.wikipedia.org/wiki/Columbia_University",
                    "source_type": "wikipedia",
                    "span": "discovered",
                    "retrieval_turn": 2,
                },
            ],
        }
    )

    router = _ScriptedRouter(
        [
            _resp(
                tool_calls=[
                    ToolCall(id="c1", name="search_places", arguments={"query": "x"})
                ]
            ),
            _resp(
                tool_calls=[
                    ToolCall(
                        id="c2",
                        name="plan_walk",
                        arguments={"place_ids": ["wikipedia:A", "wikipedia:B"]},
                    )
                ]
            ),
            _resp(content=final_with_discovered),
        ]
    )
    loop = AgentLoop(router=router, registry=registry)
    result = await loop.run(
        "plan a walk from A to B",
        context=ToolExecutionContext(),
    )

    # plan_walk's discovered POI is in the ledger and citable.
    assert result.verified is True
    cited_ids = {c.doc_id for c in result.citations}
    assert "wikipedia:C" in cited_ids
    # Ledger ledger registered C on turn 2 (the plan_walk turn).
    entry = result.ledger.lookup("wikipedia:C", on_or_before_turn=2)
    assert entry is not None
    assert entry.source_type == "wikipedia"
    assert entry.source_url == "https://en.wikipedia.org/wiki/Columbia_University"


async def test_loop_populates_retrieval_ledger_on_context():
    """The plan_walk tool requires a per-conversation RetrievalLedger on
    its context. The loop owns the ledger and mutates it onto the
    caller-provided context so plan_walk can validate place_ids.
    """
    search = _FixedSearchTool(_hits_two())
    plan = _FakePlanWalkTool([_FAKE_WALK_RESULT])
    registry = _registry_with_search_and_plan(search, plan)
    router = _ScriptedRouter(
        [
            _resp(
                tool_calls=[
                    ToolCall(id="c1", name="search_places", arguments={"query": "x"})
                ]
            ),
            _resp(
                tool_calls=[
                    ToolCall(
                        id="c2",
                        name="plan_walk",
                        arguments={"place_ids": ["wikipedia:A", "wikipedia:B"]},
                    )
                ]
            ),
            _resp(content=_final_message_two_citations(retrieval_turn=1)),
        ]
    )
    loop = AgentLoop(router=router, registry=registry)
    ctx = ToolExecutionContext()
    assert ctx.retrieval_ledger is None
    result = await loop.run("plan a walk through A and B", context=ctx)

    # After the run, the loop has populated the ledger and it knows the
    # docs the search tool returned.
    assert ctx.retrieval_ledger is not None
    assert ctx.retrieval_ledger.lookup(
        "wikipedia:A", on_or_before_turn=1
    ) is not None
    # And the result picks up the same ledger via AgentResult.ledger.
    assert result.ledger is ctx.retrieval_ledger
