"""`Tool` base class + registry + validation helpers.

Every concrete tool subclass declares:
  - `name` — string, must be unique within a registry
  - `description` — short sentence the LLM sees
  - `parameters` — JSON Schema describing the tool's args (single source of
                   truth for both LLM tool-calling and server-side validation)

The `run(args, context)` path validates the incoming args against the
schema before calling `execute(...)`. Validation failures raise
`ToolArgError` which the agent loop turns into a tool-error message
the LLM can recover from on the next turn.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import jsonschema

from app.llm.models import ToolDefinition

if TYPE_CHECKING:
    # Forward-only imports to avoid an import cycle:
    #   app.routing imports nothing from app.agent.tools
    #   app.agent.citations imports nothing from app.agent.tools
    # but app.agent.tools.plan_walk DOES import from both, so keeping these
    # imports under TYPE_CHECKING keeps `app.agent.tools.base` itself a leaf
    # module that any tool can import without dragging the routing or
    # citations modules into the import graph at module-load time.
    from app.agent.citations import RetrievalLedger
    from app.routing import RoutingBackend


class ToolArgError(ValueError):
    """Raised when a tool is invoked with arguments that fail JSON Schema validation."""


class UnknownToolError(KeyError):
    """Raised when the LLM asks for a tool name not in the registry.

    Per agent-tools spec: the loop catches this, appends a tool-error message
    to the conversation, and lets the LLM retry on the next turn.
    """


# ── Execution context ───────────────────────────────────────────────


@runtime_checkable
class _SessionLike(Protocol):
    """The narrow async-session surface the tools actually use."""

    async def execute(self, *args: Any, **kwargs: Any) -> Any: ...


@dataclass
class ToolExecutionContext:
    """Per-call context passed to `Tool.execute`.

    Holds whatever ambient state a tool needs (DB session, embedder, routing
    backend, retrieval ledger) without forcing every tool to declare it.
    Tests can build a default context with no kwargs and inject only what
    the tool under test consumes.

    Fields:
      - `session`: async DB session (used by both tools).
      - `embedder`: sentence-transformer singleton (used by `search_places`).
      - `routing_backend`: routing client (used by `plan_walk`; `None` means
        the tool MUST fail loudly rather than silently degrade).
      - `retrieval_ledger`: per-conversation `RetrievalLedger` (used by
        `plan_walk` to validate that every `place_id` it's asked to route
        through was actually returned by a prior `search_places` call).
      - `metadata`: free-form bag for ad-hoc per-call data.
    """

    session: _SessionLike | None = None
    embedder: Any = None
    routing_backend: RoutingBackend | None = None
    retrieval_ledger: RetrievalLedger | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Tool ABC ────────────────────────────────────────────────────────


class Tool:
    """Abstract base — concrete tools subclass and override `execute`."""

    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {}

    # ----- LLM definition -------------------------------------------

    def definition(self) -> ToolDefinition:
        """Return the OpenAI-compatible tool schema."""
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )

    # ----- Validation + dispatch ------------------------------------

    def _apply_defaults(self, args: dict[str, Any]) -> dict[str, Any]:
        """Layer JSON-Schema `default` values onto the incoming args."""
        result = dict(args)
        properties = self.parameters.get("properties", {})
        for key, schema in properties.items():
            if key not in result and "default" in schema:
                result[key] = schema["default"]
        return result

    def validate(self, args: dict[str, Any]) -> None:
        """Validate `args` against the tool's parameter schema.

        Raises `ToolArgError` on any failure. Caller is expected to surface
        the error message back to the LLM.
        """
        try:
            jsonschema.validate(instance=args, schema=self.parameters)
        except jsonschema.ValidationError as exc:
            raise ToolArgError(str(exc)) from exc

    async def run(
        self, args: dict[str, Any], context: ToolExecutionContext
    ) -> Any:
        self.validate(args)
        full = self._apply_defaults(args)
        return await self.execute(full, context)

    async def execute(
        self, args: dict[str, Any], context: ToolExecutionContext
    ) -> Any:
        raise NotImplementedError


# ── Registry ────────────────────────────────────────────────────────


class ToolRegistry:
    """Holds the V1 LLM tool surface (exactly one entry in V1)."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name: {tool.name!r}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise UnknownToolError(name)
        return self._tools[name]

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def definitions(self) -> list[ToolDefinition]:
        return [t.definition() for t in self._tools.values()]
