"""Agent loop + tool surface for Palimpsest NYC.

V1 contract (locked under `swap-llm-tiers-and-lock-mvp-decisions`):
  - one LLM-callable tool only (`search_places`)
  - turn cap = 6 to allow iterative retrieval refinement
  - terminal response is JSON: `{narration, citations[]}` per the locked
    citation contract
  - server-side `plan_walk` runs after the agent emits citations[];
    the LLM never sees it
"""

from app.agent.tools.base import (
    Tool,
    ToolArgError,
    ToolExecutionContext,
    ToolRegistry,
    UnknownToolError,
)

__all__ = [
    "Tool",
    "ToolArgError",
    "ToolExecutionContext",
    "ToolRegistry",
    "UnknownToolError",
]
