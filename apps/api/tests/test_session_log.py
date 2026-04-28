"""Tests for the meta-instrumentation session log."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.meta.session_log import SCHEMA_VERSION, SessionLogger, SessionRecord


def _record(session_id: str = "test-1", **overrides: object) -> SessionRecord:
    base = {
        "session_id": session_id,
        "started_at": datetime.now(tz=timezone.utc).isoformat(),
        "goal": "test",
        "outcome": "success",
    }
    base.update(overrides)
    return SessionRecord(**base)  # type: ignore[arg-type]


def test_append_writes_to_dated_file(tmp_path: Path) -> None:
    logger = SessionLogger(log_dir=str(tmp_path))
    record = _record()
    path = logger.append(record)

    assert path.parent == tmp_path
    assert path.name.endswith(".jsonl")
    assert path.read_text().count("\n") == 1


def test_append_is_additive(tmp_path: Path) -> None:
    logger = SessionLogger(log_dir=str(tmp_path))
    logger.append(_record("s1"))
    logger.append(_record("s2"))

    all_records = logger.iter_records()
    assert len(all_records) == 2
    assert {r.session_id for r in all_records} == {"s1", "s2"}


def test_summarize_aggregates_tokens_and_cost(tmp_path: Path) -> None:
    logger = SessionLogger(log_dir=str(tmp_path))
    logger.append(
        _record(
            "s1",
            prompt_tokens=1000,
            completion_tokens=500,
            cost_usd=0.15,
            files_touched=["a.py", "b.py"],
        )
    )
    logger.append(
        _record(
            "s2",
            prompt_tokens=2000,
            completion_tokens=1000,
            cost_usd=0.30,
            files_touched=["a.py", "c.py"],
            outcome="partial",
        )
    )

    summary = logger.summarize()

    assert summary["records"] == 2
    assert summary["total_prompt_tokens"] == 3000
    assert summary["total_completion_tokens"] == 1500
    assert summary["total_cost_usd"] == pytest.approx(0.45)
    assert summary["outcomes"] == {"success": 1, "partial": 1}
    assert summary["unique_files_touched"] == 3
    assert summary["schema_version"] == SCHEMA_VERSION


def test_seed_is_idempotent(tmp_path: Path) -> None:
    logger = SessionLogger(log_dir=str(tmp_path))
    logger.seed_first_record()
    logger.seed_first_record()

    records = logger.iter_records()
    # seed writes a single constant-id record; second call should be no-op
    seed_records = [r for r in records if r.session_id.endswith("-scaffold")]
    assert len(seed_records) == 1


def test_malformed_lines_are_skipped(tmp_path: Path) -> None:
    logger = SessionLogger(log_dir=str(tmp_path))
    logger.append(_record("good"))
    # Corrupt a line
    bad_file = tmp_path / "2026-04-11.jsonl"
    with bad_file.open("a") as fh:
        fh.write("not-json\n")

    records = logger.iter_records()
    assert any(r.session_id == "good" for r in records)
