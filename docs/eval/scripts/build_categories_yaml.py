"""Emit categories.yaml from the curated TSV. One entry per accepted question."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import yaml


def main(tsv_path: str, out_path: str) -> None:
    questions: list[dict] = []
    with Path(tsv_path).open(newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            if row.get("accept", "").strip().upper() != "Y":
                continue
            q = (row.get("edited_question") or "").strip() or row["question"].strip()
            questions.append({
                "question": q,
                "category": row["category"],
                "region": row.get("region") or "varied",
                "expected_source_types": [
                    s.strip()
                    for s in (row.get("expected_source_types") or "").split(",")
                    if s.strip()
                ],
                "is_out_of_scope": row["category"] == "out_of_scope",
            })

    Path(out_path).write_text(yaml.safe_dump({"questions": questions}, sort_keys=False))
    print(f"wrote {len(questions)} entries → {out_path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
