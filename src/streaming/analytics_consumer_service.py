"""Standalone process runner for the transport analytics consumer."""

from __future__ import annotations

import asyncio
import signal

from src.api.dependencies import get_transport_analytics_consumer
from src.config.settings import get_settings
from src.utils.logger import get_logger, setup_logging

logger = get_logger(__name__)


async def main() -> None:
    """Run the analytics consumer until the process receives a shutdown signal."""
    setup_logging()
    settings = get_settings()
    if not settings.analytics_consumer_enabled:
        logger.info("analytics_consumer_service_disabled")
        return

    consumer = get_transport_analytics_consumer()
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _request_shutdown() -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_shutdown)
        except NotImplementedError:
            pass

    await consumer.start()
    logger.info(
        "analytics_consumer_service_started",
        source=settings.analytics_consumer_source,
        embedded=settings.analytics_consumer_embedded_enabled,
    )
    try:
        await stop_event.wait()
    finally:
        await consumer.stop()
        logger.info("analytics_consumer_service_stopped")


if __name__ == "__main__":
    asyncio.run(main())
