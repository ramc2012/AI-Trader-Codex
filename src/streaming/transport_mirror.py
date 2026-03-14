"""Mirror transport events from NATS into Kafka for durable replay."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Dict, Optional

from src.config.settings import Settings, get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

try:
    import orjson  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    orjson = None


@dataclass
class TransportMirrorStats:
    mirrored: int = 0
    dropped: int = 0
    errors: int = 0
    started_at: Optional[datetime] = None


class TransportMirror:
    """Subscribe to NATS transport subjects and republish into Kafka."""

    def __init__(self, *, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=4096)
        self._running = False
        self._process_task: asyncio.Task[None] | None = None
        self._nats_client: Any = None
        self._nats_subscriptions: list[Any] = []
        self._kafka_producer: Any = None
        self.stats = TransportMirrorStats()

    async def start(self) -> None:
        if self._running or not self._settings.transport_mirror_enabled:
            return
        if not (self._settings.nats_enabled and self._settings.kafka_enabled):
            logger.info("transport_mirror_disabled_missing_backends")
            return
        self._running = True
        self.stats.started_at = datetime.now(tz=timezone.utc)
        await self._connect_nats()
        await self._connect_kafka()
        self._process_task = asyncio.create_task(self._process_loop())
        logger.info("transport_mirror_started")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
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
        if self._kafka_producer is not None:
            try:
                await self._kafka_producer.stop()
            except Exception:
                pass
            self._kafka_producer = None
        if self._process_task is not None and not self._process_task.done():
            self._process_task.cancel()
            try:
                await self._process_task
            except asyncio.CancelledError:
                pass
        self._process_task = None
        logger.info(
            "transport_mirror_stopped",
            mirrored=self.stats.mirrored,
            dropped=self.stats.dropped,
            errors=self.stats.errors,
        )

    def snapshot(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "mirrored": self.stats.mirrored,
            "dropped": self.stats.dropped,
            "errors": self.stats.errors,
            "queue_depth": int(self._queue.qsize()),
        }

    async def _connect_nats(self) -> None:
        try:
            import nats  # type: ignore[import-not-found]
        except ImportError:
            logger.warning("transport_mirror_nats_client_missing")
            return
        self._nats_client = await nats.connect(self._settings.nats_url)
        for subject in self._subjects():
            subscription = await self._nats_client.subscribe(subject, cb=self._nats_callback)
            self._nats_subscriptions.append(subscription)

    async def _connect_kafka(self) -> None:
        try:
            from aiokafka import AIOKafkaProducer  # type: ignore[import-not-found]
        except ImportError:
            logger.warning("transport_mirror_kafka_client_missing")
            return
        producer = AIOKafkaProducer(
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            value_serializer=self._dumps_bytes,
        )
        await producer.start()
        self._kafka_producer = producer

    def _subjects(self) -> tuple[str, ...]:
        prefix = self._settings.nats_stream_prefix
        return (
            f"{prefix}.execution.events",
            f"{prefix}.execution.signals",
            f"{prefix}.market.ticks",
            f"{prefix}.market.bars",
        )

    async def _nats_callback(self, message: Any) -> None:
        payload = self._loads_bytes(message.data)
        if isinstance(payload, dict):
            await self._enqueue(payload)

    async def _enqueue(self, envelope: Dict[str, Any]) -> None:
        if self._queue.full():
            try:
                self._queue.get_nowait()
                self.stats.dropped += 1
            except asyncio.QueueEmpty:
                pass
        await self._queue.put(envelope)

    async def _process_loop(self) -> None:
        while self._running:
            envelope = await self._queue.get()
            try:
                await self._publish(envelope)
                self.stats.mirrored += 1
            except Exception as exc:
                self.stats.errors += 1
                logger.warning("transport_mirror_publish_failed", error=str(exc))

    async def _publish(self, envelope: Dict[str, Any]) -> None:
        if self._kafka_producer is None:
            return
        await self._kafka_producer.send_and_wait(
            self._topic_for(envelope),
            envelope,
        )

    def _topic_for(self, envelope: Dict[str, Any]) -> str:
        prefix = self._settings.kafka_topic_prefix
        stream = str(envelope.get("stream") or "execution")
        if stream == "market_ticks":
            suffix = "market.ticks"
        elif stream == "market_bars":
            suffix = "market.bars"
        elif stream == "execution_signals":
            suffix = "execution.signals"
        else:
            suffix = "execution.events"
        return f"{prefix}.{suffix}"

    @staticmethod
    def _loads_bytes(payload: bytes) -> Dict[str, Any]:
        if orjson is not None:
            return dict(orjson.loads(payload))
        return dict(json.loads(payload.decode("utf-8")))

    @staticmethod
    def _dumps_bytes(payload: Dict[str, Any]) -> bytes:
        if orjson is not None:
            return orjson.dumps(payload)
        return json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
