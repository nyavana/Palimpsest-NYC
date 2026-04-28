"""Meta-instrumentation harness.

Captures Claude Code session telemetry so the final report can quantify
the cost, cycle time, and failure modes of building the product
end-to-end with an autonomous coding agent.

Public API:
    from app.meta import SessionLogger, SessionRecord, SCHEMA_VERSION
"""

from app.meta.session_log import SCHEMA_VERSION, SessionLogger, SessionRecord

__all__ = ["SCHEMA_VERSION", "SessionLogger", "SessionRecord"]
