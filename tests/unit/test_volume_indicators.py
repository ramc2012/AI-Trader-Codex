"""Tests for volume indicators: OBV, VWAP, MFI, Accumulation/Distribution."""

import numpy as np
import pandas as pd
import pytest

from src.analysis.indicators.volume import (
    OBV,
    VWAP,
    MFI,
    AccumulationDistribution,
)


@pytest.fixture
def ohlcv_df() -> pd.DataFrame:
    """Sample OHLCV DataFrame with realistic price and volume data."""
    np.random.seed(42)
    n = 40
    base = np.linspace(100, 120, n) + np.random.normal(0, 0.5, n)
    close = base
    high = close + np.abs(np.random.normal(1.0, 0.3, n))
    low = close - np.abs(np.random.normal(1.0, 0.3, n))
    open_ = close + np.random.normal(0, 0.3, n)
    volume = np.random.randint(1000, 10000, n).astype(float)

    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


@pytest.fixture
def monotonic_up_df() -> pd.DataFrame:
    """OHLCV DataFrame with strictly increasing close prices."""
    n = 30
    close = np.linspace(100, 130, n)
    return pd.DataFrame({
        "open": close - 0.5,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": np.full(n, 5000.0),
    })


@pytest.fixture
def monotonic_down_df() -> pd.DataFrame:
    """OHLCV DataFrame with strictly decreasing close prices."""
    n = 30
    close = np.linspace(130, 100, n)
    return pd.DataFrame({
        "open": close + 0.5,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": np.full(n, 5000.0),
    })


@pytest.fixture
def short_ohlcv_df() -> pd.DataFrame:
    """OHLCV DataFrame with very few bars."""
    return pd.DataFrame({
        "open": [100.0, 101.0, 102.0],
        "high": [101.0, 102.0, 103.0],
        "low": [99.0, 100.0, 101.0],
        "close": [100.5, 101.5, 102.5],
        "volume": [5000.0, 6000.0, 7000.0],
    })


@pytest.fixture
def flat_ohlcv_df() -> pd.DataFrame:
    """OHLCV DataFrame with flat prices."""
    n = 30
    close = np.full(n, 100.0)
    return pd.DataFrame({
        "open": close,
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "volume": np.full(n, 5000.0),
    })


# =========================================================================
# OBV Tests
# =========================================================================


class TestOBV:
    def test_obv_returns_series(self, ohlcv_df: pd.DataFrame) -> None:
        """OBV should return a Series of the same length."""
        obv = OBV()
        result = obv.calculate(ohlcv_df)
        assert isinstance(result, pd.Series)
        assert len(result) == len(ohlcv_df)

    def test_obv_no_nan(self, ohlcv_df: pd.DataFrame) -> None:
        """OBV should not contain any NaN values."""
        result = OBV().calculate(ohlcv_df)
        assert not result.isna().any()

    def test_obv_increasing_in_uptrend(self, monotonic_up_df: pd.DataFrame) -> None:
        """OBV should be strictly increasing when price is monotonically rising."""
        result = OBV().calculate(monotonic_up_df)
        # From bar 1 onward, OBV should increase each bar
        diffs = result.diff().iloc[2:]  # skip first two (bar 0 = 0, bar 1 = first add)
        assert (diffs > 0).all()

    def test_obv_decreasing_in_downtrend(
        self, monotonic_down_df: pd.DataFrame
    ) -> None:
        """OBV should be strictly decreasing when price is monotonically falling."""
        result = OBV().calculate(monotonic_down_df)
        diffs = result.diff().iloc[2:]
        assert (diffs < 0).all()

    def test_obv_flat_prices(self, flat_ohlcv_df: pd.DataFrame) -> None:
        """OBV should not change when prices are flat (close == prev close)."""
        result = OBV().calculate(flat_ohlcv_df)
        # All diffs from bar 1 onward should be 0 (no price change)
        diffs = result.diff().iloc[1:]
        assert (diffs == 0).all()

    def test_obv_first_bar_zero(self, ohlcv_df: pd.DataFrame) -> None:
        """First OBV value should be 0 (direction is 0 for first bar)."""
        result = OBV().calculate(ohlcv_df)
        assert result.iloc[0] == 0.0

    def test_obv_repr(self) -> None:
        """OBV repr should contain class name."""
        assert "OBV" in repr(OBV())


