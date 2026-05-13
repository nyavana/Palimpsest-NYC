"""Per-region and per-source CCR bar charts.

Reads the per_region-<system>.csv / per_source-<system>.csv emitted by
aggregate.py and renders one bar chart per breakdown showing CCR mean per
group, with one cluster per system.
"""

from __future__ import annotations

import argparse
import csv
import glob
from pathlib import Path


def _load_breakdown(path: Path) -> tuple[list[str], list[float]]:
    """Returns (group_labels, ccr_means)."""
    groups: list[str] = []
    ccrs: list[float] = []
    with path.open() as fh:
        reader = csv.DictReader(fh)
        key = "region" if "region" in (reader.fieldnames or []) else "dominant_source"
        for row in reader:
            try:
                ccr = float(row.get("ccr_mean") or "nan")
            except ValueError:
                continue
            if ccr != ccr:  # NaN
                continue
            groups.append(row[key])
            ccrs.append(ccr)
    return groups, ccrs


def _plot(
    breakdown_glob: str,
    out_path: Path,
    title: str,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    files = sorted(glob.glob(breakdown_glob))
    if not files:
        raise SystemExit(f"no files match {breakdown_glob}")

    per_system: dict[str, dict[str, float]] = {}
    all_groups: list[str] = []
    seen: set[str] = set()
    for fp in files:
        path = Path(fp)
        # filename pattern: per_region-<system>.csv or per_source-<system>.csv
        sys_name = path.stem.split("-", 1)[1]
        groups, ccrs = _load_breakdown(path)
        per_system[sys_name] = dict(zip(groups, ccrs))
        for g in groups:
            if g not in seen:
                seen.add(g)
                all_groups.append(g)

    n_groups = len(all_groups)
    n_systems = len(per_system)
    if n_groups == 0 or n_systems == 0:
        raise SystemExit("no data")
    bar_w = 0.8 / n_systems
    fig, ax = plt.subplots(figsize=(max(8, n_groups * 1.2), 5))
    x = np.arange(n_groups)
    for i, (sys_name, scores) in enumerate(sorted(per_system.items())):
        vals = [scores.get(g, 0.0) for g in all_groups]
        ax.bar(x + i * bar_w, vals, bar_w, label=sys_name)
    ax.set_xticks(x + bar_w * (n_systems - 1) / 2)
    ax.set_xticklabels(all_groups, rotation=30, ha="right")
    ax.set_ylabel("CCR mean")
    ax.set_title(title)
    ax.set_ylim(0, 1.0)
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(fontsize=8, loc="upper right")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"wrote {out_path}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--kind", choices=["region", "source"], required=True)
    p.add_argument("--inputs-dir", type=Path, default=Path("docs/eval/results"))
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()

    if args.kind == "region":
        _plot(
            str(args.inputs_dir / "per_region-*.csv"),
            args.out,
            "Per-region CCR (manhattan-100)",
        )
    else:
        _plot(
            str(args.inputs_dir / "per_source-*.csv"),
            args.out,
            "Per-source CCR (manhattan-100)",
        )


if __name__ == "__main__":
    main()
