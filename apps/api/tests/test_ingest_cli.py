"""Ingest CLI tests — argument parsing + ingestor selection.

Avoids hitting the network or the DB by injecting a fake registry.
"""

from __future__ import annotations

from app.ingest.base import IngestReport
from app.ingest.cli import build_parser, dispatch


class _FakeIngestor:
    source = "wikipedia"
    runs = 0

    def __init__(self, *, scope=None, cache=None, **_) -> None:  # noqa: ANN001
        self._scope = scope

    async def run(self, session, embedder=None):  # noqa: ANN001
        type(self).runs += 1
        return IngestReport(source=self.source, fetched=2, inserted=2)


async def test_dispatch_wikipedia_run_calls_run() -> None:
    _FakeIngestor.runs = 0
    registry = {"wikipedia": _FakeIngestor}
    report = await dispatch(
        ["wikipedia", "run"],
        registry=registry,
        session_provider=_fake_session_provider,
        embedder_provider=lambda: None,
    )
    assert _FakeIngestor.runs == 1
    assert report.source == "wikipedia"
    assert report.inserted == 2


def test_parser_accepts_known_sources_only() -> None:
    parser = build_parser({"wikipedia", "osm"})
    args = parser.parse_args(["osm", "run"])
    assert args.source == "osm"
    assert args.cmd == "run"


class _FakeSession:
    async def commit(self) -> None:
        pass

    async def close(self) -> None:
        pass


class _FakeEngine:
    async def dispose(self) -> None:
        pass


async def _fake_session_provider():
    yield _FakeSession()
