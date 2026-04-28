"""Async SQLAlchemy engine + session factory.

Wired into the app lifespan; ORM models in `app.db.models` use the same
declarative `Base`. Per spec, this module never executes DDL — schema
is owned by `app/db/migrations/*.sql` applied by the postgres entrypoint.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import PostgresSettings


def build_engine(settings: PostgresSettings) -> AsyncEngine:
    return create_async_engine(
        settings.dsn,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=10,
        future=True,
    )


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
