"""Background publisher for execution, tick, and candle events."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Dict, Optional

import httpx

from src.agent.events import AgentEvent, AgentEventBus, AgentEventType
from src.config.settings import Settings, get_settings
from src.data.live.tick_stream import TickStreamBroker
from src.utils.logger import get_logger

logger = get_logger(__name__)

try:
    import orjson  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    orjson = None

_EXECUTION_AGENT_EVENTS = {
    AgentEventType.SIGNAL_GENERATED,
    AgentEventType.RISK_CHECK_PASSED,
    AgentEventType.RISK_CHECK_FAILED,
    AgentEventType.ORDER_PLACING,
    AgentEventType.ORDER_PLACED,
    AgentEventType.ORDER_FILLED,
    AgentEventType.ORDER_REJECTED,
    AgentEventType.POSITION_OPENED,
    AgentEventType.POSITION_CLOSED,
    AgentEventType.POSITION_UPDATE,
}


@dataclass
class PublisherStats:
    published_events: int = 0
    dropped_events: int = 0
    errors: int = 0
    started_at: Optional[datetime] = None


class ExecutionEventPublisher:
    """Fan out execution and market-stream events to transport backends."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        agent_event_bus: AgentEventBus | None = None,
        broker_event_broker: TickStreamBroker | None = None,
        tick_broker: TickStreamBroker | None = None,
        candle_broker: TickStreamBroker | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._agent_event_bus = agent_event_bus
        self._broker_event_broker = broker_event_broker
        self._tick_broker = tick_broker
        self._candle_broker = candle_broker
        self._running = False
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=2048)
        self._agent_subscription: asyncio.Queue[AgentEvent] | None = None
        self._broker_subscription: asyncio.Queue[dict[str, Any]] | None = None
        self._tick_subscription: asyncio.Queue[dict[str, Any]] | None = None
        self._candle_subscription: asyncio.Queue[dict[str, Any]] | None = None
        self._agent_task: asyncio.Task[None] | None = None
        self._broker_task: asyncio.Task[None] | None = None
        self._tick_task: asyncio.Task[None] | None = None
        self._candle_task: asyncio.Task[None] | None = None
        self._publish_task: asyncio.Task[None] | None = None
        self._nats_client: Any = None
        self._kafka_producer: Any = None
        self._http_client: httpx.AsyncClient | None = None
        self._questdb_writer: asyncio.StreamWriter | None = None
        self._questdb_lock = asyncio.Lock()
        self.stats = PublisherStats()

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.stats.started_at = datetime.now(tz=timezone.utc)
        await self._connect_backends()
        if self._agent_event_bus is not None:
            self._agent_subscription = self._agent_event_bus.subscribe(maxsize=512)
            self._agent_task = asyncio.create_task(self._consume_agent_events())
        if self._broker_event_broker is not None:
            self._broker_subscription = self._broker_event_broker.subscribe("*")
            self._broker_task = asyncio.create_task(self._consume_broker_events())
        if self._tick_broker is not None:
            self._tick_subscription = self._tick_broker.subscribe("*")
            self._tick_task = asyncio.create_task(self._consume_tick_events())
        if self._candle_broker is not None:
            self._candle_subscription = self._candle_broker.subscribe("*")
            self._candle_task = asyncio.create_task(self._consume_candle_events())
        self._publish_task = asyncio.create_task(self._publish_loop())
        logger.info("execution_event_publisher_started")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._agent_subscription is not None and self._agent_event_bus is not None:
            self._agent_event_bus.unsubscribe(self._agent_subscription)
            self._agent_subscription = None
        if self._broker_subscription is not None and self._broker_event_broker is not None:
            self._broker_event_broker.unsubscribe("*", self._broker_subscription)
            self._broker_subscription = None
        if self._tick_subscription is not None and self._tick_broker is not None:
            self._tick_broker.unsubscribe("*", self._tick_subscription)
            self._tick_subscription = None
        if self._candle_subscription is not None and self._candle_broker is not None:
            self._candle_broker.unsubscribe("*", self._candle_subscription)
            self._candle_subscription = None
        for task in (
            self._agent_task,
            self._broker_task,
            self._tick_task,
            self._candle_task,
            self._publish_task,
        ):
            if task is not None and not task.done():
                task.cancel()
        for task in (
            self._agent_task,
            self._broker_task,
            self._tick_task,
            self._candle_task,
            self._publish_task,
        ):
            if task is not None:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    logger.debug("execution_event_publisher_task_stop_failed", error=str(exc))
        self._agent_task = None
        self._broker_task = None
        self._tick_task = None
        self._candle_task = None
        self._publish_task = None
        await self._close_backends()
        logger.info(
            "execution_event_publisher_stopped",
            published=self.stats.published_events,
            dropped=self.stats.dropped_events,
            errors=self.stats.errors,
        )

    async def _consume_agent_events(self) -> None:
        assert self._agent_subscription is not None
        while self._running:
            event = await self._agent_subscription.get()
            if event.event_type not in _EXECUTION_AGENT_EVENTS:
                continue
            await self._enqueue(self._normalize_agent_event(event))

    async def _consume_broker_events(self) -> None:
        assert self._broker_subscription is not None
        while self._running:
            payload = await self._broker_subscription.get()
            await self._enqueue(self._normalize_broker_event(payload))

    async def _consume_tick_events(self) -> None:
        assert self._tick_subscription is not None
        while self._running:
            payload = await self._tick_subscription.get()
            await self._enqueue(self._normalize_tick_event(payload))

    async def _consume_candle_events(self) -> None:
        assert self._candle_subscription is not None
        while self._running:
            payload = await self._candle_subscription.get()
            await self._enqueue(self._normalize_candle_event(payload))

    async def _enqueue(self, envelope: dict[str, Any]) -> None:
        if self._queue.full():
            try:
                self._queue.get_nowait()
                self.stats.dropped_events += 1
            except asyncio.QueueEmpty:
                pass
        await self._queue.put(envelope)

    async def _publish_loop(self) -> None:
        while self._running:
            envelope = await self._queue.get()
            try:
                await self._publish_envelope(envelope)
                self.stats.published_events += 1
            except Exception as exc:
                self.stats.errors += 1
                logger.warning("execution_event_publish_failed", error=str(exc), event_type=envelope.get("event_type"))

    async def _connect_backends(self) -> None:
        if self._settings.nats_enabled:
            try:
                await self._connect_nats()
            except Exception as exc:
                logger.warning("execution_event_nats_connect_failed", error=str(exc))
        if self._settings.kafka_enabled:
            try:
                await self._connect_kafka()
            except Exception as exc:
                logger.warning("execution_event_kafka_connect_failed", error=str(exc))
        if self._settings.clickhouse_enabled:
            try:
                self._http_client = httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0))
                await self._ensure_clickhouse_tables()
            except Exception as exc:
                logger.warning("execution_event_clickhouse_init_failed", error=str(exc))
                if self._http_client is not None:
                    await self._http_client.aclose()
                self._http_client = None
        elif self._settings.questdb_enabled:
            self._http_client = httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0))

    async def _close_backends(self) -> None:
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
        if self._questdb_writer is not None:
            try:
                self._questdb_writer.close()
                await self._questdb_writer.wait_closed()
            except Exception:
                pass
            self._questdb_writer = None
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def _connect_nats(self) -> None:
        try:
            import nats  # type: ignore[import-not-found]
        except ImportError:
            logger.warning("nats_client_missing")
            return
        self._nats_client = await nats.connect(self._settings.nats_url)
        logger.info("execution_event_nats_connected", url=self._settings.nats_url)

    async def _connect_kafka(self) -> None:
        try:
            from aiokafka import AIOKafkaProducer  # type: ignore[import-not-found]
        except ImportError:
            logger.warning("kafka_client_missing")
            return
        producer = AIOKafkaProducer(
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            value_serializer=self._dumps_bytes,
        )
        await producer.start()
        self._kafka_producer = producer
        logger.info("execution_event_kafka_connected", bootstrap_servers=self._settings.kafka_bootstrap_servers)

    async def _publish_envelope(self, envelope: dict[str, Any]) -> None:
        tasks: list[asyncio.Future[Any] | asyncio.Task[Any]] = []
        stream = str(envelope.get("stream") or "execution")
        nats_subject, kafka_topic = self._transport_names(stream)
        if self._nats_client is not None:
            tasks.append(asyncio.create_task(self._nats_client.publish(nats_subject, self._dumps_bytes(envelope))))
        if self._kafka_producer is not None:
            tasks.append(asyncio.create_task(self._kafka_producer.send_and_wait(kafka_topic, envelope)))
        if self._settings.clickhouse_enabled:
            tasks.append(asyncio.create_task(self._write_clickhouse(envelope)))
        if self._settings.questdb_enabled:
            tasks.append(asyncio.create_task(self._write_questdb(envelope)))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=False)

    async def _ensure_clickhouse_tables(self) -> None:
        if self._http_client is None:
            return
        execution_ddl = f"""
        CREATE TABLE IF NOT EXISTS {self._settings.clickhouse_database}.execution_events (
            event_time DateTime64(3, 'UTC'),
            event_date Date,
            event_id String,
            source LowCardinality(String),
            event_type LowCardinality(String),
            symbol String,
            order_id String,
            trade_id String,
            strategy String,
            market LowCardinality(String),
            payload String
        ) ENGINE = MergeTree
        ORDER BY (event_date, event_type, symbol, event_time)
        """
        market_ticks_ddl = f"""
        CREATE TABLE IF NOT EXISTS {self._settings.clickhouse_database}.market_ticks (
            event_time DateTime64(3, 'UTC'),
            event_date Date,
            symbol String,
            market LowCardinality(String),
            ltp Float64,
            bid Nullable(Float64),
            ask Nullable(Float64),
            volume Int64,
            cumulative_volume Nullable(Int64),
            payload String
        ) ENGINE = MergeTree
        ORDER BY (event_date, symbol, event_time)
        """
        market_bars_ddl = f"""
        CREATE TABLE IF NOT EXISTS {self._settings.clickhouse_database}.market_bars (
            event_time DateTime64(3, 'UTC'),
            event_date Date,
            symbol String,
            market LowCardinality(String),
            timeframe LowCardinality(String),
            open Float64,
            high Float64,
            low Float64,
            close Float64,
            volume Int64,
            payload String
        ) ENGINE = MergeTree
        ORDER BY (event_date, symbol, timeframe, event_time)
        """
        for ddl in (execution_ddl, market_ticks_ddl, market_bars_ddl):
            response = await self._http_client.post(
                self._settings.clickhouse_http_url,
                params={"query": ddl},
                auth=(self._settings.clickhouse_user, self._settings.clickhouse_password or ""),
            )
            response.raise_for_status()

    async def _write_clickhouse(self, envelope: dict[str, Any]) -> None:
        if self._http_client is None:
            return
        stream = str(envelope.get("stream") or "execution")
        if stream == "market_ticks":
            row = {
                "event_time": envelope["event_time"],
                "event_date": envelope["event_time"][:10],
                "symbol": envelope.get("symbol", ""),
                "market": envelope.get("market", ""),
                "ltp": float(envelope.get("ltp") or 0.0),
                "bid": envelope.get("bid"),
                "ask": envelope.get("ask"),
                "volume": int(envelope.get("volume") or 0),
                "cumulative_volume": envelope.get("cumulative_volume"),
                "payload": self._dumps_text(envelope.get("payload", {})),
            }
            table = "market_ticks"
        elif stream == "market_bars":
            row = {
                "event_time": envelope["event_time"],
                "event_date": envelope["event_time"][:10],
                "symbol": envelope.get("symbol", ""),
                "market": envelope.get("market", ""),
                "timeframe": envelope.get("timeframe", ""),
                "open": float(envelope.get("open") or 0.0),
                "high": float(envelope.get("high") or 0.0),
                "low": float(envelope.get("low") or 0.0),
                "close": float(envelope.get("close") or 0.0),
                "volume": int(envelope.get("volume") or 0),
                "payload": self._dumps_text(envelope.get("payload", {})),
            }
            table = "market_bars"
        else:
            table = "execution_events"
            row = {
                "event_time": envelope["event_time"],
                "event_date": envelope["event_time"][:10],
                "event_id": envelope["event_id"],
                "source": envelope["source"],
                "event_type": envelope["event_type"],
                "symbol": envelope.get("symbol", ""),
                "order_id": envelope.get("order_id", ""),
                "trade_id": envelope.get("trade_id", ""),
                "strategy": envelope.get("strategy", ""),
                "market": envelope.get("market", ""),
                "payload": self._dumps_text(envelope.get("payload", {})),
            }
        response = await self._http_client.post(
            self._settings.clickhouse_http_url,
            params={
                "query": (
                    f"INSERT INTO {self._settings.clickhouse_database}.{table} FORMAT JSONEachRow"
                )
            },
            content=self._dumps_bytes(row),
            auth=(self._settings.clickhouse_user, self._settings.clickhouse_password or ""),
        )
        response.raise_for_status()

    async def _write_questdb(self, envelope: dict[str, Any]) -> None:
        writer = await self._get_questdb_writer()
        if writer is None:
            return
        stream = str(envelope.get("stream") or "execution")
        payload_json = self._dumps_text(envelope.get("payload", {})).replace('"', '\\"')
        if stream == "market_ticks":
            line = (
                "market_ticks"
                f",symbol={self._escape_tag(envelope.get('symbol') or '_')}"
                f",market={self._escape_tag(envelope.get('market') or '_')}"
                f" ltp={float(envelope.get('ltp') or 0.0)},"
                f"bid={self._questdb_float(envelope.get('bid'))},"
                f"ask={self._questdb_float(envelope.get('ask'))},"
                f"volume={int(envelope.get('volume') or 0)}i,"
                f"cumulative_volume={self._questdb_int(envelope.get('cumulative_volume'))},"
                f'payload="{self._escape_field(payload_json)}" '
                f"{self._to_ns(envelope['event_time'])}\n"
            )
        elif stream == "market_bars":
            line = (
                "market_bars"
                f",symbol={self._escape_tag(envelope.get('symbol') or '_')}"
                f",market={self._escape_tag(envelope.get('market') or '_')}"
                f",timeframe={self._escape_tag(envelope.get('timeframe') or '_')}"
                f" open={float(envelope.get('open') or 0.0)},"
                f"high={float(envelope.get('high') or 0.0)},"
                f"low={float(envelope.get('low') or 0.0)},"
                f"close={float(envelope.get('close') or 0.0)},"
                f"volume={int(envelope.get('volume') or 0)}i,"
                f'payload="{self._escape_field(payload_json)}" '
                f"{self._to_ns(envelope['event_time'])}\n"
            )
        else:
            line = (
                "execution_events"
                f",source={self._escape_tag(envelope['source'])}"
                f",event_type={self._escape_tag(envelope['event_type'])}"
                f",symbol={self._escape_tag(envelope.get('symbol') or '_')}"
                f",strategy={self._escape_tag(envelope.get('strategy') or '_')}"
                f",market={self._escape_tag(envelope.get('market') or '_')}"
                f' event_id="{self._escape_field(envelope["event_id"])}",'
                f'order_id="{self._escape_field(envelope.get("order_id") or "")}",'
                f'trade_id="{self._escape_field(envelope.get("trade_id") or "")}",'
                f'payload="{self._escape_field(payload_json)}" '
                f"{self._to_ns(envelope['event_time'])}\n"
            )
        writer.write(line.encode("utf-8"))
        await writer.drain()

    async def _get_questdb_writer(self) -> asyncio.StreamWriter | None:
        async with self._questdb_lock:
            if self._questdb_writer is not None:
                return self._questdb_writer
            try:
                _, writer = await asyncio.open_connection(
                    self._settings.questdb_host,
                    self._settings.questdb_ilp_port,
                )
            except Exception as exc:
                logger.warning("questdb_ilp_connect_failed", error=str(exc))
                return None
            self._questdb_writer = writer
            return self._questdb_writer

    @staticmethod
    def _normalize_agent_event(event: AgentEvent) -> dict[str, Any]:
        metadata = dict(event.metadata or {})
        symbol = str(metadata.get("symbol") or "")
        return {
            "event_id": event.event_id,
            "event_time": event.timestamp.astimezone(timezone.utc).isoformat(timespec="milliseconds"),
            "source": "agent",
            "event_type": event.event_type.value,
            "symbol": symbol,
            "order_id": str(metadata.get("order_id") or ""),
            "trade_id": str(metadata.get("trade_id") or ""),
            "strategy": str(metadata.get("strategy") or ""),
            "market": str(metadata.get("market") or _infer_market(symbol)),
            "payload": event.to_dict(),
        }

    @staticmethod
    def _normalize_broker_event(payload: dict[str, Any]) -> dict[str, Any]:
        symbol = str(payload.get("symbol") or "")
        timestamp = payload.get("timestamp") or datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds")
        return {
            "event_id": f"broker-{payload.get('event_kind', 'event')}-{payload.get('order_id', '')}-{payload.get('trade_id', '') or timestamp}",
            "event_time": timestamp,
            "stream": "execution",
            "source": "broker",
            "event_type": str(payload.get("event_kind") or "broker"),
            "symbol": symbol,
            "order_id": str(payload.get("order_id") or ""),
            "trade_id": str(payload.get("trade_id") or ""),
            "strategy": "",
            "market": _infer_market(symbol),
            "payload": payload,
        }

    @staticmethod
    def _normalize_tick_event(payload: dict[str, Any]) -> dict[str, Any]:
        symbol = str(payload.get("symbol") or "")
        timestamp = str(payload.get("timestamp") or datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds"))
        return {
            "event_id": f"tick-{symbol}-{timestamp}",
            "event_time": timestamp,
            "stream": "market_ticks",
            "source": "tick_broker",
            "event_type": "market_tick",
            "symbol": symbol,
            "market": _infer_market(symbol),
            "ltp": float(payload.get("ltp") or 0.0),
            "bid": payload.get("bid"),
            "ask": payload.get("ask"),
            "volume": int(payload.get("volume") or 0),
            "cumulative_volume": payload.get("cumulative_volume"),
            "payload": payload,
        }

    @staticmethod
    def _normalize_candle_event(payload: dict[str, Any]) -> dict[str, Any]:
        symbol = str(payload.get("symbol") or "")
        timestamp = str(payload.get("timestamp") or datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds"))
        return {
            "event_id": f"bar-{symbol}-{payload.get('timeframe', '')}-{timestamp}",
            "event_time": timestamp,
            "stream": "market_bars",
            "source": "candle_broker",
            "event_type": "market_bar",
            "symbol": symbol,
            "market": _infer_market(symbol),
            "timeframe": str(payload.get("timeframe") or ""),
            "open": float(payload.get("open") or 0.0),
            "high": float(payload.get("high") or 0.0),
            "low": float(payload.get("low") or 0.0),
            "close": float(payload.get("close") or 0.0),
            "volume": int(payload.get("volume") or 0),
            "payload": payload,
        }

    def _transport_names(self, stream: str) -> tuple[str, str]:
        subject_map = {
            "execution": (
                f"{self._settings.nats_stream_prefix}.execution.events",
                f"{self._settings.kafka_topic_prefix}.execution.events",
            ),
            "market_ticks": (
                f"{self._settings.nats_stream_prefix}.market.ticks",
                f"{self._settings.kafka_topic_prefix}.market.ticks",
            ),
            "market_bars": (
                f"{self._settings.nats_stream_prefix}.market.bars",
                f"{self._settings.kafka_topic_prefix}.market.bars",
            ),
        }
        return subject_map.get(
            stream,
            (
                f"{self._settings.nats_stream_prefix}.execution.events",
                f"{self._settings.kafka_topic_prefix}.execution.events",
            ),
        )

    @staticmethod
    def _escape_tag(value: str) -> str:
        return str(value or "_").replace("\\", "\\\\").replace(" ", "\\ ").replace(",", "\\,").replace("=", "\\=")

    @staticmethod
    def _escape_field(value: str) -> str:
        return str(value or "").replace("\\", "\\\\").replace('"', '\\"')

    @staticmethod
    def _to_ns(timestamp: str) -> int:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1_000_000_000)

    @staticmethod
    def _questdb_float(value: Any) -> str:
        if value in (None, ""):
            return "null"
        return str(float(value))

    @staticmethod
    def _questdb_int(value: Any) -> str:
        if value in (None, ""):
            return "null"
        return f"{int(value)}i"

    @staticmethod
    def _dumps_bytes(payload: dict[str, Any]) -> bytes:
        if orjson is not None:
            return orjson.dumps(payload)
        return json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")

    @staticmethod
    def _dumps_text(payload: dict[str, Any]) -> str:
        if orjson is not None:
            return orjson.dumps(payload).decode("utf-8")
        return json.dumps(payload, separators=(",", ":"), default=str)


def _infer_market(symbol: str) -> str:
    token = str(symbol or "").strip().upper()
    if token.startswith("US:"):
        return "US"
    if token.startswith("CRYPTO:"):
        return "CRYPTO"
    if token.startswith("NSE:") or token.startswith("BSE:"):
        return "NSE"
    return ""
