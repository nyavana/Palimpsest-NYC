"""Typed request/response models for the LLM router.

The router intentionally defines its own shapes rather than leaking OpenAI or
OpenRouter response types. Adapters translate between provider APIs and these
shared types so the router stays backend-agnostic.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Complexity = Literal["simple", "standard", "complex"]
Role = Literal["system", "user", "assistant", "tool"]


class Message(BaseModel):
    """A single message in the chat conversation."""

    model_config = ConfigDict(extra="forbid")

    role: Role
    content: str | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] | None = None


class ToolDefinition(BaseModel):
    """JSON-schema-based tool declaration the LLM may invoke."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    """A tool-call the LLM asked the runtime to perform."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Usage(BaseModel):
    """Token / cost accounting for a single call."""

    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0


class ChatRequest(BaseModel):
    """What callers submit to the router."""

    model_config = ConfigDict(extra="forbid")

    messages: list[Message]
    complexity: Complexity = "standard"
    tools: list[ToolDefinition] | None = None
    temperature: float = 0.2
    max_tokens: int | None = None
    response_format: Literal["text", "json"] | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    """What the router returns to callers."""

    model_config = ConfigDict(extra="forbid")

    id: str
    content: str | None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    backend: Literal["local", "openrouter"]
    model: str
    cached: bool = False
    upgraded_from: Literal["local"] | None = None
    latency_ms: float = 0.0


class NormalizedRequest(BaseModel):
    """Backend-agnostic request shape adapters receive."""

    model_config = ConfigDict(extra="forbid")

    model: str
    messages: list[Message]
    tools: list[ToolDefinition] | None = None
    temperature: float = 0.2
    max_tokens: int | None = None
    response_format: Literal["text", "json"] | None = None


class NormalizedResponse(BaseModel):
    """Backend-agnostic response shape adapters must return."""

    model_config = ConfigDict(extra="forbid")

    id: str
    content: str | None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    model: str


class TelemetryRecord(BaseModel):
    """One line in the router telemetry stream.

    Emitted for every call including cache hits and errors. Persisted to
    structlog AND to a Redis time series so the final report can aggregate
    across both.
    """

    model_config = ConfigDict(extra="forbid")

    request_id: str
    timestamp: str
    backend: Literal["local", "openrouter"] | None
    model: str | None
    complexity: Complexity
    cached: bool
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    error_code: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)


Message.model_rebuild()
