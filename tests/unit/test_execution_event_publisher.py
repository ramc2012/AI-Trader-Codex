"""Tests for the execution event publisher."""

from __future__ import annotations

import asyncio

import pytest

from src.agent.events import AgentEvent, AgentEventBus, AgentEventType
from src.config.market_hours import IST
from src.config.settings import Settings
from src.data.live.tick_stream import TickStreamBroker
from src.streaming.execution_event_publisher import ExecutionEventPublisher


class _FakeNatsClient:
    def __init__(self) -> None:
        self.messages: list[tuple[str, bytes]] = []

    async def publish(self, subject: str, payload: bytes) -> None:
        self.messages.append((subject, payload))

    async def close(self) -> None:
        return None


class _FakeKafkaProducer:
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict]] = []

    async def send_and_wait(self, topic: str, payload: dict) -> None:
        self.messages.append((topic, payload))

    async def stop(self) -> None:
        return None


@pytest.mark.asyncio
async def test_execution_event_publisher_emits_agent_and_broker_events() -> None:
    event_bus = AgentEventBus()
    broker = TickStreamBroker()
    broker.bind_loop(asyncio.get_running_loop())
    settings = Settings(
        nats_enabled=True,
        kafka_enabled=True,
        clickhouse_enabled=False,
        questdb_enabled=False,
        nats_stream_prefix="test_stream",
        kafka_topic_prefix="test_topic",
    )

    publisher = ExecutionEventPublisher(
        settings=settings,
        agent_event_bus=event_bus,
        broker_event_broker=broker,
    )
    fake_nats = _FakeNatsClient()
    fake_kafka = _FakeKafkaProducer()

    async def _connect_nats() -> None:
        publisher._nats_client = fake_nats

    async def _connect_kafka() -> None:
        publisher._kafka_producer = fake_kafka

    publisher._connect_nats = _connect_nats  # type: ignore[method-assign]
    publisher._connect_kafka = _connect_kafka  # type: ignore[method-assign]

    await publisher.start()
    await event_bus.emit(
        AgentEvent(
            event_type=AgentEventType.ORDER_FILLED,
            title="Order Filled",
            message="filled",
            metadata={
                "symbol": "NSE:NIFTY26MAR22500CE",
                "order_id": "ORD-1",
                "strategy": "EMA_Crossover",
                "market": "NSE",
            },
        )
    )
    broker.publish(
        {
            "type": "broker_event",
            "event_kind": "trade",
            "symbol": "NSE:NIFTY26MAR22500CE",
            "timestamp": "2026-03-14T09:20:00+05:30",
            "order_id": "ORD-1",
            "trade_id": "TRD-1",
            "payload": {"foo": "bar"},
        }
    )

    await asyncio.sleep(0.1)
    await publisher.stop()

    assert len(fake_nats.messages) == 2
    assert all(subject == "test_stream.execution.events" for subject, _ in fake_nats.messages)
    assert len(fake_kafka.messages) == 2
    assert all(topic == "test_topic.execution.events" for topic, _ in fake_kafka.messages)
    assert publisher.stats.published_events >= 2


@pytest.mark.asyncio
async def test_execution_event_publisher_emits_tick_and_candle_market_streams() -> None:
    tick_broker = TickStreamBroker()
    tick_broker.bind_loop(asyncio.get_running_loop())
    candle_broker = TickStreamBroker()
    candle_broker.bind_loop(asyncio.get_running_loop())
    settings = Settings(
        nats_enabled=True,
        kafka_enabled=True,
        clickhouse_enabled=False,
        questdb_enabled=False,
        nats_stream_prefix="test_stream",
        kafka_topic_prefix="test_topic",
    )

    publisher = ExecutionEventPublisher(
        settings=settings,
        tick_broker=tick_broker,
        candle_broker=candle_broker,
    )
    fake_nats = _FakeNatsClient()
    fake_kafka = _FakeKafkaProducer()

    async def _connect_nats() -> None:
        publisher._nats_client = fake_nats

    async def _connect_kafka() -> None:
        publisher._kafka_producer = fake_kafka

    publisher._connect_nats = _connect_nats  # type: ignore[method-assign]
    publisher._connect_kafka = _connect_kafka  # type: ignore[method-assign]

    await publisher.start()
    tick_broker.publish(
        {
            "type": "tick",
            "symbol": "CRYPTO:BTCUSDT",
            "timestamp": "2026-03-14T09:21:00+05:30",
            "ltp": 64500.5,
            "bid": 64500.1,
            "ask": 64501.0,
            "volume": 42,
            "cumulative_volume": 420,
        }
    )
    candle_broker.publish(
        {
            "type": "candle",
            "symbol": "NSE:NIFTY50-INDEX",
            "timeframe": "1",
            "timestamp": "2026-03-14T09:22:00+05:30",
            "open": 22410.0,
            "high": 22425.5,
            "low": 22400.0,
            "close": 22422.1,
            "volume": 1250,
        }
    )

    await asyncio.sleep(0.1)
    await publisher.stop()

    assert [subject for subject, _ in fake_nats.messages] == [
        "test_stream.market.ticks",
        "test_stream.market.bars",
    ]
    assert [topic for topic, _ in fake_kafka.messages] == [
        "test_topic.market.ticks",
        "test_topic.market.bars",
    ]
    assert fake_kafka.messages[0][1]["event_type"] == "market_tick"
    assert fake_kafka.messages[1][1]["event_type"] == "market_bar"
    assert fake_kafka.messages[0][1]["market"] == "CRYPTO"
    assert fake_kafka.messages[1][1]["market"] == "NSE"


def test_execution_event_publisher_normalizes_market_and_ids() -> None:
    timestamp = "2026-03-14T09:20:00+05:30"
    normalized = ExecutionEventPublisher._normalize_broker_event(
        {
            "event_kind": "order",
            "symbol": "CRYPTO:BTCUSDT",
            "timestamp": timestamp,
            "order_id": "ORD-2",
            "trade_id": "",
            "payload": {"status": "OPEN"},
        }
    )

    assert normalized["source"] == "broker"
    assert normalized["event_type"] == "order"
    assert normalized["market"] == "CRYPTO"
    assert normalized["order_id"] == "ORD-2"
    assert normalized["event_time"] == timestamp


def test_execution_event_publisher_normalizes_market_tick_and_candle_events() -> None:
    tick_timestamp = "2026-03-14T09:23:00+05:30"
    tick = ExecutionEventPublisher._normalize_tick_event(
        {
            "symbol": "US:SPY",
            "timestamp": tick_timestamp,
            "ltp": 510.25,
            "bid": 510.2,
            "ask": 510.3,
            "volume": 30,
            "cumulative_volume": 120,
        }
    )
    candle = ExecutionEventPublisher._normalize_candle_event(
        {
            "symbol": "NSE:NIFTY50-INDEX",
            "timeframe": "5",
            "timestamp": tick_timestamp,
            "open": 22410.0,
            "high": 22430.0,
            "low": 22400.0,
            "close": 22420.0,
            "volume": 1000,
        }
    )

    assert tick["stream"] == "market_ticks"
    assert tick["event_type"] == "market_tick"
    assert tick["market"] == "US"
    assert tick["event_time"] == tick_timestamp
    assert candle["stream"] == "market_bars"
    assert candle["event_type"] == "market_bar"
    assert candle["market"] == "NSE"
    assert candle["timeframe"] == "5"