# =========================================================================
# VWAP Tests
# =========================================================================


class TestVWAP:
    def test_vwap_returns_series(self, ohlcv_df: pd.DataFrame) -> None:
        """VWAP should return a Series of the same length."""
        vwap = VWAP()
        result = vwap.calculate(ohlcv_df)
        assert isinstance(result, pd.Series)
        assert len(result) == len(ohlcv_df)

    def test_vwap_no_nan(self, ohlcv_df: pd.DataFrame) -> None:
        """VWAP should not have NaN values when volume is positive."""
        result = VWAP().calculate(ohlcv_df)
        assert not result.isna().any()

    def test_vwap_first_bar_is_typical_price(
        self, ohlcv_df: pd.DataFrame
    ) -> None:
        """First VWAP value should equal the typical price of the first bar."""
        result = VWAP().calculate(ohlcv_df)
        expected = (
            ohlcv_df["high"].iloc[0]
            + ohlcv_df["low"].iloc[0]
            + ohlcv_df["close"].iloc[0]
        ) / 3.0
        assert abs(result.iloc[0] - expected) < 0.001

    def test_vwap_between_high_and_low(self, ohlcv_df: pd.DataFrame) -> None:
        """VWAP at bar 0 should be between low and high."""
        result = VWAP().calculate(ohlcv_df)
        # First bar VWAP is typical price, must be between low and high
        assert result.iloc[0] >= ohlcv_df["low"].iloc[0]
        assert result.iloc[0] <= ohlcv_df["high"].iloc[0]

    def test_vwap_equal_volume(self) -> None:
        """With equal volume, VWAP should be the running mean of typical prices."""
        df = pd.DataFrame({
            "open": [100.0, 102.0, 104.0],
            "high": [101.0, 103.0, 105.0],
            "low": [99.0, 101.0, 103.0],
            "close": [100.0, 102.0, 104.0],
            "volume": [1000.0, 1000.0, 1000.0],
        })
        result = VWAP().calculate(df)
        tp = (df["high"] + df["low"] + df["close"]) / 3.0
        expected_last = tp.mean()  # equal volume -> simple mean
        assert abs(result.iloc[-1] - expected_last) < 0.001

    def test_vwap_repr(self) -> None:
        """VWAP repr should contain class name."""
        assert "VWAP" in repr(VWAP())


# =========================================================================
# MFI Tests
# =========================================================================


class TestMFI:
    def test_mfi_returns_series(self, ohlcv_df: pd.DataFrame) -> None:
        """MFI should return a Series of the same length."""
        mfi = MFI(period=14)
        result = mfi.calculate(ohlcv_df)
        assert isinstance(result, pd.Series)
        assert len(result) == len(ohlcv_df)

    def test_mfi_range(self, ohlcv_df: pd.DataFrame) -> None:
        """MFI values should be between 0 and 100."""
        result = MFI(period=14).calculate(ohlcv_df)
        valid = result.dropna()
        assert (valid >= 0).all()
        assert (valid <= 100).all()

    def test_mfi_high_in_uptrend(self) -> None:
        """MFI should be high (near 100) in a strong uptrend."""
        # Use larger dataset with slight noise to avoid all-positive typical price diffs
        np.random.seed(42)
        n = 60
        base = np.linspace(100, 160, n)
        noise = np.random.normal(0, 0.3, n)
        close = base + noise
        df = pd.DataFrame({
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(n, 5000.0),
        })
        result = MFI(period=14).calculate(df)
        valid = result.dropna()
        assert len(valid) > 0
        # In strong uptrend, MFI should be high
        assert valid.iloc[-1] > 60

    def test_mfi_low_in_downtrend(self, monotonic_down_df: pd.DataFrame) -> None:
        """MFI should be low (near 0) in a strong downtrend."""
        result = MFI(period=14).calculate(monotonic_down_df)
        valid = result.dropna()
        # In strong downtrend, MFI should be low
        assert valid.iloc[-1] < 30

    def test_mfi_insufficient_data(self, short_ohlcv_df: pd.DataFrame) -> None:
        """MFI with insufficient data should return NaN."""
        result = MFI(period=14).calculate(short_ohlcv_df)
        assert len(result) == len(short_ohlcv_df)
        assert result.isna().all()

    def test_mfi_invalid_period(self) -> None:
        """MFI should reject period < 1."""
        with pytest.raises(ValueError, match="must be >= 1"):
            MFI(period=0)

    def test_mfi_repr(self) -> None:
        """MFI repr should contain class name and period."""
        r = repr(MFI(period=14))
        assert "MFI" in r
        assert "14" in r


