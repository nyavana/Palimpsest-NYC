"""Worker entrypoint — runs scheduled ingestion jobs in a loop.

Week 1: log heartbeat every 30s. Week 2: wire APScheduler + real ingestors.
"""

from __future__ import annotations

import asyncio
import signal

from app.config import get_settings
from app.logging import configure_logging, get_logger

log = get_logger(__name__)


async def _heartbeat() -> None:
    while True:
        log.info("worker.heartbeat")
        await asyncio.sleep(30)


async def _run() -> None:
    settings = get_settings()
    configure_logging(settings)
    log.info("worker.startup", env=settings.app_env)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    heartbeat_task = asyncio.create_task(_heartbeat())
    await stop.wait()
    heartbeat_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass
    log.info("worker.shutdown")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
