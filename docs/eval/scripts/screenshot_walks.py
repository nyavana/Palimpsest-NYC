"""Replay each saved walk through the running web frontend via Playwright +
SSE mock, take a screenshot per walk.

Used by §13.4 to deliver "capture screenshots" without re-running paid LLM
calls. Each walk's JSONL row is converted to a synthetic SSE body matching
the real /api/agent/ask frame format.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


def _build_sse_body(row: dict[str, Any]) -> str:
    """Construct an SSE body that matches what the live backend would emit
    for the same walk. We synthesize: turn(s), citations, walk, done.

    Order matters — the frontend reducer reads them sequentially.
    """
    frames: list[str] = []

    def emit(event: str, payload: dict[str, Any]) -> None:
        frames.append(f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}")

    turns = row.get("turns") or 1
    for tc in row.get("tool_calls") or []:
        emit("tool_call", {"name": tc.get("name") or "search_places", "args": tc.get("args") or {}})

    if row.get("max_turn_index"):
        emit("turn", {"index": row["max_turn_index"]})

    if row.get("narration"):
        emit("narration", {"text": row["narration"]})

    if row.get("citations"):
        emit("citations", {"citations": row["citations"]})

    if row.get("walk_stops"):
        emit("walk", {"stops": row["walk_stops"]})

    for w in row.get("warnings") or []:
        emit("warning", {"message": w})

    result = {
        "narration": row.get("narration") or "",
        "citations": row.get("citations") or [],
        "verified": row.get("verified") if row.get("verified") is not None else False,
        "warning": row.get("verifier_warning"),
        "turns": turns,
        "duration_s": row.get("server_duration_s") or row.get("client_latency_s") or 0,
    }
    emit("done", {"result": result})

    return "\n\n".join(frames) + "\n\n"


def _esc(s: str) -> str:
    """JSON-string-escape so we can embed the body in a JS template literal
    via run-code."""
    return json.dumps(s)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("jsonl", type=Path)
    p.add_argument("--out-dir", type=Path, default=Path("docs/eval/screenshots/qualitative"))
    p.add_argument("--frontend", default="http://localhost:5173/")
    args = p.parse_args()

    rows = [json.loads(l) for l in args.jsonl.read_text().splitlines() if l.strip()]
    walks = [r for r in rows if r.get("type") == "row"]
    args.out_dir.mkdir(parents=True, exist_ok=True)

    # The web container's proxy directory is the only file root playwright-cli
    # is allowed to read. Stage the mock body there.
    sandbox = Path("apps/web/.playwright-cli")
    sandbox.mkdir(parents=True, exist_ok=True)

    cli = ["npx", "--no-install", "playwright-cli"]

    def run(*argv: str) -> str:
        return subprocess.run(
            list(cli) + list(argv),
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    for w in walks:
        idx = w["index"]
        body = _build_sse_body(w)
        body_js = _esc(body)
        # Set up the route and reload the page; the EventSource opens
        # immediately on mount, so the mocked frames stream through.
        run(
            "unroute",
        )
        run(
            "run-code",
            (
                "async (page) => { "
                "await page.context().route('**/api/agent/ask*', async (route) => { "
                "  await route.fulfill({ status: 200, contentType: 'text/event-stream', body: "
                f"{body_js}"
                " }); "
                "}); "
                "}"
            ),
        )
        run("goto", args.frontend)
        # Use the textbox to "ask" so the EventSource is opened with the
        # session reducer in 'asking' state. Question comes from the row.
        snap = run("snapshot")
        # Parse refs out of snapshot to find textbox + ask button.
        textbox = None
        button = None
        for line in snap.splitlines():
            if "textbox" in line and "ref=e" in line:
                textbox = line.split("ref=")[1].split("]")[0].strip()
            if 'button "Ask"' in line and "ref=e" in line:
                button = line.split("ref=")[1].split("]")[0].strip()
        if textbox is None or button is None:
            raise SystemExit(f"Could not find composer in snapshot for walk {idx}")
        run("fill", textbox, w["question"])
        run("click", button)
        # Brief settling delay for the mock SSE to flow through.
        run("eval", "() => new Promise((r) => setTimeout(r, 1500))")
        out = args.out_dir / f"q{idx}.png"
        # screenshot must land inside the sandbox; copy it out after.
        run("screenshot", "--filename", f"qual-q{idx}.png")
        sandbox_png = Path("apps/web/qual-q{idx}.png".format(idx=idx))
        if sandbox_png.exists():
            sandbox_png.replace(out)
            print(f"✔ wrote {out}")
        else:
            print(f"⚠ screenshot not found for walk {idx}")


if __name__ == "__main__":
    main()
