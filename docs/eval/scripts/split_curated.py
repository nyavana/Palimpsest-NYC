"""Reads a curated TSV (accept=Y rows) and emits one .txt per category."""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

CATEGORY_TO_FILE = {
    "single_place": "single-place.txt",
    "multi_place": "multi-place.txt",
    "geographic": "geographic.txt",
    "per_neighborhood": "per-neighborhood.txt",
    "out_of_scope": "out-of-scope.txt",
}


def main(tsv_path: str, out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    buckets: dict[str, list[str]] = defaultdict(list)
    with Path(tsv_path).open(newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            if row.get("accept", "").strip().upper() != "Y":
                continue
            q = (row.get("edited_question") or "").strip() or row["question"].strip()
            buckets[row["category"]].append(q)

    for cat, fname in CATEGORY_TO_FILE.items():
        path = out / fname
        with path.open("w") as fh:
            for q in buckets.get(cat, []):
                fh.write(q + "\n")
        print(f"{cat}: {len(buckets.get(cat, []))} → {path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
