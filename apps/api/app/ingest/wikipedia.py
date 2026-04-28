"""Wikipedia / Wikidata ingestor (stub).

Week 2 will flesh this out. For Week 1 we need the module to exist, declare
its scope filter, and provide a placeholder `run()` so the worker service can
import it without errors.

Target (Week 2):
  1. Query Wikidata SPARQL for items with `coordinate location` inside
     `SCOPE_BBOX` and `instance of` in a curated class list (landmarks,
     buildings, parks, etc.).
  2. For each returned QID, fetch the linked English Wikipedia article.
  3. Normalize into `places` and `documents` rows with provenance metadata.
  4. Generate embeddings via the LLM router (`complexity="simple"`) and write
     them into the `embeddings` column.
"""

from __future__ import annotations

import time

from app.ingest.base import IngestReport, Ingestor
from app.ingest.scope import SCOPE_BBOX
from app.logging import get_logger

log = get_logger(__name__)


class WikipediaIngestor:
    """Wikipedia + Wikidata ingestor for v1 scope."""

    source = "wikipedia"

    def __init__(self, *, scope=SCOPE_BBOX) -> None:
        self._scope = scope

    async def run(self) -> IngestReport:
        t0 = time.perf_counter()
        report = IngestReport(source=self.source)
        log.info(
            "ingest.wikipedia.start",
            bbox=self._scope.as_tuple(),
            note="stub — Week 2 will implement SPARQL + article fetch",
        )
        # TODO(apply-task-11.1): implement real ingestion
        report.duration_s = time.perf_counter() - t0
        log.info("ingest.wikipedia.done", **report.__dict__)
        return report
