"""Tests for transport-based analytics consumption."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest

from src.config.settings import Settings
from src.streaming.transport_analytics_consumer import TransportAnalyticsConsumer


class _FakeSink:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.envelopes: list[dict] = []
        self.enabled = True

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def write_envelope(self, envelope: dict) -> None:
        self.envelopes.append(envelope)


class _FakeKafkaMessage:
    def __init__(self, value: dict) -> None:
        self.value = value


class _FakeKafkaConsumer:
    def __init__(self, messages: list[dict]) -> None:
        self._messages = list(messages)
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    def __aiter__(self) -> "_FakeKafkaConsumer":
        return self

    async def __anext__(self) -> _FakeKafkaMessage:
        await asyncio.sleep(0)
        if not self._messages:
            raise StopAsyncIteration
        return _FakeKafkaMessage(self._messages.pop(0))


class _CaptureKafkaConsumer:
    def __init__(self, *topics: str, **_: object) -> None:
        self.topics = topics
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


class _FakeNatsSubscription:
    def __init__(self, subject: str) -> None:
        self.subject = subject
        self.unsubscribed = False

    async def unsubscribe(self) -> None:
        self.unsubscribed = True


class _FakeNatsClient:
    def __init__(self) -> None:
        self.subjects: list[str] = []
        self.closed = False

    async def subscribe(self, subject: str, cb=None):  # type: ignore[no-untyped-def]
        self.subjects.append(subject)
        return _FakeNatsSubscription(subject)

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_transport_analytics_consumer_consumes_kafka_envelopes() -> None:
    sink = _FakeSink()
    settings = Settings(
        analytics_consumer_enabled=True,
        analytics_consumer_source="kafka",
        kafka_enabled=True,
        clickhouse_enabled=False,
        questdb_enabled=False,
        _env_file=None,
    )
    consumer = TransportAnalyticsConsumer(settings=settings, sink=sink)
    fake_kafka = _FakeKafkaConsumer(
        [
            {
                "event_id": "evt-1",
                "event_time": "2026-03-14T10:00:00.000+00:00",
                "stream": "execution",
                "source": "agent",
                "event_type": "order_placed",
                "symbol": "NSE:NIFTY50-INDEX",
                "order_id": "ORD-1",
                "trade_id": "",
                "strategy": "EMA_Crossover",
                "market": "NSE",
                "payload": {"foo": "bar"},
            }
        ]
    )

    async def _connect_kafka() -> None:
        consumer._kafka_consumer = fake_kafka

    consumer._connect_kafka = _connect_kafka  # type: ignore[method-assign]

    await consumer.start()
    await asyncio.sleep(0.1)
    await consumer.stop()

    assert sink.started is True
    assert sink.stopped is True
    assert len(sink.envelopes) == 1
    assert sink.envelopes[0]["event_id"] == "evt-1"
    assert consumer.snapshot()["consumed"] == 1


@pytest.mark.asyncio
async def test_transport_analytics_consumer_subscribes_to_signal_topics(monkeypatch: pytest.MonkeyPatch) -> None:
    sink = _FakeSink()
    settings = Settings(
        analytics_consumer_enabled=True,
        analytics_consumer_source="kafka",
        kafka_enabled=True,
        clickhouse_enabled=False,
        questdb_enabled=False,
        kafka_topic_prefix="test_topic",
        _env_file=None,
    )
    consumer = TransportAnalyticsConsumer(settings=settings, sink=sink)
    monkeypatch.setitem(
        sys.modules,
        "aiokafka",
        SimpleNamespace(AIOKafkaConsumer=_CaptureKafkaConsumer),
    )

    await consumer._connect_kafka()

    assert consumer._kafka_consumer is not None
    assert consumer._kafka_consumer.topics == (  # type: ignore[union-attr]
        "test_topic.execution.events",
        "test_topic.execution.signals",
        "test_topic.market.ticks",
        "test_topic.market.bars",
    )


@pytest.mark.asyncio
async def test_transport_analytics_consumer_subscribes_to_signal_subjects(monkeypatch: pytest.MonkeyPatch) -> None:
    sink = _FakeSink()
    settings = Settings(
        analytics_consumer_enabled=True,
        analytics_consumer_source="nats",
        nats_enabled=True,
        clickhouse_enabled=False,
        questdb_enabled=False,
        nats_stream_prefix="test_stream",
        _env_file=None,
    )
    consumer = TransportAnalyticsConsumer(settings=settings, sink=sink)
    fake_nats = _FakeNatsClient()

    async def _connect(url: str) -> _FakeNatsClient:
        assert url == settings.nats_url
        return fake_nats

    monkeypatch.setitem(sys.modules, "nats", SimpleNamespace(connect=_connect))

    await consumer._connect_nats()

    assert fake_nats.subjects == [
        "test_stream.execution.events",
        "test_stream.execution.signals",
        "test_stream.market.ticks",
        "test_stream.market.bars",
    ]
