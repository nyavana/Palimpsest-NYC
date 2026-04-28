"""Unit tests for the async SQLAlchemy engine factory.

These tests do not require a live postgres — they exercise the engine /
session-factory wiring. Integration tests that hit a real DB live in
`tests/integration/` (skipped unless `PALIMPSEST_INTEGRATION=1`).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import PostgresSettings
from app.db.engine import build_engine, build_session_factory


def _settings() -> PostgresSettings:
    return PostgresSettings()  # defaults — no network use until engine.connect()


def test_build_engine_returns_async_engine() -> None:
    engine = build_engine(_settings())
    assert isinstance(engine, AsyncEngine)
    # asyncpg dialect (`postgresql+asyncpg://...`) — required for asyncio tools
    assert engine.dialect.driver == "asyncpg"


async def test_build_session_factory_yields_async_session() -> None:
    engine = build_engine(_settings())
    factory = build_session_factory(engine)
    assert isinstance(factory, async_sessionmaker)
    session = factory()
    try:
        assert isinstance(session, AsyncSession)
    finally:
        await session.close()


async def test_engine_dsn_uses_settings_values() -> None:
    settings = PostgresSettings(host="example", port=6543, db="db1", user="u")
    engine = build_engine(settings)
    url = engine.url
    assert url.host == "example"
    assert url.port == 6543
    assert url.database == "db1"
    assert url.username == "u"
    await engine.dispose()
