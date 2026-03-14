"""Standalone runner for NATS-to-Kafka transport mirroring."""

from __future__ import annotations

import asyncio
import signal

from src.api.dependencies import get_transport_mirror
from src.config.settings import get_settings
from src.utils.logger import get_logger, setup_logging

logger = get_logger(__name__)


async def main() -> None:
    """Run the transport mirror until shutdown."""
    setup_logging()
    settings = get_settings()
    if not settings.transport_mirror_enabled:
        logger.info("transport_mirror_service_disabled")
        return

    mirror = get_transport_mirror()
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _request_shutdown() -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_shutdown)
        except NotImplementedError:
            pass

    await mirror.start()
    logger.info(
        "transport_mirror_service_started",
        embedded=settings.transport_mirror_embedded_enabled,
    )
    try:
        await stop_event.wait()
    finally:
        await mirror.stop()
        logger.info("transport_mirror_service_stopped")


if __name__ == "__main__":
    asyncio.run(main())
