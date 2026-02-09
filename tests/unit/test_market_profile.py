"""Tests for the Market Profile engine."""

from datetime import datetime

import pandas as pd
import pytest

from src.analysis.market_profile import (
    MarketProfileEngine,
    MarketProfileResult,
    ProfileShape,
)
from src.config.market_hours import IST


@pytest.fixture
def sample_candles() -> pd.DataFrame:
    """Simulated intraday 30-min candles for one session."""
    base_time = datetime(2024, 2, 8, 9, 15, tzinfo=IST)
    candles = []
    # Simulate a normal day with some range
    prices = [
        (22000, 22050, 21980, 22030, 100000),
        (22030, 22080, 22010, 22060, 120000),
        (22060, 22100, 22040, 22070, 110000),
        (22070, 22090, 22020, 22040, 95000),
        (22040, 22060, 22000, 22020, 80000),
        (22020, 22070, 22010, 22050, 105000),
        (22050, 22080, 22030, 22060, 90000),
        (22060, 22100, 22050, 22090, 115000),
        (22090, 22110, 22060, 22080, 100000),
        (22080, 22100, 22050, 22070, 85000),
        (22070, 22090, 22040, 22060, 75000),
        (22060, 22080, 22030, 22050, 70000),
    ]
    for i, (o, h, l, c, v) in enumerate(prices):
        candles.append({
            "timestamp": base_time.replace(minute=15 + i * 30) if i == 0
            else base_time.replace(hour=9 + (15 + i * 30) // 60, minute=(15 + i * 30) % 60),
            "open": o, "high": h, "low": l, "close": c, "volume": v,
        })
    return pd.DataFrame(candles)


class TestMarketProfileEngine:
    def test_build_profile_basic(self, sample_candles: pd.DataFrame) -> None:
        engine = MarketProfileEngine(tick_size=10.0)
        result = engine.build_profile(sample_candles)

        assert result.poc is not None
        assert result.vah is not None
        assert result.val is not None
        assert result.session_high is not None
        assert result.session_low is not None
        assert result.vah >= result.val
        assert result.session_high >= result.poc >= result.session_low

    def test_initial_balance(self, sample_candles: pd.DataFrame) -> None:
        engine = MarketProfileEngine(tick_size=10.0, ib_periods=2)
        result = engine.build_profile(sample_candles)

        assert result.ib_high is not None
        assert result.ib_low is not None
        assert result.ib_high >= result.ib_low
        assert result.ib_range is not None
        assert result.ib_range > 0

    def test_empty_candles(self) -> None:
        engine = MarketProfileEngine()
        result = engine.build_profile(pd.DataFrame())
        assert result.poc is None
        assert result.tpo_rows == []

    def test_value_area_contains_poc(self, sample_candles: pd.DataFrame) -> None:
        engine = MarketProfileEngine(tick_size=10.0)
        result = engine.build_profile(sample_candles)
        assert result.val <= result.poc <= result.vah

    def test_tpo_rows_populated(self, sample_candles: pd.DataFrame) -> None:
        engine = MarketProfileEngine(tick_size=10.0)
        result = engine.build_profile(sample_candles)
        assert len(result.tpo_rows) > 0
        poc_rows = [r for r in result.tpo_rows if r.is_poc]
        assert len(poc_rows) == 1

    def test_to_dict(self, sample_candles: pd.DataFrame) -> None:
        engine = MarketProfileEngine(tick_size=10.0)
        result = engine.build_profile(sample_candles)
        d = result.to_dict()
        assert "poc" in d
        assert "vah" in d
        assert "val" in d
        assert "profile_shape" in d

    def test_ib_extension(self, sample_candles: pd.DataFrame) -> None:
        engine = MarketProfileEngine(tick_size=10.0)
        result = engine.build_profile(sample_candles)
        assert result.ib_extension is not None
        assert result.ib_extension >= 1.0  # session range >= IB range

    def test_different_tick_sizes(self, sample_candles: pd.DataFrame) -> None:
        fine = MarketProfileEngine(tick_size=5.0).build_profile(sample_candles)
        coarse = MarketProfileEngine(tick_size=50.0).build_profile(sample_candles)
        # Finer tick size → more TPO rows
        assert len(fine.tpo_rows) >= len(coarse.tpo_rows)

    def test_profile_shape_classified(self, sample_candles: pd.DataFrame) -> None:
        engine = MarketProfileEngine(tick_size=10.0)
        result = engine.build_profile(sample_candles)
        assert result.profile_shape in list(ProfileShape)
