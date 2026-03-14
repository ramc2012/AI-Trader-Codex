"""Tests for NATS-to-Kafka transport mirroring."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest

from src.config.settings import Settings
from src.streaming.transport_mirror import TransportMirror


class _FakeKafkaProducer:
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict]] = []
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send_and_wait(self, topic: str, payload: dict) -> None:
        self.messages.append((topic, payload))


class _CaptureKafkaProducer(_FakeKafkaProducer):
    def __init__(self, **_: object) -> None:
        super().__init__()


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
async def test_transport_mirror_subscribes_to_all_hot_subjects(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        transport_mirror_enabled=True,
        nats_enabled=True,
        kafka_enabled=True,
        nats_stream_prefix="test_stream",
        kafka_topic_prefix="test_topic",
        _env_file=None,
    )
    mirror = TransportMirror(settings=settings)
    fake_nats = _FakeNatsClient()

    async def _connect(url: str) -> _FakeNatsClient:
        assert url == settings.nats_url
        return fake_nats

    monkeypatch.setitem(sys.modules, "nats", SimpleNamespace(connect=_connect))

    await mirror._connect_nats()

    assert fake_nats.subjects == [
        "test_stream.execution.events",
        "test_stream.execution.signals",
        "test_stream.market.ticks",
        "test_stream.market.bars",
    ]


@pytest.mark.asyncio
async def test_transport_mirror_routes_signal_stream_to_kafka() -> None:
    settings = Settings(
        transport_mirror_enabled=True,
        nats_enabled=True,
        kafka_enabled=True,
        kafka_topic_prefix="test_topic",
        _env_file=None,
    )
    mirror = TransportMirror(settings=settings)
    fake_kafka = _FakeKafkaProducer()
    mirror._kafka_producer = fake_kafka
    mirror._running = True
    mirror._process_task = asyncio.create_task(mirror._process_loop())

    try:
        await mirror._enqueue(
            {
                "stream": "execution_signals",
                "event_time": "2026-03-15T12:00:00.000+00:00",
                "event_id": "sig-1",
                "source": "execution_core",
                "event_type": "signal_candidate",
                "signal_type": "BUY",
                "symbol": "CRYPTO:BTCUSDT",
                "market": "CRYPTO",
                "timeframe": "1",
                "strategy": "Rust_EMA_Crossover",
                "price": 65000.0,
                "payload": {"ema_fast": 64990.0, "ema_slow": 64980.0},
            }
        )
        await asyncio.sleep(0.05)
    finally:
        await mirror.stop()

    assert fake_kafka.messages == [
        (
            "test_topic.execution.signals",
            {
                "stream": "execution_signals",
                "event_time": "2026-03-15T12:00:00.000+00:00",
                "event_id": "sig-1",
                "source": "execution_core",
                "event_type": "signal_candidate",
                "signal_type": "BUY",
                "symbol": "CRYPTO:BTCUSDT",
                "market": "CRYPTO",
                "timeframe": "1",
                "strategy": "Rust_EMA_Crossover",
                "price": 65000.0,
                "payload": {"ema_fast": 64990.0, "ema_slow": 64980.0},
            },
        )
    ]


@pytest.mark.asyncio
async def test_transport_mirror_connects_kafka_producer(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        transport_mirror_enabled=True,
        nats_enabled=True,
        kafka_enabled=True,
        _env_file=None,
    )
    mirror = TransportMirror(settings=settings)

    monkeypatch.setitem(
        sys.modules,
        "aiokafka",
        SimpleNamespace(AIOKafkaProducer=_CaptureKafkaProducer),
    )

    await mirror._connect_kafka()

    assert mirror._kafka_producer is not None
    assert mirror._kafka_producer.started is True  # type: ignore[union-attr]
