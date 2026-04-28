"""/internal/* routes — meta-instrumentation and metrics surfaces."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/metrics")
async def metrics(request: Request) -> dict[str, object]:
    """Aggregate Claude-Code session telemetry for the local dashboard.

    Returns a summary of session count, total tokens, total dollar cost, and
    outcome breakdown. Intentionally not Prometheus-formatted; this is a
    first-party JSON view of the meta-instrumentation harness.
    """
    session_logger = getattr(request.app.state, "session_logger", None)
    if session_logger is None:
        return {"status": "uninitialized", "records": 0}
    return session_logger.summarize()
