"""Consume transport events and write them into analytics backends."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Dict, Optional

from src.config.settings import Settings, get_settings
from src.streaming.event_analytics_sink import EventAnalyticsSink
from src.utils.logger import get_logger

logger = get_logger(__name__)

try:
    import orjson  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    orjson = None


@dataclass
class ConsumerStats:
    consumed: int = 0
    errors: int = 0
    started_at: Optional[datetime] = None
    source: str = ""


class TransportAnalyticsConsumer:
    """Read normalized envelopes from Kafka or NATS and persist them."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        sink: EventAnalyticsSink | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._sink = sink or EventAnalyticsSink(self._settings)
        self._queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=4096)
        self._running = False
        self._process_task: asyncio.Task[None] | None = None
        self._transport_task: asyncio.Task[None] | None = None
        self._nats_client: Any = None
        self._nats_subscriptions: list[Any] = []
        self._kafka_consumer: Any = None
        self.stats = ConsumerStats()

    async def start(self) -> None:
        if self._running or not self._settings.analytics_consumer_enabled:
            return
        if not self._sink.enabled:
            logger.info("transport_analytics_consumer_disabled_no_sink")
            return
        self._running = True
        self.stats.started_at = datetime.now(tz=timezone.utc)
        source = self._resolve_source()
        self.stats.source = source
        await self._sink.start()
        self._process_task = asyncio.create_task(self._process_loop())
        if source == "kafka":
            await self._connect_kafka()
            self._transport_task = asyncio.create_task(self._consume_kafka())
        elif source == "nats":
            await self._connect_nats()
        else:
            logger.warning("transport_analytics_consumer_no_source")
        logger.info("transport_analytics_consumer_started", source=source)

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._transport_task is not None and not self._transport_task.done():
            self._transport_task.cancel()
            try:
                await self._transport_task
            except asyncio.CancelledError:
                pass
        self._transport_task = None
        for subscription in self._nats_subscriptions:
            try:
                await subscription.unsubscribe()
            except Exception:
                pass
        self._nats_subscriptions = []
        if self._nats_client is not None:
            try:
                await self._nats_client.close()
            except Exception:
                pass
            self._nats_client = None
        if self._kafka_consumer is not None:
            try:
                await self._kafka_consumer.stop()
            except Exception:
                pass
            self._kafka_consumer = None
        if self._process_task is not None and not self._process_task.done():
            self._process_task.cancel()
            try:
                await self._process_task
            except asyncio.CancelledError:
                pass
        self._process_task = None
        await self._sink.stop()
        logger.info(
            "transport_analytics_consumer_stopped",
            consumed=self.stats.consumed,
            errors=self.stats.errors,
            source=self.stats.source,
        )

    def snapshot(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "source": self.stats.source,
            "consumed": self.stats.consumed,
            "errors": self.stats.errors,
            "queue_depth": int(self._queue.qsize()),
        }

    def _resolve_source(self) -> str:
        preferred = str(self._settings.analytics_consumer_source or "").strip().lower()
        if preferred == "kafka" and self._settings.kafka_enabled:
            return "kafka"
        if preferred == "nats" and self._settings.nats_enabled:
            return "nats"
        if self._settings.kafka_enabled:
            return "kafka"
        if self._settings.nats_enabled:
            return "nats"
        return ""

    async def _connect_kafka(self) -> None:
        try:
            from aiokafka import AIOKafkaConsumer  # type: ignore[import-not-found]
        except ImportError:
            logger.warning("transport_analytics_kafka_client_missing")
            return
        self._kafka_consumer = AIOKafkaConsumer(
            f"{self._settings.kafka_topic_prefix}.execution.events",
            f"{self._settings.kafka_topic_prefix}.market.ticks",
            f"{self._settings.kafka_topic_prefix}.market.bars",
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            group_id=self._settings.analytics_consumer_group_id,
            value_deserializer=self._loads_bytes,
            auto_offset_reset="latest",
            enable_auto_commit=True,
        )
        await self._kafka_consumer.start()

    async def _connect_nats(self) -> None:
        try:
            import nats  # type: ignore[import-not-found]
        except ImportError:
            logger.warning("transport_analytics_nats_client_missing")
            return
        self._nats_client = await nats.connect(self._settings.nats_url)
        for subject in (
            f"{self._settings.nats_stream_prefix}.execution.events",
            f"{self._settings.nats_stream_prefix}.market.ticks",
            f"{self._settings.nats_stream_prefix}.market.bars",
        ):
            subscription = await self._nats_client.subscribe(subject, cb=self._nats_callback)
            self._nats_subscriptions.append(subscription)

    async def _consume_kafka(self) -> None:
        if self._kafka_consumer is None:
            return
        async for message in self._kafka_consumer:
            if not self._running:
                break
            await self._enqueue(message.value)

    async def _nats_callback(self, message: Any) -> None:
        payload = self._loads_bytes(message.data)
        if isinstance(payload, dict):
            await self._enqueue(payload)

    async def _enqueue(self, envelope: Dict[str, Any]) -> None:
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        await self._queue.put(envelope)

    async def _process_loop(self) -> None:
        while self._running:
            envelope = await self._queue.get()
            try:
                await self._sink.write_envelope(envelope)
                self.stats.consumed += 1
            except Exception as exc:
                self.stats.errors += 1
                logger.warning("transport_analytics_consume_failed", error=str(exc))

    @staticmethod
    def _loads_bytes(payload: bytes) -> Dict[str, Any]:
        if orjson is not None:
            return dict(orjson.loads(payload))
        return dict(json.loads(payload.decode("utf-8")))
