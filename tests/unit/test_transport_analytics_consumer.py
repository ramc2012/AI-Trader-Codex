"""Tests for transport-based analytics consumption."""

from __future__ import annotations

import asyncio

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
