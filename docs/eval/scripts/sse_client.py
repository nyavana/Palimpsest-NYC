"""POST + JSON SSE client for /agent/ask.

The live route in apps/api/app/routes/agent.py is POST with an AskBody JSON
({q, history}); the original run_eval.py still uses a deprecated GET form
and is intentionally not reused.

Public API:
    async for frame in stream_agent_ask(client, question="…", history=[]):
        ...

`frame` is a dict {"event": str, "data": dict}. Each frame mirrors one
`event: <type>\\ndata: <json>` block on the wire.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx


async def stream_agent_ask(
    client: httpx.AsyncClient,
    *,
    question: str,
    history: list[dict[str, str]] | None = None,
    headers: dict[str, str] | None = None,
    timeout_s: float = 300.0,
) -> AsyncIterator[dict[str, Any]]:
    body = {"q": question, "history": history or []}
    req_headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if headers:
        req_headers.update(headers)
    async with client.stream(
        "POST",
        "/agent/ask",
        json=body,
        headers=req_headers,
        timeout=httpx.Timeout(timeout_s, read=timeout_s),
    ) as resp:
        resp.raise_for_status()
        event_name: str | None = None
        async for line in resp.aiter_lines():
            if not line:
                event_name = None
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event_name = line.removeprefix("event:").strip()
            elif line.startswith("data:") and event_name:
                payload = line.removeprefix("data:").strip()
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    data = {"raw": payload}
                yield {"event": event_name, "data": data}
