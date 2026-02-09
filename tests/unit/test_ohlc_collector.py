"""Tests for the OHLC data collector."""

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fyers_apiv3.fyersModel import FyersModel

from src.config.market_hours import IST
from src.data.collectors.ohlc_collector import (
    Candle,
    CollectionProgress,
    OHLCCollector,
)
from src.integrations.fyers_client import FyersClient
from src.utils.exceptions import DataFetchError, DataValidationError


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def mock_fyers_client() -> FyersClient:
    """Return a FyersClient with mocked internals."""
    with patch("src.integrations.fyers_client.get_settings") as mock_settings:
        settings = MagicMock()
        settings.fyers_app_id = "TEST"
        settings.fyers_secret_key = "TEST"
        settings.fyers_redirect_uri = "http://localhost/callback"
        settings.fyers_rate_limit_per_sec = 100
        mock_settings.return_value = settings

        client = FyersClient()
        client._access_token = "TEST:token"
        client._fyers = MagicMock(spec=FyersModel)
        return client


@pytest.fixture
def collector(mock_fyers_client: FyersClient) -> OHLCCollector:
    """Return an OHLCCollector with a mocked client."""
    return OHLCCollector(
        client=mock_fyers_client,
        symbols=["NSE:NIFTY50-INDEX"],
    )


def _make_raw_candle(ts: int, o: float, h: float, l: float, c: float, v: int) -> list:
    return [ts, o, h, l, c, v]


SAMPLE_CANDLES_RAW = [
    _make_raw_candle(1707369000, 22150.5, 22200.75, 22100.25, 22180.0, 150000),
    _make_raw_candle(1707372600, 22180.0, 22250.0, 22170.5, 22230.25, 120000),
    _make_raw_candle(1707376200, 22230.25, 22280.0, 22210.0, 22260.5, 130000),
]


# =========================================================================
# Candle Parsing Tests
# =========================================================================


class TestCandleParsing:
    def test_parse_valid_candle(self, collector: OHLCCollector) -> None:
        raw = _make_raw_candle(1707369000, 22150.5, 22200.75, 22100.25, 22180.0, 150000)
        candle = collector._parse_candle("NSE:NIFTY50-INDEX", "D", raw)

        assert candle.symbol == "NSE:NIFTY50-INDEX"
        assert candle.timeframe == "D"
        assert candle.open == 22150.5
        assert candle.high == 22200.75
        assert candle.low == 22100.25
        assert candle.close == 22180.0
        assert candle.volume == 150000
        assert candle.timestamp.tzinfo is not None

    def test_parse_candle_invalid_ohlc(self, collector: OHLCCollector) -> None:
        # High < Low — invalid
        raw = _make_raw_candle(1707369000, 100.0, 90.0, 95.0, 92.0, 100)
        with pytest.raises(DataValidationError):
            collector._parse_candle("NSE:NIFTY50-INDEX", "D", raw)

    def test_parse_candle_negative_volume(self, collector: OHLCCollector) -> None:
        raw = _make_raw_candle(1707369000, 100.0, 110.0, 95.0, 105.0, -1)
        with pytest.raises(DataValidationError):
            collector._parse_candle("NSE:NIFTY50-INDEX", "D", raw)

    def test_parse_candle_too_few_fields(self, collector: OHLCCollector) -> None:
        raw = [1707369000, 100.0, 110.0]  # missing fields
        with pytest.raises(DataValidationError, match="Expected 6 fields"):
            collector._parse_candle("NSE:NIFTY50-INDEX", "D", raw)

    def test_candle_to_dict(self) -> None:
        candle = Candle(
            symbol="NSE:NIFTY50-INDEX",
            timeframe="D",
            timestamp=datetime(2024, 2, 8, 9, 15, tzinfo=IST),
            open=22150.5,
            high=22200.75,
            low=22100.25,
            close=22180.0,
            volume=150000,
        )
        d = candle.to_dict()
        assert d["symbol"] == "NSE:NIFTY50-INDEX"
        assert d["volume"] == 150000


# =========================================================================
# Date Chunking Tests
# =========================================================================


class TestDateChunking:
    def test_single_chunk_small_range(self, collector: OHLCCollector) -> None:
        chunks = collector._build_date_chunks(
            "D", date(2024, 1, 1), date(2024, 1, 10)
        )
        assert len(chunks) == 1
        assert chunks[0] == (date(2024, 1, 1), date(2024, 1, 10))

    def test_multiple_chunks_large_range(self, collector: OHLCCollector) -> None:
        # 1-min timeframe has 15-day chunks
        chunks = collector._build_date_chunks(
            "1", date(2024, 1, 1), date(2024, 2, 1)
        )
        assert len(chunks) >= 2
        # First chunk should be 15 days
        assert chunks[0] == (date(2024, 1, 1), date(2024, 1, 16))

    def test_empty_range(self, collector: OHLCCollector) -> None:
        chunks = collector._build_date_chunks(
            "D", date(2024, 2, 1), date(2024, 1, 1)
        )
        assert len(chunks) == 0

    def test_default_start_intraday(self, collector: OHLCCollector) -> None:
        end = date(2024, 2, 8)
        start = collector._default_start("5", end)
        assert (end - start).days == 90

    def test_default_start_daily(self, collector: OHLCCollector) -> None:
        end = date(2024, 2, 8)
        start = collector._default_start("D", end)
        assert (end - start).days == 730


# =========================================================================
# Collection Tests
# =========================================================================


