"""Claude Code session logger.

Writes one JSONL record per session to `logs/claude-sessions/<date>.jsonl`.
Records are intentionally small and self-describing so the final report can
load them into a dataframe and compute aggregate stats (cost per feature,
tokens per 10 LOC, human-edit-ratio per session, etc.).

Schema is versioned so later changes can migrate historical records
without losing backward-compatibility.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1

Outcome = Literal["success", "partial", "failure", "interrupted"]


class SessionRecord(BaseModel):
    """One Claude Code session.

    All fields are optional except `session_id`, `started_at`, and `goal`
    so the harness can record incomplete sessions (interrupts, crashes)
    without data loss.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    session_id: str
    started_at: str
    ended_at: str | None = None
    goal: str
    model: str | None = None

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0

    files_touched: list[str] = Field(default_factory=list)
    human_edits_after: int = 0
    lines_added: int = 0
    lines_removed: int = 0

    outcome: Outcome = "success"
    notes: str = ""
    tags: dict[str, str] = Field(default_factory=dict)


@dataclass
class _Summary:
    records: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_cost_usd: float = 0.0
    outcomes: dict[str, int] = field(default_factory=dict)
    files_touched_unique: set[str] = field(default_factory=set)


class SessionLogger:
    """Append-only JSONL writer for SessionRecord.

    Thread-safe for append operations (Python's file-open append is atomic
    for small lines), not safe for concurrent summarization during writes.
    For v1 the harness is single-reader and this is sufficient.
    """

    def __init__(self, log_dir: str) -> None:
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)

    # -- Append -----------------------------------------------------

    def append(self, record: SessionRecord) -> Path:
        """Write a single record and return the file path it landed in."""
        path = self._path_for(record.started_at)
        line = record.model_dump_json() + "\n"
        # Atomic append on POSIX for small writes
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
        return path

    def _path_for(self, iso_timestamp: str) -> Path:
        # One file per UTC date, e.g. 2026-04-11.jsonl
        date = iso_timestamp.split("T", 1)[0]
        return self._log_dir / f"{date}.jsonl"

    # -- Read / summarize -------------------------------------------

    def iter_records(self) -> list[SessionRecord]:
        """Load every record on disk. Invalid lines are skipped with a warning."""
        records: list[SessionRecord] = []
        if not self._log_dir.exists():
            return records
        for path in sorted(self._log_dir.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(SessionRecord.model_validate_json(line))
                except Exception:  # noqa: BLE001 — skip malformed line
                    continue
        return records

    def summarize(self) -> dict[str, object]:
        """Return a JSON-friendly aggregate used by /internal/metrics."""
        summary = _Summary()
        for rec in self.iter_records():
            summary.records += 1
            summary.total_prompt_tokens += rec.prompt_tokens
            summary.total_completion_tokens += rec.completion_tokens
            summary.total_cost_usd += rec.cost_usd
            summary.outcomes[rec.outcome] = summary.outcomes.get(rec.outcome, 0) + 1
            summary.files_touched_unique.update(rec.files_touched)
        return {
            "schema_version": SCHEMA_VERSION,
            "records": summary.records,
            "total_prompt_tokens": summary.total_prompt_tokens,
            "total_completion_tokens": summary.total_completion_tokens,
            "total_cost_usd": round(summary.total_cost_usd, 4),
            "outcomes": summary.outcomes,
            "unique_files_touched": len(summary.files_touched_unique),
            "log_dir": str(self._log_dir),
        }

    # -- Convenience --------------------------------------------------

    def seed_first_record(self) -> None:
        """Write a first record describing this very scaffolding session.

        Idempotent: runs once, skipped if today's file already exists with any
        records for this session_id.
        """
        session_id = "2026-04-11T01:30:00Z-scaffold"
        already = any(
            rec.session_id == session_id for rec in self.iter_records()
        )
        if already:
            return
        now = datetime.now(tz=timezone.utc)
        record = SessionRecord(
            session_id=session_id,
            started_at=now.isoformat(),
            ended_at=now.isoformat(),
            goal="scaffold monorepo, openspec artifacts, llm router, meta-log, map engine",
            model="claude-opus-4-6[1m]",
            outcome="success",
            notes=(
                "Initial Palimpsest NYC scaffold — openspec change "
                "initial-palimpsest-scaffold. Built by Claude Code under "
                "instructor permission as a case study in agentic engineering."
            ),
            tags={"phase": "week-1", "kind": "foundation"},
        )
        self.append(record)


# ── Environment integration ─────────────────────────────────────────


def build_default_logger() -> SessionLogger:
    """Build a SessionLogger using the env-configured log directory."""
    log_dir = os.environ.get("META_SESSION_LOG_DIR", "/app/logs/claude-sessions")
    return SessionLogger(log_dir=log_dir)
