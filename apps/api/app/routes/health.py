"""Liveness and readiness endpoints.

- /health: always cheap, returns 200 if the process is alive.
- /ready:  dependency-sensitive, pings Postgres and Redis. Returns 503 if any
           dependency is unreachable.
"""

from __future__ import annotations

from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app import __version__
from app.config import Settings

router = APIRouter()


@router.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/ready", tags=["health"])
async def ready(request: Request) -> JSONResponse:
    settings: Settings = request.app.state.settings
    checks: dict[str, Any] = {}
    healthy = True

    # Postgres ping
    try:
        engine = create_async_engine(settings.postgres.dsn, pool_pre_ping=True)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        checks["postgres"] = "ok"
    except Exception as exc:  # noqa: BLE001 - surface any connection failure
        checks["postgres"] = f"error: {exc!s}"
        healthy = False

    # Redis ping
    try:
        r = aioredis.from_url(settings.redis_url)
        pong = await r.ping()
        await r.aclose()
        checks["redis"] = "ok" if pong else "no-pong"
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = f"error: {exc!s}"
        healthy = False

    status_code = status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=status_code, content={"status": "ok" if healthy else "degraded", "checks": checks})