class TestCollection:
    def test_collect_symbol_success(
        self, collector: OHLCCollector, mock_fyers_client: FyersClient
    ) -> None:
        mock_fyers_client._fyers.history.return_value = {
            "s": "ok",
            "candles": SAMPLE_CANDLES_RAW,
        }
        result = collector.collect_symbol(
            symbol="NSE:NIFTY50-INDEX",
            timeframe="D",
            start_date=date(2024, 2, 1),
            end_date=date(2024, 2, 8),
        )
        assert result.success is True
        assert len(result.candles) == 3
        assert result.progress.completed_chunks == 1
        assert result.duration_seconds > 0

    def test_collect_symbol_with_resume(
        self, collector: OHLCCollector, mock_fyers_client: FyersClient
    ) -> None:
        mock_fyers_client._fyers.history.return_value = {
            "s": "ok",
            "candles": SAMPLE_CANDLES_RAW,
        }
        # Skip candles from the first timestamp
        target_ts = datetime.fromtimestamp(1707369000, tz=IST)

        def exists_fn(symbol: str, tf: str, ts: datetime) -> bool:
            return ts == target_ts

        result = collector.collect_symbol(
            symbol="NSE:NIFTY50-INDEX",
            timeframe="D",
            start_date=date(2024, 2, 1),
            end_date=date(2024, 2, 8),
            exists_fn=exists_fn,
        )
        # 1 skipped, 2 collected
        assert len(result.candles) == 2
        assert result.progress.skipped_candles == 1

    def test_collect_handles_api_error_gracefully(
        self, collector: OHLCCollector, mock_fyers_client: FyersClient
    ) -> None:
        mock_fyers_client._fyers.history.return_value = {
            "s": "error",
            "code": -300,
            "message": "Invalid request",
        }
        result = collector.collect_symbol(
            symbol="NSE:NIFTY50-INDEX",
            timeframe="D",
            start_date=date(2024, 2, 1),
            end_date=date(2024, 2, 8),
        )
        # Should not raise — errors captured in progress
        assert result.success is False
        assert len(result.progress.errors) > 0

    def test_collect_multiple_timeframes(
        self, collector: OHLCCollector, mock_fyers_client: FyersClient
    ) -> None:
        mock_fyers_client._fyers.history.return_value = {
            "s": "ok",
            "candles": SAMPLE_CANDLES_RAW,
        }
        results = collector.collect(
            timeframes=["D", "W"],
            start_date=date(2024, 2, 1),
            end_date=date(2024, 2, 8),
        )
        # 1 symbol × 2 timeframes = 2 results
        assert len(results) == 2
        assert all(r.success for r in results)

    def test_progress_callback_called(
        self, collector: OHLCCollector, mock_fyers_client: FyersClient
    ) -> None:
        mock_fyers_client._fyers.history.return_value = {
            "s": "ok",
            "candles": SAMPLE_CANDLES_RAW,
        }
        progress_calls: list[CollectionProgress] = []
        collector._on_progress = lambda p: progress_calls.append(p)

        collector.collect_symbol(
            symbol="NSE:NIFTY50-INDEX",
            timeframe="D",
            start_date=date(2024, 2, 1),
            end_date=date(2024, 2, 8),
        )
        assert len(progress_calls) > 0
        assert progress_calls[-1].progress_pct == 100.0


# =========================================================================
# Data Quality Tests
# =========================================================================


class TestDataQuality:
    def test_check_gaps_no_gaps(self) -> None:
        base = datetime(2024, 2, 8, 9, 15, tzinfo=IST)
        candles = [
            Candle("S", "5", base + timedelta(minutes=5 * i), 100, 101, 99, 100, 1000)
            for i in range(5)
        ]
        gaps = OHLCCollector.check_data_gaps(candles, expected_interval_minutes=5)
        assert len(gaps) == 0

    def test_check_gaps_with_gap(self) -> None:
        base = datetime(2024, 2, 8, 9, 15, tzinfo=IST)
        candles = [
            Candle("S", "5", base, 100, 101, 99, 100, 1000),
            Candle("S", "5", base + timedelta(minutes=5), 100, 101, 99, 100, 1000),
            # Gap: missing 10, 15, 20 min candles
            Candle("S", "5", base + timedelta(minutes=25), 100, 101, 99, 100, 1000),
        ]
        gaps = OHLCCollector.check_data_gaps(candles, expected_interval_minutes=5)
        assert len(gaps) == 1
        assert gaps[0][0] == base + timedelta(minutes=5)
        assert gaps[0][1] == base + timedelta(minutes=25)

    def test_check_gaps_inferred_interval(self) -> None:
        base = datetime(2024, 2, 8, 9, 15, tzinfo=IST)
        candles = [
            Candle("S", "15", base + timedelta(minutes=15 * i), 100, 101, 99, 100, 1000)
            for i in range(3)
        ]
        # No gap — should infer 15-min interval
        gaps = OHLCCollector.check_data_gaps(candles)
        assert len(gaps) == 0

    def test_check_gaps_single_candle(self) -> None:
        candle = Candle("S", "D", datetime(2024, 2, 8, tzinfo=IST), 100, 101, 99, 100, 1000)
        gaps = OHLCCollector.check_data_gaps([candle])
        assert len(gaps) == 0


class TestCollectionProgress:
    def test_progress_pct_zero(self) -> None:
        p = CollectionProgress(symbol="S", timeframe="D")
        assert p.progress_pct == 0.0

    def test_progress_pct_partial(self) -> None:
        p = CollectionProgress(symbol="S", timeframe="D", total_chunks=4, completed_chunks=2)
        assert p.progress_pct == 50.0

    def test_progress_pct_complete(self) -> None:
        p = CollectionProgress(symbol="S", timeframe="D", total_chunks=4, completed_chunks=4)
        assert p.progress_pct == 100.0