# =========================================================================
# Accumulation/Distribution Tests
# =========================================================================


class TestAccumulationDistribution:
    def test_ad_returns_series(self, ohlcv_df: pd.DataFrame) -> None:
        """A/D should return a Series of the same length."""
        ad = AccumulationDistribution()
        result = ad.calculate(ohlcv_df)
        assert isinstance(result, pd.Series)
        assert len(result) == len(ohlcv_df)

    def test_ad_no_nan(self, ohlcv_df: pd.DataFrame) -> None:
        """A/D line should not contain NaN values."""
        result = AccumulationDistribution().calculate(ohlcv_df)
        assert not result.isna().any()

    def test_ad_close_at_high(self) -> None:
        """When close equals high, MFM should be +1 and A/D should increase."""
        df = pd.DataFrame({
            "open": [100.0, 101.0, 102.0],
            "high": [102.0, 103.0, 104.0],
            "low": [98.0, 99.0, 100.0],
            "close": [102.0, 103.0, 104.0],  # close == high
            "volume": [1000.0, 1000.0, 1000.0],
        })
        result = AccumulationDistribution().calculate(df)
        # MFM = ((C-L) - (H-C)) / (H-L) = ((102-98) - 0) / 4 = 1.0
        # Each bar adds +1000 (mfm=1 * volume=1000)
        assert result.iloc[0] == 1000.0
        assert result.iloc[1] == 2000.0
        assert result.iloc[2] == 3000.0

    def test_ad_close_at_low(self) -> None:
        """When close equals low, MFM should be -1 and A/D should decrease."""
        df = pd.DataFrame({
            "open": [100.0, 99.0, 98.0],
            "high": [102.0, 101.0, 100.0],
            "low": [98.0, 97.0, 96.0],
            "close": [98.0, 97.0, 96.0],  # close == low
            "volume": [1000.0, 1000.0, 1000.0],
        })
        result = AccumulationDistribution().calculate(df)
        # MFM = ((C-L) - (H-C)) / (H-L) = (0 - 4) / 4 = -1.0
        assert result.iloc[0] == -1000.0
        assert result.iloc[1] == -2000.0
        assert result.iloc[2] == -3000.0

    def test_ad_close_at_midpoint(self) -> None:
        """When close is at the midpoint, MFM should be 0."""
        df = pd.DataFrame({
            "open": [100.0],
            "high": [102.0],
            "low": [98.0],
            "close": [100.0],  # midpoint of 98-102
            "volume": [1000.0],
        })
        result = AccumulationDistribution().calculate(df)
        # MFM = ((100-98) - (102-100)) / (102-98) = (2-2)/4 = 0
        assert result.iloc[0] == 0.0

    def test_ad_zero_range(self) -> None:
        """When high == low (zero range), MFM should default to 0."""
        df = pd.DataFrame({
            "open": [100.0],
            "high": [100.0],
            "low": [100.0],
            "close": [100.0],
            "volume": [1000.0],
        })
        result = AccumulationDistribution().calculate(df)
        assert result.iloc[0] == 0.0

    def test_ad_repr(self) -> None:
        """A/D repr should contain class name."""
        assert "AccumulationDistribution" in repr(AccumulationDistribution())
