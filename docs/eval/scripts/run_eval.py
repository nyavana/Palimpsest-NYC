"""Eval harness — runs N agent asks against the live SSE endpoint and writes
results to a JSONL file for analysis.

Per task §13.4 (qualitative review of 5 walks) and §13.6 (router cost
analysis ~10 walks). Captures per-question:

  - question
  - all SSE event types in order (turns, tool calls, narration, citations,
    walk, warnings, done)
  - terminal narration + citations + walk
  - verifier outcome (verified flag + warning string)
  - wall-clock latency (request → terminal `done`)
  - server-reported `duration_s` and `turns`

Cost / token totals are pulled from `/internal/metrics` before and after the
batch and the delta is written into the run summary.

Usage::

    docker compose exec api python -m scripts.run_eval \
        --questions docs/eval/questions/v1-qualitative.txt \
        --label v1-qualitative \
        --out docs/eval/results

Run from inside the api container so the ``/internal/metrics`` log dir
(``/app/logs/claude-sessions``) is local — but it also works from the host
since both endpoints are exposed on ``localhost:8000``.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import time
from collections.abc import AsyncIterator, Iterable
from pathlib import Path
from typing import Any

import httpx


@dataclasses.dataclass(slots=True)
class Frame:
    event: str
    data: dict[str, Any]


async def _stream_sse(client: httpx.AsyncClient, q: str) -> AsyncIterator[Frame]:
    """Stream the SSE response, parsing event/data pairs."""
    async with client.stream(
        "GET",
        "/agent/ask",
        params={"q": q},
        timeout=httpx.Timeout(300.0, read=300.0),
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
                yield Frame(event_name, data)


def _verifier_outcome(events: list[Frame]) -> tuple[bool | None, str | None]:
    """Pull verified flag + warning from the terminal `done` frame, if any."""
    for ev in reversed(events):
        if ev.event != "done":
            continue
        result = ev.data.get("result") if isinstance(ev.data, dict) else None
        if result is None:
            return (None, None)
        return (result.get("verified"), result.get("warning"))
    return (None, None)


def _terminal_result(events: list[Frame]) -> dict[str, Any] | None:
    for ev in reversed(events):
        if ev.event == "done":
            return (ev.data or {}).get("result")
    return None


def _walk(events: list[Frame]) -> list[dict[str, Any]]:
    for ev in reversed(events):
        if ev.event == "walk":
            return list((ev.data or {}).get("stops") or [])
    return []


async def _run_one(client: httpx.AsyncClient, q: str) -> dict[str, Any]:
    started_at = time.perf_counter()
    events: list[Frame] = []
    error: str | None = None
    try:
        async for ev in _stream_sse(client, q):
            events.append(ev)
            if ev.event == "done":
                break
    except httpx.HTTPError as exc:
        error = f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - started_at

    result = _terminal_result(events)
    verified, warning = _verifier_outcome(events)
    walk = _walk(events)

    tool_calls = [ev.data for ev in events if ev.event == "tool_call"]
    warnings = [ev.data.get("message") for ev in events if ev.event == "warning"]
    turn_indices = [
        ev.data.get("index") for ev in events if ev.event == "turn"
    ]
    turn_indices = [t for t in turn_indices if isinstance(t, int)]

    return {
        "question": q,
        "client_latency_s": round(elapsed, 3),
        "server_duration_s": (result or {}).get("duration_s"),
        "turns": (result or {}).get("turns"),
        "max_turn_index": max(turn_indices) if turn_indices else None,
        "tool_call_count": len(tool_calls),
        "tool_calls": [
            {"name": t.get("name"), "args": t.get("args")}
            for t in tool_calls
        ],
        "verified": verified,
        "verifier_warning": warning,
        "warnings": [w for w in warnings if w],
        "narration_chars": len((result or {}).get("narration") or ""),
        "narration": (result or {}).get("narration"),
        "citations": (result or {}).get("citations") or [],
        "walk_stops": walk,
        "walk_total_distance_m": round(
            sum(s.get("leg_distance_m", 0.0) for s in walk),
            1,
        ),
        "error": error,
    }


async def _fetch_metrics(client: httpx.AsyncClient) -> dict[str, Any]:
    try:
        r = await client.get("/internal/metrics", timeout=15.0)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as exc:
        return {"error": str(exc)}


def _read_llm_telemetry(redis_url: str | None = None) -> list[dict[str, Any]]:
    """Pull every record currently in the LLM telemetry Redis list.

    The router writes one record per call (to ``llm:telemetry:v1``, capped at
    10k entries). LPUSH stores newest-first, so the list reads newest→oldest.
    """
    if redis_url is None:
        return []
    try:
        import redis  # type: ignore[import-not-found]
    except ImportError:
        return [{"error": "redis package not installed on host"}]
    try:
        r = redis.from_url(redis_url, decode_responses=True)
        raw = r.lrange("llm:telemetry:v1", 0, -1)
        out: list[dict[str, Any]] = []
        for entry in raw:
            try:
                out.append(json.loads(entry))
            except json.JSONDecodeError:
                continue
        return out
    except Exception as exc:  # noqa: BLE001
        return [{"error": f"redis read failed: {exc}"}]


def _summarize_telemetry(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_model: dict[str, dict[str, Any]] = {}
    for r in records:
        if not isinstance(r, dict) or r.get("error"):
            continue
        model = r.get("model") or "<unknown>"
        slot = by_model.setdefault(
            model,
            {
                "calls": 0,
                "cached": 0,
                "errors": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "cost_usd": 0.0,
                "latency_ms_sum": 0.0,
                "complexities": set(),
                "backends": set(),
            },
        )
        slot["calls"] += 1
        if r.get("cached"):
            slot["cached"] += 1
        if r.get("error_code"):
            slot["errors"] += 1
        slot["prompt_tokens"] += int(r.get("prompt_tokens") or 0)
        slot["completion_tokens"] += int(r.get("completion_tokens") or 0)
        slot["cost_usd"] += float(r.get("cost_usd") or 0.0)
        slot["latency_ms_sum"] += float(r.get("latency_ms") or 0.0)
        if r.get("complexity"):
            slot["complexities"].add(r["complexity"])
        if r.get("backend"):
            slot["backends"].add(r["backend"])
    out: dict[str, Any] = {}
    for model, slot in by_model.items():
        n = slot["calls"]
        out[model] = {
            "calls": n,
            "cached": slot["cached"],
            "errors": slot["errors"],
            "prompt_tokens": slot["prompt_tokens"],
            "completion_tokens": slot["completion_tokens"],
            "cost_usd": round(slot["cost_usd"], 6),
            "avg_latency_ms": round(slot["latency_ms_sum"] / n, 1) if n else None,
            "complexities": sorted(slot["complexities"]),
            "backends": sorted(slot["backends"]),
        }
    return out


async def run_eval(
    questions: Iterable[str],
    *,
    base_url: str,
    label: str,
    out_dir: Path,
    redis_url: str | None = None,
    clear_telemetry: bool = False,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    started_at = time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())
    out_file = out_dir / f"{label}-{started_at}.jsonl"

    questions = list(questions)
    print(
        f"→ {len(questions)} questions · base_url={base_url} · label={label}"
    )

    if clear_telemetry and redis_url:
        try:
            import redis  # type: ignore[import-not-found]

            r = redis.from_url(redis_url, decode_responses=True)
            r.delete("llm:telemetry:v1")
            cache_keys = list(r.scan_iter(match="llm:cache:v1:*"))
            if cache_keys:
                r.delete(*cache_keys)
            print(
                f"→ cleared llm:telemetry:v1 + {len(cache_keys)} llm cache keys",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  (could not clear telemetry: {exc})", flush=True)

    async with httpx.AsyncClient(base_url=base_url, follow_redirects=False) as client:
        metrics_before = await _fetch_metrics(client)
        telemetry_count_before = len(_read_llm_telemetry(redis_url))

        with out_file.open("w", encoding="utf-8") as fh:
            header = {
                "type": "header",
                "label": label,
                "started_at": started_at,
                "base_url": base_url,
                "n_questions": len(questions),
                "metrics_before": metrics_before,
            }
            fh.write(json.dumps(header) + "\n")

            for i, q in enumerate(questions, 1):
                print(f"[{i}/{len(questions)}] {q[:80]}…", flush=True)
                row = await _run_one(client, q)
                row.update({"type": "row", "label": label, "index": i})
                fh.write(json.dumps(row) + "\n")
                fh.flush()
                # Light cooldown to be polite to OpenRouter rate limits.
                await asyncio.sleep(1.0)

            metrics_after = await _fetch_metrics(client)
            telemetry_after = _read_llm_telemetry(redis_url)
            telemetry_window = (
                telemetry_after[: len(telemetry_after) - telemetry_count_before]
                if not clear_telemetry
                else telemetry_after
            )
            footer = {
                "type": "footer",
                "label": label,
                "ended_at": time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime()),
                "metrics_after": metrics_after,
                "metrics_delta": _metric_delta(metrics_before, metrics_after),
                "llm_telemetry_count": len(telemetry_window),
                "llm_telemetry_summary": _summarize_telemetry(telemetry_window),
                "llm_telemetry_records": telemetry_window,
            }
            fh.write(json.dumps(footer) + "\n")

    print(f"✔ wrote {out_file}")
    return out_file


def _metric_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    keys = ("total_prompt_tokens", "total_completion_tokens", "total_cost_usd", "records")
    delta: dict[str, Any] = {}
    for k in keys:
        a = after.get(k) or 0
        b = before.get(k) or 0
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            delta[k] = round(a - b, 6) if isinstance(a, float) else a - b
    return delta


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--questions",
        type=Path,
        required=True,
        help="Path to a text file (one question per line, blank/# lines ignored).",
    )
    p.add_argument("--label", required=True, help="Label for this run, used in filename.")
    p.add_argument(
        "--out",
        type=Path,
        default=Path("docs/eval/results"),
        help="Output directory.",
    )
    p.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Backend base URL (default: http://localhost:8000).",
    )
    p.add_argument(
        "--redis-url",
        default="redis://localhost:6379/0",
        help="Redis URL for reading LLM telemetry stream (set to empty to skip).",
    )
    p.add_argument(
        "--clear-telemetry",
        action="store_true",
        help="Clear llm:telemetry:v1 before running (use for clean batch boundaries).",
    )
    return p.parse_args()


def _read_questions(path: Path) -> list[str]:
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.append(s)
    return out


def main() -> None:
    args = _parse_args()
    questions = _read_questions(args.questions)
    if not questions:
        raise SystemExit(f"No questions in {args.questions}")
    asyncio.run(
        run_eval(
            questions,
            base_url=args.base_url,
            label=args.label,
            out_dir=args.out,
            redis_url=args.redis_url or None,
            clear_telemetry=args.clear_telemetry,
        )
    )


if __name__ == "__main__":
    main()
