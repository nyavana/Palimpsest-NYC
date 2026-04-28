"""Tool base class tests — JSON-Schema validation + LLM definition shape."""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.tools.base import (
    Tool,
    ToolArgError,
    ToolExecutionContext,
)
from app.llm.models import ToolDefinition


class _EchoTool(Tool):
    name = "echo"
    description = "Echo a string back."
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "minLength": 1},
            "times": {"type": "integer", "minimum": 1, "default": 1},
        },
        "required": ["text"],
        "additionalProperties": False,
    }

    async def execute(
        self, args: dict[str, Any], context: ToolExecutionContext
    ) -> dict[str, Any]:
        text = args["text"]
        times = args.get("times", 1)
        return {"out": text * times}


# ── Definition shape ────────────────────────────────────────────────


def test_tool_definition_is_llm_compatible():
    tool = _EchoTool()
    definition = tool.definition()
    assert isinstance(definition, ToolDefinition)
    assert definition.name == "echo"
    assert definition.description == "Echo a string back."
    assert definition.parameters["type"] == "object"


# ── Argument validation ─────────────────────────────────────────────


async def test_invalid_args_missing_required_raises_tool_arg_error():
    tool = _EchoTool()
    with pytest.raises(ToolArgError) as ei:
        await tool.run({}, ToolExecutionContext())
    assert "text" in str(ei.value)


async def test_invalid_args_wrong_type_raises_tool_arg_error():
    tool = _EchoTool()
    with pytest.raises(ToolArgError):
        await tool.run({"text": 123}, ToolExecutionContext())


async def test_invalid_args_extra_property_raises_tool_arg_error():
    tool = _EchoTool()
    with pytest.raises(ToolArgError):
        await tool.run({"text": "x", "unknown": True}, ToolExecutionContext())


async def test_valid_args_dispatch_to_execute():
    tool = _EchoTool()
    out = await tool.run({"text": "hi", "times": 3}, ToolExecutionContext())
    assert out == {"out": "hihihi"}


async def test_default_value_applied_when_not_provided():
    tool = _EchoTool()
    out = await tool.run({"text": "x"}, ToolExecutionContext())
    assert out == {"out": "x"}


# ── Tool name uniqueness in a registry ──────────────────────────────


def test_tool_registry_rejects_duplicate_names():
    from app.agent.tools.base import ToolRegistry

    reg = ToolRegistry()
    reg.register(_EchoTool())
    with pytest.raises(ValueError):
        reg.register(_EchoTool())


def test_tool_registry_round_trip_get_by_name():
    from app.agent.tools.base import ToolRegistry

    reg = ToolRegistry()
    tool = _EchoTool()
    reg.register(tool)
    assert reg.get("echo") is tool
    assert reg.names() == ["echo"]


def test_tool_registry_unknown_tool_raises():
    from app.agent.tools.base import ToolRegistry, UnknownToolError

    reg = ToolRegistry()
    with pytest.raises(UnknownToolError):
        reg.get("nope")
