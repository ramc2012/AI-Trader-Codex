"""Tests for the real-time tick data collector."""

import time
from datetime import datetime

import pytest

from src.config.market_hours import IST
from src.data.collectors.tick_collector import (
    CandleAggregator,
    Tick,
    TickCollector,
    TickCollectorStats,
)


# =========================================================================
# Tick Tests
# =========================================================================


class TestTick:
    def test_to_dict(self) -> None:
        tick = Tick(
            symbol="NSE:NIFTY50-INDEX",
            timestamp=datetime(2024, 2, 8, 10, 0, tzinfo=IST),
            ltp=22150.5,
            volume=1000,
        )
        d = tick.to_dict()
        assert d["symbol"] == "NSE:NIFTY50-INDEX"
        assert d["ltp"] == 22150.5
        assert d["bid"] is None

    def test_default_values(self) -> None:
        tick = Tick(
            symbol="NSE:NIFTY50-INDEX",
            timestamp=datetime(2024, 2, 8, tzinfo=IST),
            ltp=22150.0,
        )
        assert tick.bid is None
        assert tick.ask is None
        assert tick.volume == 0


# =========================================================================
# CandleAggregator Tests
# =========================================================================


class TestCandleAggregator:
    def test_single_tick_no_candle(self) -> None:
        agg = CandleAggregator(symbol="S")
        tick = Tick("S", datetime(2024, 2, 8, 9, 15, 10, tzinfo=IST), 100.0, volume=10)
        result = agg.add_tick(tick)
        assert result is None  # minute not complete

    def test_minute_rollover_emits_candle(self) -> None:
        agg = CandleAggregator(symbol="S")
        # Ticks in minute 9:15
        agg.add_tick(Tick("S", datetime(2024, 2, 8, 9, 15, 5, tzinfo=IST), 100.0, volume=10))
        agg.add_tick(Tick("S", datetime(2024, 2, 8, 9, 15, 30, tzinfo=IST), 105.0, volume=20))
        agg.add_tick(Tick("S", datetime(2024, 2, 8, 9, 15, 55, tzinfo=IST), 98.0, volume=15))

        # Tick in minute 9:16 — should emit 9:15 candle
        candle = agg.add_tick(
            Tick("S", datetime(2024, 2, 8, 9, 16, 5, tzinfo=IST), 102.0, volume=25)
        )
        assert candle is not None
        assert candle["open"] == 100.0
        assert candle["high"] == 105.0
        assert candle["low"] == 98.0
        assert candle["close"] == 98.0
        assert candle["volume"] == 45  # 10 + 20 + 15
        assert candle["timeframe"] == "1"

    def test_flush_returns_in_progress(self) -> None:
        agg = CandleAggregator(symbol="S")
        agg.add_tick(Tick("S", datetime(2024, 2, 8, 9, 15, 5, tzinfo=IST), 100.0, volume=10))
        candle = agg.flush()
        assert candle is not None
        assert candle["open"] == 100.0
        assert candle["close"] == 100.0

    def test_flush_empty_returns_none(self) -> None:
        agg = CandleAggregator(symbol="S")
        assert agg.flush() is None

    def test_multiple_minutes(self) -> None:
        agg = CandleAggregator(symbol="S")
        # Minute 1
        agg.add_tick(Tick("S", datetime(2024, 2, 8, 9, 15, 0, tzinfo=IST), 100.0, volume=10))
        # Minute 2 — emits candle for minute 1
        c1 = agg.add_tick(Tick("S", datetime(2024, 2, 8, 9, 16, 0, tzinfo=IST), 110.0, volume=20))
        assert c1 is not None
        assert c1["open"] == 100.0
        # Minute 3 — emits candle for minute 2
        c2 = agg.add_tick(Tick("S", datetime(2024, 2, 8, 9, 17, 0, tzinfo=IST), 120.0, volume=30))
        assert c2 is not None
        assert c2["open"] == 110.0


# =========================================================================
# TickCollector Parse/Validate Tests
# =========================================================================


