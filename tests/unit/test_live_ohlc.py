"""Tests for live candle ingestion into the OHLC cache."""

from __future__ import annotations

from datetime import datetime

import pytest

from src.config.market_hours import IST
from src.data.live.live_ohlc import LiveOHLCCacheBridge
from src.data.ohlc_cache import OHLCCache


@pytest.mark.asyncio
async def test_ohlc_cache_upsert_can_replace_recent_timestamp_in_short_series() -> None:
    cache = OHLCCache()
    await cache.upsert(
        "NSE:NIFTY50-INDEX",
        "3",
        [{"timestamp": "2026-03-14T03:45:00", "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "volume": 10}],
    )
    await cache.upsert(
        "NSE:NIFTY50-INDEX",
        "3",
        [{"timestamp": "2026-03-14T03:45:00", "open": 100.0, "high": 103.0, "low": 98.0, "close": 102.0, "volume": 25}],
    )

    frame = cache.as_dataframe("NSE:NIFTY50-INDEX", "3", limit=10)

    assert len(frame) == 1
    assert float(frame.iloc[-1]["high"]) == 103.0
    assert int(frame.iloc[-1]["volume"]) == 25


@pytest.mark.asyncio
async def test_live_ohlc_bridge_updates_cache_and_aggregates() -> None:
    cache = OHLCCache()
    bridge = LiveOHLCCacheBridge(cache=cache)

    await bridge._ingest_async(
        {
            "symbol": "NSE:NIFTY50-INDEX",
            "timeframe": "1",
            "timestamp": datetime(2026, 3, 14, 9, 15, tzinfo=IST),
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 101.0,
            "volume": 10,
        }
    )
    await bridge._ingest_async(
        {
            "symbol": "NSE:NIFTY50-INDEX",
            "timeframe": "1",
            "timestamp": datetime(2026, 3, 14, 9, 16, tzinfo=IST),
            "open": 101.0,
            "high": 103.0,
            "low": 100.0,
            "close": 102.0,
            "volume": 15,
        }
    )

    minute = cache.as_dataframe("NSE:NIFTY50-INDEX", "1", limit=10)
    three = cache.as_dataframe("NSE:NIFTY50-INDEX", "3", limit=10)
    five = cache.as_dataframe("NSE:NIFTY50-INDEX", "5", limit=10)

    assert len(minute) == 2
    assert len(three) == 1
    assert len(five) == 1

    row = three.iloc[-1]
    assert float(row["open"]) == 100.0
    assert float(row["high"]) == 103.0
    assert float(row["low"]) == 99.0
    assert float(row["close"]) == 102.0
    assert int(row["volume"]) == 25
