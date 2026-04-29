"""Compare two eval JSONL runs side-by-side.

Used for §13.6 router cost analysis: produce a markdown table with
$/walk, latency, citation rate, and verifier success rate for each
model configuration.

Usage::

    python docs/eval/scripts/compare_runs.py \\
        docs/eval/results/router-bench-paid-kimi-*.jsonl \\
        docs/eval/results/router-bench-free-gemma-*.jsonl
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any


def _load(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    header = next(r for r in rows if r.get("type") == "header")
    footer = next(r for r in rows if r.get("type") == "footer")
    data = [r for r in rows if r.get("type") == "row"]
    return header, data, footer


def _stat(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    verified = [r for r in rows if r.get("verified") is True]
    has_walk = [r for r in rows if (r.get("walk_stops") or [])]
    has_cit = [r for r in rows if (r.get("citations") or [])]
    latencies = [r.get("client_latency_s") for r in rows if r.get("client_latency_s")]
    server_durs = [r.get("server_duration_s") for r in rows if r.get("server_duration_s")]
    turn_counts = [r.get("turns") for r in rows if isinstance(r.get("turns"), int)]
    cit_counts = [len(r.get("citations") or []) for r in rows]
    walk_dists = [r.get("walk_total_distance_m") for r in rows if r.get("walk_total_distance_m")]

    def _med(xs: list[float | int]) -> float | None:
        return round(statistics.median(xs), 2) if xs else None

    return {
        "n": n,
        "verified_rate": round(len(verified) / n, 3) if n else 0,
        "walk_rate": round(len(has_walk) / n, 3) if n else 0,
        "citation_rate": round(len(has_cit) / n, 3) if n else 0,
        "median_latency_s": _med(latencies),
        "median_server_duration_s": _med(server_durs),
        "median_turns": _med(turn_counts),
        "median_citations_per_walk": _med(cit_counts),
        "median_walk_distance_m": _med(walk_dists),
    }


def _telemetry(footer: dict[str, Any]) -> dict[str, Any]:
    summ = footer.get("llm_telemetry_summary") or {}
    total_cost = sum(v.get("cost_usd", 0) for v in summ.values())
    total_calls = sum(v.get("calls", 0) for v in summ.values())
    total_prompt = sum(v.get("prompt_tokens", 0) for v in summ.values())
    total_completion = sum(v.get("completion_tokens", 0) for v in summ.values())
    return {
        "total_cost_usd": round(total_cost, 4),
        "total_calls": total_calls,
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "models": summ,
    }


def _md_row(label: str, h: dict[str, Any], stat: dict[str, Any], tel: dict[str, Any], n: int) -> str:
    cost_per_walk = round(tel["total_cost_usd"] / n, 4) if n else 0
    return (
        f"| **{label}** | {tel['total_cost_usd']:.4f} | "
        f"{cost_per_walk:.4f} | "
        f"{tel['total_calls']} | "
        f"{tel['total_prompt_tokens']:,} / {tel['total_completion_tokens']:,} | "
        f"{stat['median_latency_s']} | "
        f"{stat['median_turns']} | "
        f"{int(stat['verified_rate'] * 100)}% | "
        f"{int(stat['walk_rate'] * 100)}% | "
        f"{stat['median_citations_per_walk']} | "
        f"{stat['median_walk_distance_m']} |"
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("runs", type=Path, nargs="+", help="One or more JSONL run files.")
    p.add_argument("--out", type=Path, default=None, help="Optional output markdown file.")
    args = p.parse_args()

    out_lines: list[str] = []

    out_lines.append("# Router Cost Analysis (§13.6)\n")
    out_lines.append("")
    out_lines.append(
        "| Run | Total $ | $/walk | LLM calls | Prompt / Completion tok | "
        "Median latency (s) | Median turns | Verified | Walks rendered | "
        "Median citations | Median walk dist (m) |"
    )
    out_lines.append(
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    )

    for path in args.runs:
        header, rows, footer = _load(path)
        stat = _stat(rows)
        tel = _telemetry(footer)
        out_lines.append(_md_row(header["label"], header, stat, tel, header["n_questions"]))

    out_lines.append("")
    out_lines.append("## Per-run details\n")
    for path in args.runs:
        header, rows, footer = _load(path)
        stat = _stat(rows)
        tel = _telemetry(footer)
        out_lines.append(f"### {header['label']}\n")
        out_lines.append(f"- File: `{path}`")
        out_lines.append(f"- Started: {header['started_at']} → {footer['ended_at']}")
        out_lines.append(f"- Total LLM cost: **${tel['total_cost_usd']:.4f}**")
        out_lines.append(f"- LLM calls: {tel['total_calls']}")
        out_lines.append(
            f"- Tokens: {tel['total_prompt_tokens']:,} prompt + "
            f"{tel['total_completion_tokens']:,} completion"
        )
        out_lines.append(f"- Stats: {json.dumps(stat)}")
        out_lines.append(f"- Models: {sorted(tel['models'].keys())}")
        out_lines.append("")
        out_lines.append("Per-question outcomes:")
        out_lines.append("")
        for r in rows:
            cit_count = len(r.get("citations") or [])
            walk_count = len(r.get("walk_stops") or [])
            verified = r.get("verified")
            ver_label = (
                "✅ verified" if verified is True
                else "⚠️ unverified" if verified is False
                else "❌ no terminal"
            )
            warn = r.get("verifier_warning") or (r.get("warnings") or [None])[0] or ""
            out_lines.append(
                f"  {r['index']}. *{r['question'][:78]}* — {ver_label}, "
                f"{cit_count} citations, {walk_count} stops, "
                f"latency {r['client_latency_s']}s"
                + (f" — `{warn}`" if warn else "")
            )
        out_lines.append("")

    md = "\n".join(out_lines) + "\n"
    if args.out:
        args.out.write_text(md)
        print(f"✔ wrote {args.out}")
    else:
        print(md)


if __name__ == "__main__":
    main()
