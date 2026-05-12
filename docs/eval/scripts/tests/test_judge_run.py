"""Targeted unit tests for ``docs/eval/scripts/judge_run.py``.

These cover the deterministic plumbing (metric selection by category,
JSONL row partitioning, YAML category parsing) so the long-running
batch driver can be trusted without making a real OpenRouter call.
"""

from __future__ import annotations

import json
from pathlib import Path

from docs.eval.scripts.judge_run import (
    CALIBRATION_INDICES_IN_ALL_TXT,
    _metrics_for,
    _read_categories,
    _read_rows,
)


def test_metrics_for_out_of_scope_returns_grr_only():
    assert _metrics_for(is_oos=True, run_fa=False) == ["grr"]
    # OOS always wins, regardless of run_fa.
    assert _metrics_for(is_oos=True, run_fa=True) == ["grr"]


def test_metrics_for_in_scope_without_fa():
    assert _metrics_for(is_oos=False, run_fa=False) == ["ccr", "hr", "nq"]


def test_metrics_for_in_scope_with_fa_inserts_at_position_two():
    metrics = _metrics_for(is_oos=False, run_fa=True)
    assert metrics == ["ccr", "hr", "fa", "nq"]
    assert metrics.index("fa") == 2


def test_calibration_indices_have_twenty_entries_across_five_categories():
    # 95-question bank: 4 picks from each of single, multi, geographic,
    # per-neighborhood, out-of-scope.
    assert len(CALIBRATION_INDICES_IN_ALL_TXT) == 20
    assert {0, 1, 2, 3}.issubset(CALIBRATION_INDICES_IN_ALL_TXT)
    assert {30, 31, 32, 33}.issubset(CALIBRATION_INDICES_IN_ALL_TXT)
    assert {55, 56, 57, 58}.issubset(CALIBRATION_INDICES_IN_ALL_TXT)
    assert {70, 71, 72, 73}.issubset(CALIBRATION_INDICES_IN_ALL_TXT)
    assert {85, 86, 87, 88}.issubset(CALIBRATION_INDICES_IN_ALL_TXT)


def test_read_rows_extracts_header_rows_footer(tmp_path: Path):
    header = {"type": "header", "system": "palimpsest-dense", "n_rows": 1}
    row = {"type": "row", "index": 0, "question": "Q", "narration": "N"}
    footer = {"type": "footer", "system": "palimpsest-dense"}
    p = tmp_path / "phase3-sample.jsonl"
    p.write_text(
        json.dumps(header) + "\n"
        + json.dumps(row) + "\n"
        + json.dumps(footer) + "\n"
    )
    h, rows, f = _read_rows(p)
    assert h == header
    assert rows == [row]
    assert f == footer


def test_read_rows_skips_blank_lines(tmp_path: Path):
    header = {"type": "header", "system": "x"}
    r0 = {"type": "row", "index": 0, "question": "q0"}
    r1 = {"type": "row", "index": 1, "question": "q1"}
    footer = {"type": "footer", "system": "x"}
    p = tmp_path / "with-blanks.jsonl"
    p.write_text(
        json.dumps(header) + "\n"
        + "\n"
        + json.dumps(r0) + "\n"
        + json.dumps(r1) + "\n"
        + "  \n"
        + json.dumps(footer) + "\n"
    )
    h, rows, f = _read_rows(p)
    assert h == header
    assert rows == [r0, r1]
    assert f == footer


def test_read_categories_parses_yaml(tmp_path: Path):
    p = tmp_path / "categories.yaml"
    p.write_text(
        "questions:\n"
        "- question: Tell me about the Cathedral.\n"
        "  category: single_place\n"
        "  is_out_of_scope: false\n"
        "- question: Tell me about Mars.\n"
        "  category: out_of_scope\n"
        "  is_out_of_scope: true\n"
    )
    cats = _read_categories(p)
    assert isinstance(cats, list)
    assert len(cats) == 2
    assert cats[0]["category"] == "single_place"
    assert cats[0]["is_out_of_scope"] is False
    assert cats[1]["is_out_of_scope"] is True
