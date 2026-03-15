"""Tests for analytics sink normalization before backend writes."""

from __future__ import annotations

import json

import pytest

from src.config.settings import Settings
from src.streaming.event_analytics_sink import EventAnalyticsSink


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None


class _FakeHttpClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def post(self, url: str, *, params=None, content=None, auth=None):  # type: ignore[no-untyped-def]
        self.calls.append(
            {
                "url": url,
                "params": params,
                "content": content,
                "auth": auth,
            }
        )
        return _FakeResponse()


class _FakeQuestDbWriter:
    def __init__(self, fail_first: bool = False) -> None:
        self.fail_first = fail_first
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, payload: bytes) -> None:
        self.writes.append(payload)

    async def drain(self) -> None:
        if self.fail_first:
            self.fail_first = False
            raise ConnectionResetError("connection reset")

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


@pytest.mark.asyncio
async def test_event_analytics_sink_normalizes_clickhouse_market_tick_payload() -> None:
    settings = Settings(
        clickhouse_enabled=True,
        clickhouse_host="clickhouse",
        clickhouse_http_port=8123,
        clickhouse_database="ai_trader",
        clickhouse_user="ai_trader_app",
        clickhouse_password="secret",
        questdb_enabled=False,
        _env_file=None,
    )
    sink = EventAnalyticsSink(settings)
    fake_http = _FakeHttpClient()
    sink._http_client = fake_http

    await sink._write_clickhouse(
        {
            "stream": "market_ticks",
            "event_time": "2026-03-15T06:36:25.999+00:00",
            "symbol": "CRYPTO:BTCUSDT",
            "market": "CRYPTO",
            "ltp": 71420.55,
            "bid": "",
            "ask": None,
            "volume": "0",
            "cumulative_volume": "",
            "payload": {"foo": "bar"},
        }
    )

    assert len(fake_http.calls) == 1
    call = fake_http.calls[0]
    assert call["auth"] == ("ai_trader_app", "secret")
    payload = json.loads(call["content"])
    assert payload["event_time"] == "2026-03-15 06:36:25.999"
    assert payload["event_date"] == "2026-03-15"
    assert payload["bid"] is None
    assert payload["ask"] is None
    assert payload["cumulative_volume"] is None
    assert payload["volume"] == 0


@pytest.mark.asyncio
async def test_event_analytics_sink_reconnects_questdb_writer_on_reset() -> None:
    settings = Settings(
        clickhouse_enabled=False,
        questdb_enabled=True,
        _env_file=None,
    )
    sink = EventAnalyticsSink(settings)
    first = _FakeQuestDbWriter(fail_first=True)
    second = _FakeQuestDbWriter()
    calls = 0

    async def _get_writer() -> _FakeQuestDbWriter:
        nonlocal calls
        calls += 1
        writer = first if calls == 1 else second
        sink._questdb_writer = writer
        return writer

    sink._get_questdb_writer = _get_writer  # type: ignore[method-assign]

    await sink._write_questdb(
        {
            "stream": "market_ticks",
            "event_time": "2026-03-15T06:36:25.999+00:00",
            "symbol": "CRYPTO:BTCUSDT",
            "market": "CRYPTO",
            "ltp": 71420.55,
            "bid": None,
            "ask": None,
            "volume": 0,
            "cumulative_volume": None,
            "payload": {"foo": "bar"},
        }
    )

    assert first.closed is True
    assert len(first.writes) == 1
    assert len(second.writes) == 1
