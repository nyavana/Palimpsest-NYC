"""First-run initialization for the Palimpsest stack.

Runs inside the dedicated ``init-ingest`` compose service after postgres
becomes healthy. Each step is idempotent: if it has already happened, it
logs and skips, so re-up cycles stay fast.

Steps:
  1. Preload the sentence-transformer weights into the ``hf-cache`` volume
     so the first ``/agent/ask`` request doesn't pay the ~130 MB download.
  2. Run ``app.ingest.cli osm run`` when the ``places`` table has no rows
     with ``source_type='osm'``.
  3. Run ``app.ingest.cli wikipedia run`` when the ``places`` table has no
     rows with ``source_type='wikipedia'``.

To force re-ingestion after the ingestor code changes (e.g. the food
expansion in commit 7adc637), drop the postgres volume with ``make nuke``
and bring the stack back up.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from app.config import get_settings
from app.db.engine import build_engine, build_session_factory
from app.embeddings import build_embedder
from app.ingest.cli import dispatch
from app.logging import configure_logging, get_logger


async def _existing_rows(session_factory, source_type: str) -> int:
    async with session_factory() as session:
        result = await session.execute(
            text("SELECT COUNT(*) FROM places WHERE source_type = :st"),
            {"st": source_type},
        )
        return int(result.scalar() or 0)


async def _run() -> int:
    settings = get_settings()
    configure_logging(settings)
    log = get_logger("app.ingest.init_runner")

    log.info("init.embedder.preload.start", model=settings.embeddings.model)
    build_embedder(settings.embeddings)
    log.info("init.embedder.preload.done")

    engine = build_engine(settings.postgres)
    factory = build_session_factory(engine)
    failures = 0
    try:
        for source in ("osm", "wikipedia"):
            existing = await _existing_rows(factory, source)
            if existing > 0:
                log.info("init.ingest.skip", source=source, existing=existing)
                continue
            log.info("init.ingest.run.start", source=source)
            report = await dispatch([source, "run"])
            if not report.is_clean:
                failures += 1
                log.error(
                    "init.ingest.run.errors",
                    source=source,
                    errors=len(report.errors),
                )
            else:
                log.info(
                    "init.ingest.run.done",
                    source=source,
                    fetched=report.fetched,
                    inserted=report.inserted,
                )
    finally:
        await engine.dispose()

    return 0 if failures == 0 else 1


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
