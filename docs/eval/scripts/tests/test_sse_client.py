from __future__ import annotations

import json

import httpx
import pytest

from docs.eval.scripts.sse_client import stream_agent_ask

pytestmark = pytest.mark.asyncio


def _sse_body(events: list[tuple[str, dict]]) -> bytes:
    lines: list[str] = []
    for name, data in events:
        lines.append(f"event: {name}")
        lines.append(f"data: {json.dumps(data)}")
        lines.append("")  # blank between frames
    return ("\n".join(lines) + "\n").encode("utf-8")


async def test_stream_agent_ask_posts_json_body_and_yields_frames():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["json"] = json.loads(request.content)
        body = _sse_body([
            ("turn", {"index": 0}),
            ("tool_call", {"name": "search_places", "args": {"query": "cathedral"}}),
            ("tool_result", {
                "name": "search_places",
                "result": {"results": [
                    {"doc_id": "wikipedia:Cathedral", "name": "Cathedral",
                     "source_type": "wikipedia", "source_url": "x",
                     "lat": 40.8, "lon": -73.96, "score": 0.71},
                ]},
            }),
            ("citations", {"citations": [{"doc_id": "wikipedia:Cathedral", "span": "x"}]}),
            ("done", {"result": {"narration": "Built in 1892…",
                                  "citations": [{"doc_id": "wikipedia:Cathedral",
                                                 "source_url": "x",
                                                 "source_type": "wikipedia",
                                                 "span": "Built in 1892",
                                                 "retrieval_turn": 1}],
                                  "verified": True, "turns": 2,
                                  "duration_s": 9.4}}),
        ])
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://x") as client:
        frames = [f async for f in stream_agent_ask(client, question="Q?", history=[])]

    assert captured["method"] == "POST"
    assert captured["url"].endswith("/agent/ask")
    assert captured["json"]["q"] == "Q?"
    assert captured["json"]["history"] == []
    event_names = [f["event"] for f in frames]
    assert event_names == ["turn", "tool_call", "tool_result", "citations", "done"]
    assert frames[2]["data"]["result"]["results"][0]["doc_id"] == "wikipedia:Cathedral"
