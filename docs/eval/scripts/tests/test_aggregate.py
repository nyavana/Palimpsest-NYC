"""Tests for ``docs/eval/scripts/aggregate.py``.

Covers the deterministic plumbing the canonical plan calls out (Phase 3.4 +
the Phase 6 helpers ``per_region_breakdown`` / ``per_source_breakdown``),
plus the project-specific deviation: hand grades are optional. When the
caller doesn't pass ``--hand-grades`` (or the file is missing) the
aggregator still produces ``ablation_table.md`` and records
``kappa: null (no hand grades)`` instead of crashing.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from docs.eval.scripts.aggregate import (
    attach_citation_source_types,
    bootstrap_ci95_mean,
    cohen_kappa_binary,
    load_judge_grades,
    per_region_breakdown,
    per_source_breakdown,
    run_aggregate,
    summarize_system,
    write_ablation_markdown,
)


def _write_csv(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for r in rows:
            w.writerow(r)


JUDGE_HEADER = [
    "system", "index", "question",
    "ccr_score", "hr_score", "fa_score", "nq_score", "grr_score",
    "ccr_reasoning", "hr_reasoning", "fa_reasoning", "nq_reasoning", "grr_reasoning",
    "error",
]


# -------- load_judge_grades --------------------------------------------------


def test_load_judge_grades_parses_csv(tmp_path: Path) -> None:
    p = tmp_path / "g.csv"
    _write_csv(
        p,
        JUDGE_HEADER,
        [
            ["vanilla", 0, "Q0", 0.0, 0.6, 0.5,  3.0, None, "", "", "", "", "", ""],
            ["vanilla", 1, "Q1", 0.5, 0.3, None, 4.0, None, "", "", "", "", "", ""],
        ],
    )
    rows = load_judge_grades(p)
    assert len(rows) == 2
    assert rows[0]["ccr_score"] == 0.0
    assert rows[1]["fa_score"] is None
    assert rows[0]["system"] == "vanilla"
    assert rows[0]["index"] == 0


def test_load_judge_grades_treats_empty_and_none_strings_as_missing(tmp_path: Path) -> None:
    p = tmp_path / "g.csv"
    _write_csv(
        p,
        JUDGE_HEADER,
        [
            ["vanilla", 0, "Q0", "", "None", "0.4", "2.5", "", "", "", "", "", "", ""],
        ],
    )
    rows = load_judge_grades(p)
    assert rows[0]["ccr_score"] is None
    assert rows[0]["hr_score"] is None
    assert rows[0]["fa_score"] == 0.4
    assert rows[0]["nq_score"] == 2.5
    assert rows[0]["grr_score"] is None


# -------- summarize_system ---------------------------------------------------


def test_summarize_system_means_and_n() -> None:
    rows = [
        {"system": "vanilla", "index": 0, "ccr_score": 0.0, "hr_score": 1.0,
         "fa_score": 0.5, "nq_score": 3.0, "grr_score": None},
        {"system": "vanilla", "index": 1, "ccr_score": 0.0, "hr_score": 0.8,
         "fa_score": None, "nq_score": 4.0, "grr_score": None},
    ]
    s = summarize_system(rows)
    assert s["system"] == "vanilla"
    assert s["n"] == 2
    assert s["ccr_mean"] == 0.0
    assert s["hr_mean"] == 0.9
    assert s["fa_mean"] == 0.5
    assert s["nq_mean"] == 3.5
    assert s["grr_mean"] is None


def test_summarize_system_handles_empty_rows() -> None:
    s = summarize_system([])
    assert s["n"] == 0
    assert s["system"] is None
    assert s["ccr_mean"] is None


# -------- bootstrap_ci95_mean ------------------------------------------------


def test_bootstrap_ci95_constant_sample_is_degenerate() -> None:
    lo, hi = bootstrap_ci95_mean([0.5] * 10, seed=42, n_resamples=200)
    assert lo == 0.5
    assert hi == 0.5


def test_bootstrap_ci95_brackets_population_mean() -> None:
    # Symmetric small sample; the percentile bootstrap should bracket the mean.
    sample = [0.0, 0.25, 0.5, 0.75, 1.0]
    lo, hi = bootstrap_ci95_mean(sample, seed=7, n_resamples=500)
    assert lo <= 0.5 <= hi
    assert lo >= 0.0
    assert hi <= 1.0


def test_bootstrap_ci95_empty_returns_none_pair() -> None:
    assert bootstrap_ci95_mean([], seed=0) == (None, None)


# -------- cohen_kappa_binary -------------------------------------------------


def test_cohen_kappa_perfect_agreement() -> None:
    hand = [1, 0, 1, 0, 1]
    judge = [1, 0, 1, 0, 1]
    assert cohen_kappa_binary(hand, judge) == 1.0


def test_cohen_kappa_chance_agreement() -> None:
    hand = [1, 0, 1, 0, 1, 0]
    judge = [0, 1, 0, 1, 0, 1]
    # All disagreements -> negative kappa.
    assert cohen_kappa_binary(hand, judge) < 0.0


def test_cohen_kappa_all_same_label_collapses_to_observed() -> None:
    # Both raters say 1 every time -> p_e = 1.0 and p_o = 1.0 -> kappa = 1.0.
    assert cohen_kappa_binary([1, 1, 1, 1], [1, 1, 1, 1]) == 1.0


# -------- per_region_breakdown ----------------------------------------------


def test_per_region_breakdown_groups_by_categories_yaml() -> None:
    # 4 rows: 2 in Harlem, 2 in Midtown.
    rows = [
        {"system": "palimpsest-dense", "index": 0, "ccr_score": 1.0, "hr_score": 0.0,
         "fa_score": None, "nq_score": 5.0, "grr_score": None},
        {"system": "palimpsest-dense", "index": 1, "ccr_score": 0.5, "hr_score": 0.4,
         "fa_score": None, "nq_score": 4.0, "grr_score": None},
        {"system": "palimpsest-dense", "index": 2, "ccr_score": 0.0, "hr_score": 1.0,
         "fa_score": None, "nq_score": 3.0, "grr_score": None},
        {"system": "palimpsest-dense", "index": 3, "ccr_score": 0.0, "hr_score": 0.8,
         "fa_score": None, "nq_score": 3.5, "grr_score": None},
    ]
    categories = [
        {"question": "Q0", "category": "single_place", "region": "Harlem"},
        {"question": "Q1", "category": "single_place", "region": "Harlem"},
        {"question": "Q2", "category": "single_place", "region": "Midtown"},
        {"question": "Q3", "category": "single_place", "region": "Midtown"},
    ]
    table = per_region_breakdown(rows, categories)
    by_region = {row["region"]: row for row in table}
    assert by_region["Harlem"]["ccr_mean"] == 0.75
    assert by_region["Midtown"]["ccr_mean"] == 0.0
    assert by_region["Harlem"]["n"] == 2


# -------- per_source_breakdown ----------------------------------------------


def test_per_source_breakdown_groups_by_citation_source_type() -> None:
    rows = [
        {"system": "s", "index": 0, "ccr_score": 1.0, "hr_score": 0.0,
         "fa_score": None, "nq_score": 5.0, "grr_score": None,
         "citation_source_types": ["wikipedia", "wikipedia"]},
        {"system": "s", "index": 1, "ccr_score": 0.5, "hr_score": 0.5,
         "fa_score": None, "nq_score": 4.0, "grr_score": None,
         "citation_source_types": ["osm", "osm"]},
        {"system": "s", "index": 2, "ccr_score": 0.7, "hr_score": 0.2,
         "fa_score": None, "nq_score": 4.5, "grr_score": None,
         "citation_source_types": ["wikipedia", "osm"]},
    ]
    table = per_source_breakdown(rows)
    by_source = {row["dominant_source"]: row for row in table}
    assert "wikipedia" in by_source
    assert "osm" in by_source
    # Row 0 is purely wikipedia, row 2 ties and breaks alphabetically -> osm.
    assert by_source["wikipedia"]["ccr_mean"] == 1.0


def test_attach_citation_source_types_reads_jsonl(tmp_path: Path) -> None:
    jl = tmp_path / "r.jsonl"
    lines = [
        json.dumps({"type": "header", "system": "s"}),
        json.dumps({
            "type": "row", "index": 0, "question": "Q0",
            "citations": [{"source_type": "wikipedia"}, {"source_type": "wikipedia"}],
        }),
        json.dumps({
            "type": "row", "index": 1, "question": "Q1",
            "citations": [{"source_type": "osm"}],
        }),
        json.dumps({"type": "footer"}),
    ]
    jl.write_text("\n".join(lines) + "\n")
    judge_rows = [
        {"system": "s", "index": 0, "ccr_score": 0.5, "hr_score": None,
         "fa_score": None, "nq_score": None, "grr_score": None},
        {"system": "s", "index": 1, "ccr_score": 0.5, "hr_score": None,
         "fa_score": None, "nq_score": None, "grr_score": None},
    ]
    merged = attach_citation_source_types(judge_rows, jl)
    assert merged[0]["citation_source_types"] == ["wikipedia", "wikipedia"]
    assert merged[1]["citation_source_types"] == ["osm"]


# -------- write_ablation_markdown -------------------------------------------


def test_write_ablation_markdown_records_table(tmp_path: Path) -> None:
    out = tmp_path / "ablation_table.md"
    write_ablation_markdown(
        out,
        [
            {"system": "vanilla", "n": 2,
             "ccr_mean": 0.0, "hr_mean": 0.9, "fa_mean": 0.5,
             "nq_mean": 3.5, "grr_mean": None,
             "ccr_ci95": (0.0, 0.0), "hr_ci95": (0.8, 1.0),
             "fa_ci95": (0.5, 0.5), "nq_ci95": (3.0, 4.0),
             "grr_ci95": (None, None)},
        ],
        kappa=None,
    )
    text = out.read_text()
    assert "Ablation table" in text
    assert "| vanilla |" in text
    assert "kappa: null (no hand grades)" in text


def test_write_ablation_markdown_records_kappa_when_present(tmp_path: Path) -> None:
    out = tmp_path / "ablation_table.md"
    write_ablation_markdown(
        out,
        [
            {"system": "vanilla", "n": 1,
             "ccr_mean": 0.0, "hr_mean": 0.5, "fa_mean": None,
             "nq_mean": 3.0, "grr_mean": None,
             "ccr_ci95": (0.0, 0.0), "hr_ci95": (0.5, 0.5),
             "fa_ci95": (None, None), "nq_ci95": (3.0, 3.0),
             "grr_ci95": (None, None)},
        ],
        kappa=0.812,
        kappa_n=20,
    )
    text = out.read_text()
    assert "kappa(CCR, threshold=0.5)" in text
    assert "0.812" in text
    assert "n=20" in text


# -------- run_aggregate (integration; honours optional hand grades) ---------


def _seed_judged_csv(path: Path, system: str) -> None:
    _write_csv(
        path,
        JUDGE_HEADER,
        [
            [system, 0, "Q0", 1.0, 0.0, 0.8, 5.0, None, "", "", "", "", "", ""],
            [system, 1, "Q1", 0.5, 0.4, 0.6, 4.0, None, "", "", "", "", "", ""],
            [system, 2, "Q2", 0.0, 1.0, 0.2, 3.0, None, "", "", "", "", "", ""],
        ],
    )


def test_run_aggregate_no_hand_grades_emits_table_and_null_kappa(tmp_path: Path) -> None:
    judge_dir = tmp_path / "grades"
    judge_dir.mkdir()
    _seed_judged_csv(judge_dir / "phase3-vanilla-judged.csv", "vanilla")
    _seed_judged_csv(judge_dir / "phase3-naive_rag-judged.csv", "naive_rag")

    out = tmp_path / "results" / "ablation_table.md"
    result = run_aggregate(
        inputs_glob=str(judge_dir / "phase3-*-judged.csv"),
        out_path=out,
        hand_grades_path=None,  # <-- the project deviation
        categories_path=None,
    )
    assert out.exists()
    text = out.read_text()
    assert "vanilla" in text
    assert "naive_rag" in text
    # No hand grades -> kappa must be recorded as null.
    assert result["kappa"] is None
    assert "kappa: null (no hand grades)" in text


def test_run_aggregate_missing_hand_grades_file_falls_back_gracefully(tmp_path: Path) -> None:
    judge_dir = tmp_path / "grades"
    judge_dir.mkdir()
    _seed_judged_csv(judge_dir / "phase3-vanilla-judged.csv", "vanilla")

    out = tmp_path / "results" / "ablation_table.md"
    result = run_aggregate(
        inputs_glob=str(judge_dir / "phase3-*-judged.csv"),
        out_path=out,
        hand_grades_path=tmp_path / "does-not-exist.csv",
        categories_path=None,
    )
    assert result["kappa"] is None
    assert "kappa: null (no hand grades)" in out.read_text()


def test_run_aggregate_with_hand_grades_computes_kappa(tmp_path: Path) -> None:
    judge_dir = tmp_path / "grades"
    judge_dir.mkdir()
    # System answers: indices 0..3 -> CCR 1.0, 0.0, 1.0, 0.0 -> binary 1,0,1,0.
    _write_csv(
        judge_dir / "phase3-vanilla-judged.csv",
        JUDGE_HEADER,
        [
            ["vanilla", 0, "Q0", 1.0, 0.0, None, 4.0, None, "", "", "", "", "", ""],
            ["vanilla", 1, "Q1", 0.0, 1.0, None, 3.0, None, "", "", "", "", "", ""],
            ["vanilla", 2, "Q2", 1.0, 0.0, None, 5.0, None, "", "", "", "", "", ""],
            ["vanilla", 3, "Q3", 0.0, 1.0, None, 2.0, None, "", "", "", "", "", ""],
        ],
    )
    hand_csv = tmp_path / "calibration.csv"
    _write_csv(
        hand_csv,
        ["system", "index", "ccr_hand"],
        [
            ["vanilla", 0, 1.0],
            ["vanilla", 1, 0.0],
            ["vanilla", 2, 1.0],
            ["vanilla", 3, 0.0],
        ],
    )

    out = tmp_path / "results" / "ablation_table.md"
    result = run_aggregate(
        inputs_glob=str(judge_dir / "phase3-*-judged.csv"),
        out_path=out,
        hand_grades_path=hand_csv,
        categories_path=None,
    )
    # Perfect agreement on the 4-row hand subset -> kappa == 1.0.
    assert result["kappa"] == 1.0
    text = out.read_text()
    assert "kappa(CCR, threshold=0.5)" in text
    assert "1.000" in text


def test_run_aggregate_iterates_actual_row_count_not_hardcoded(tmp_path: Path) -> None:
    # Real bank is 95 rows, not 100. Verify summarize_system uses len(rows).
    judge_dir = tmp_path / "grades"
    judge_dir.mkdir()
    rows = [["vanilla", i, f"Q{i}", 0.5, 0.5, None, 3.0, None,
             "", "", "", "", "", ""] for i in range(95)]
    _write_csv(judge_dir / "phase3-vanilla-judged.csv", JUDGE_HEADER, rows)

    out = tmp_path / "results" / "ablation_table.md"
    result = run_aggregate(
        inputs_glob=str(judge_dir / "phase3-*-judged.csv"),
        out_path=out,
        hand_grades_path=None,
        categories_path=None,
    )
    assert result["summaries"][0]["n"] == 95
