"""One-shot ingest CLI.

Usage:
    python -m app.ingest.cli wikipedia run
    python -m app.ingest.cli osm run

V1 worker per `swap-llm-tiers-and-lock-mvp-decisions` §4.6.1: ingestion runs
as a CLI invocation, not on a schedule. The worker container runs a
heartbeat loop only.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable
from typing import Any

from app.config import get_settings
from app.db.engine import build_engine, build_session_factory
from app.embeddings import build_embedder
from app.ingest.base import IngestReport
from app.ingest.osm import OsmIngestor
from app.ingest.raw_cache import RawCache
from app.ingest.wikipedia import WikipediaIngestor
from app.logging import configure_logging, get_logger

DEFAULT_REGISTRY: dict[str, type] = {
    "wikipedia": WikipediaIngestor,
    "osm": OsmIngestor,
}


def build_parser(sources: Iterable[str]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.ingest.cli")
    parser.add_argument("source", choices=sorted(sources))
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="Run the ingestor once")
    return parser


# ── default providers (swap-able for tests) ────────────────────────


async def _default_session_provider() -> AsyncGenerator[Any, None]:
    settings = get_settings()
    engine = build_engine(settings.postgres)
    factory = build_session_factory(engine)
    async with factory() as session:
        try:
            yield session
        finally:
            await engine.dispose()


def _default_embedder_provider() -> Any:
    settings = get_settings()
    return build_embedder(settings.embeddings)


def _default_cache() -> RawCache:
    root = os.environ.get("RAW_CACHE_DIR", "data/raw")
    return RawCache(root)


# ── dispatch ────────────────────────────────────────────────────────


async def dispatch(
    argv: list[str],
    *,
    registry: dict[str, type] | None = None,
    session_provider: Callable[[], AsyncGenerator[Any, None]] | None = None,
    embedder_provider: Callable[[], Any] | None = None,
    cache_provider: Callable[[], RawCache | None] | None = None,
) -> IngestReport:
    log = get_logger("app.ingest.cli")
    registry = registry or DEFAULT_REGISTRY
    parser = build_parser(registry.keys())
    args = parser.parse_args(argv)

    cls = registry[args.source]
    cache = (cache_provider or _default_cache)()
    ingestor = cls(cache=cache) if cache is not None else cls()

    sp = session_provider or _default_session_provider
    embedder = (embedder_provider or _default_embedder_provider)()

    log.info("ingest.cli.start", source=args.source)
    report = IngestReport(source=args.source)
    async for session in sp():
        report = await ingestor.run(session, embedder=embedder)
    log.info(
        "ingest.cli.done",
        source=args.source,
        fetched=report.fetched,
        inserted=report.inserted,
        errors=len(report.errors),
    )
    return report


# ── entrypoint ──────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    configure_logging(settings)
    report = asyncio.run(dispatch(argv if argv is not None else sys.argv[1:]))
    return 0 if report.is_clean else 1


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["build_parser", "dispatch", "main", "DEFAULT_REGISTRY"]
