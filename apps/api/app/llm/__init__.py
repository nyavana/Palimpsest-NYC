"""LLM router capability.

Provides a cost-aware, telemetered dispatcher across:
- local llama.cpp serving Gemma-4-26B (simple tasks)
- OpenRouter GPT-5.4-mini (standard tasks)
- OpenRouter GPT-5.4 (complex tasks)

Public API:
    from app.llm import LLMRouter, ChatRequest, Complexity
"""

from app.llm.models import (
    ChatRequest,
    ChatResponse,
    Complexity,
    Message,
    NormalizedRequest,
    NormalizedResponse,
    TelemetryRecord,
    ToolCall,
    ToolDefinition,
    Usage,
)
from app.llm.router import (
    CloudBackendUnavailableError,
    LLMRouter,
    LLMRouterError,
    UnknownToolError,
)

__all__ = [
    "ChatRequest",
    "ChatResponse",
    "CloudBackendUnavailableError",
    "Complexity",
    "LLMRouter",
    "LLMRouterError",
    "Message",
    "NormalizedRequest",
    "NormalizedResponse",
    "TelemetryRecord",
    "ToolCall",
    "ToolDefinition",
    "UnknownToolError",
    "Usage",
]
