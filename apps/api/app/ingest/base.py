"""Shared ingestion base types.

Every source-specific ingestor implements the `Ingestor` protocol so the
worker service can discover and run them generically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class IngestReport:
    """Summary returned by a single ingestor run."""

    source: str
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    skipped_out_of_scope: int = 0
    skipped_malformed: int = 0
    errors: list[str] = field(default_factory=list)
    duration_s: float = 0.0

    @property
    def is_clean(self) -> bool:
        return len(self.errors) == 0


@runtime_checkable
class Ingestor(Protocol):
    """Protocol every ingestor implements."""

    source: str
    """Identifier matching the `source_id` column on persisted rows."""

    async def run(self) -> IngestReport:
        """Execute the ingestion pass and return a summary."""
        ...
