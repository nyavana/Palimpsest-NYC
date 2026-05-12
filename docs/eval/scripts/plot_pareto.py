"""Accuracy-vs-latency Pareto figure.

One point per system. X = median latency from the JSONL footers. Y = CCR
from the judge CSV.
"""

from __future__ import annotations

import argparse
import glob
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from docs.eval.scripts.aggregate import load_judge_grades, summarize_system


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--judge-glob", required=True)
    p.add_argument("--jsonl-dir", type=Path, default=Path("docs/eval/results"))
    p.add_argument("--out", type=Path, default=Path("docs/eval/results/pareto.png"))
    args = p.parse_args()

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    points: list[tuple[str, float, float]] = []
    for fp in sorted(glob.glob(args.judge_glob)):
        rows = load_judge_grades(Path(fp))
        if not rows:
            continue
        summary = summarize_system(rows)
        sys_name = summary["system"]
        ccr = summary["ccr_mean"] or 0.0

        stem = Path(fp).stem.removesuffix("-judged")
        jsonl_path = args.jsonl_dir / f"{stem}.jsonl"
        if not jsonl_path.exists():
            print(f"warning: no jsonl for {sys_name} (looked at {jsonl_path})", file=sys.stderr)
            continue
        latencies: list[float] = []
        for line in jsonl_path.read_text().splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if payload.get("type") != "row":
                continue
            lat = payload.get("latency_s")
            if lat is None:
                continue
            latencies.append(float(lat))
        if not latencies:
            continue
        p50 = statistics.median(latencies)
        points.append((sys_name, p50, ccr))

    if not points:
        raise SystemExit("no points to plot")

    fig, ax = plt.subplots(figsize=(7, 5))
    for name, lat, ccr in points:
        ax.scatter(lat, ccr, s=120)
        ax.annotate(name, (lat, ccr), xytext=(6, 6), textcoords="offset points", fontsize=9)
    ax.set_xlabel("latency p50 (s)")
    ax.set_ylabel("citation correctness rate")
    ax.set_title("Accuracy vs latency Pareto (manhattan-100)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(args.out, dpi=150)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
