"""Telemetry sink for the LLM router.

Every router call (success, cache hit, or error) produces one `TelemetryRecord`.
Records are emitted to structlog AND appended to a bounded Redis list so the
`/internal/metrics` endpoint can aggregate recent activity without touching the
full logging pipeline.
"""

from __future__ import annotations

from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.llm.models import TelemetryRecord
from app.logging import get_logger

log = get_logger(__name__)

_STREAM_KEY = "llm:telemetry:v1"
_STREAM_MAX = 10_000


class TelemetrySink:
    """Fan telemetry out to structlog and a capped Redis stream."""

    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis

    async def emit(self, record: TelemetryRecord) -> None:
        log.info(
            "llm.call",
            request_id=record.request_id,
            backend=record.backend,
            model=record.model,
            complexity=record.complexity,
            cached=record.cached,
            prompt_tokens=record.prompt_tokens,
            completion_tokens=record.completion_tokens,
            latency_ms=round(record.latency_ms, 2),
            cost_usd=round(record.cost_usd, 6),
            error_code=record.error_code,
            tags=record.tags,
        )
        try:
            # LPUSH + LTRIM to maintain a bounded tail-recent stream.
            payload = record.model_dump_json()
            pipe = self._redis.pipeline()
            pipe.lpush(_STREAM_KEY, payload)
            pipe.ltrim(_STREAM_KEY, 0, _STREAM_MAX - 1)
            await pipe.execute()
        except Exception as exc:  # noqa: BLE001 — telemetry must never break the call
            log.warning("llm.telemetry.redis_failed", error=str(exc))

    @staticmethod
    def build(
        *,
        request_id: str,
        backend: str | None,
        model: str | None,
        complexity: str,
        cached: bool,
        latency_ms: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_usd: float = 0.0,
        error_code: str | None = None,
        tags: dict[str, str] | None = None,
    ) -> TelemetryRecord:
        return TelemetryRecord(
            request_id=request_id,
            timestamp=datetime.now(tz=timezone.utc).isoformat(),
            backend=backend,  # type: ignore[arg-type]
            model=model,
            complexity=complexity,  # type: ignore[arg-type]
            cached=cached,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            error_code=error_code,
            tags=tags or {},
        )