class TestTickCollectorParsing:
    def _make_collector(self) -> TickCollector:
        return TickCollector(
            access_token="TEST:token",
            symbols=["NSE:NIFTY50-INDEX"],
            batch_interval=10,
        )

    def test_parse_valid_message(self) -> None:
        tc = self._make_collector()
        msg = {
            "symbol": "NSE:NIFTY50-INDEX",
            "ltp": 22150.5,
            "timestamp": 1707369000,
            "bid": 22150.0,
            "ask": 22151.0,
            "vol_traded_today": 150000,
            "open_price": 22100.0,
            "high_price": 22200.0,
            "low_price": 22050.0,
            "prev_close_price": 22120.0,
        }
        tick = tc._parse_tick(msg)
        assert tick is not None
        assert tick.symbol == "NSE:NIFTY50-INDEX"
        assert tick.ltp == 22150.5
        # First tick uses volume delta; baseline tick emits 0.
        assert tick.volume == 0

    def test_parse_volume_delta_between_ticks(self) -> None:
        tc = self._make_collector()
        first = {
            "symbol": "NSE:NIFTY50-INDEX",
            "ltp": 22150.5,
            "timestamp": 1707369000,
            "vol_traded_today": 150000,
        }
        second = {
            "symbol": "NSE:NIFTY50-INDEX",
            "ltp": 22150.7,
            "timestamp": 1707369001,
            "vol_traded_today": 150040,
        }
        t1 = tc._parse_tick(first)
        t2 = tc._parse_tick(second)
        assert t1 is not None
        assert t2 is not None
        assert t2.volume == 40

    def test_parse_rejects_outlier_jump(self) -> None:
        tc = self._make_collector()
        first = tc._parse_tick({"symbol": "NSE:NIFTY50-INDEX", "ltp": 22000.0, "vol_traded_today": 1})
        outlier = tc._parse_tick({"symbol": "NSE:NIFTY50-INDEX", "ltp": 25000.0, "vol_traded_today": 2})
        assert first is not None
        assert outlier is None

    def test_parse_missing_symbol(self) -> None:
        tc = self._make_collector()
        msg = {"ltp": 22150.5}
        assert tc._parse_tick(msg) is None

    def test_parse_missing_ltp(self) -> None:
        tc = self._make_collector()
        msg = {"symbol": "NSE:NIFTY50-INDEX"}
        assert tc._parse_tick(msg) is None

    def test_parse_negative_ltp(self) -> None:
        tc = self._make_collector()
        msg = {"symbol": "NSE:NIFTY50-INDEX", "ltp": -100.0}
        assert tc._parse_tick(msg) is None

    def test_parse_non_dict(self) -> None:
        tc = self._make_collector()
        assert tc._parse_tick("not a dict") is None
        assert tc._parse_tick(None) is None
        assert tc._parse_tick(42) is None

    def test_parse_no_timestamp_uses_now(self) -> None:
        tc = self._make_collector()
        msg = {"symbol": "NSE:NIFTY50-INDEX", "ltp": 22150.5}
        tick = tc._parse_tick(msg)
        assert tick is not None
        assert tick.timestamp.tzinfo is not None


# =========================================================================
# TickCollector Batch Tests
# =========================================================================


class TestTickCollectorBatching:
    def test_flush_empty_buffer(self) -> None:
        tc = TickCollector(
            access_token="TEST:token",
            symbols=["NSE:NIFTY50-INDEX"],
        )
        tc._flush_batch()
        assert tc.stats.batches_flushed == 0  # nothing to flush

    def test_flush_calls_on_batch(self) -> None:
        batches: list = []
        tc = TickCollector(
            access_token="TEST:token",
            symbols=["NSE:NIFTY50-INDEX"],
            on_batch=lambda b: batches.append(b),
        )
        tc._tick_buffer = [{"symbol": "S", "ltp": 100.0}]
        tc._flush_batch()
        assert len(batches) == 1
        assert len(batches[0]) == 1
        assert tc.stats.batches_flushed == 1

    def test_handle_message_buffers_tick(self) -> None:
        tc = TickCollector(
            access_token="TEST:token",
            symbols=["NSE:NIFTY50-INDEX"],
            batch_interval=9999,  # won't auto-flush
        )
        # Set last flush time to now so elapsed < batch_interval
        tc._last_flush_time = time.monotonic()
        msg = {"symbol": "NSE:NIFTY50-INDEX", "ltp": 22150.5, "timestamp": 1707369000}
        tc._handle_message(msg)
        assert tc.stats.ticks_received == 1
        assert len(tc._tick_buffer) == 1


# =========================================================================
# Stats Tests
# =========================================================================


class TestTickCollectorStats:
    def test_initial_stats(self) -> None:
        stats = TickCollectorStats()
        assert stats.ticks_received == 0
        assert stats.uptime_seconds == 0.0

    def test_uptime_with_start(self) -> None:
        stats = TickCollectorStats(started_at=datetime.now(tz=IST))
        assert stats.uptime_seconds >= 0.0
