"""GRR (Graceful Refusal Rate) — out-of-scope questions × N systems."""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from docs.eval.scripts.aggregate import load_judge_grades


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--judge-glob", required=True)
    p.add_argument("--categories", type=Path, required=True)
    p.add_argument("--out", type=Path, default=Path("docs/eval/results/grr_table.md"))
    args = p.parse_args()

    cats_doc = yaml.safe_load(args.categories.read_text())
    cats = cats_doc["questions"] if isinstance(cats_doc, dict) else cats_doc
    oos_indices = {
        i for i, q in enumerate(cats)
        if q.get("is_out_of_scope") or q.get("category") == "out_of_scope"
    }

    lines = [
        "# GRR — out-of-scope subset",
        "",
        f"Out-of-scope indices ({len(oos_indices)} questions): "
        f"{sorted(oos_indices)}",
        "",
        "| System | n | GRR ↑ |",
        "|---|---:|---:|",
    ]
    for fp in sorted(glob.glob(args.judge_glob)):
        rows = load_judge_grades(Path(fp))
        if not rows:
            continue
        oos_rows = [r for r in rows if r["index"] in oos_indices]
        grr = [r["grr_score"] for r in oos_rows if r["grr_score"] is not None]
        if not grr:
            continue
        mean = sum(grr) / len(grr)
        lines.append(
            f"| {oos_rows[0]['system']} | {len(grr)} | {mean:.3f} |"
        )

    args.out.write_text("\n".join(lines) + "\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
