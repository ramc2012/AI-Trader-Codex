"""Tests for trend indicators: ADX, Supertrend, Ichimoku Cloud, Parabolic SAR."""

import numpy as np
import pandas as pd
import pytest

from src.analysis.indicators.trend import (
    ADX,
    IchimokuCloud,
    ParabolicSAR,
    Supertrend,
)


@pytest.fixture
def ohlcv_df() -> pd.DataFrame:
    """Sample OHLCV DataFrame with a trending pattern for testing.

    Creates ~60 bars of data with an uptrend followed by a downtrend,
    providing enough data for all indicator calculations.
    """
    np.random.seed(42)
    n = 60
    # Base price: uptrend for first 35 bars, downtrend for last 25
    base = np.concatenate([
        np.linspace(100, 130, 35),
        np.linspace(130, 110, 25),
    ])
    noise = np.random.normal(0, 0.5, n)
    close = base + noise
    high = close + np.abs(np.random.normal(1.0, 0.5, n))
    low = close - np.abs(np.random.normal(1.0, 0.5, n))
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
def flat_ohlcv_df() -> pd.DataFrame:
    """OHLCV DataFrame with flat prices (no trend)."""
    n = 40
    close = np.full(n, 100.0)
    return pd.DataFrame({
        "open": close,
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "volume": np.full(n, 5000.0),
    })


@pytest.fixture
def short_ohlcv_df() -> pd.DataFrame:
    """OHLCV DataFrame with very few bars (insufficient data)."""
    return pd.DataFrame({
        "open": [100.0, 101.0, 102.0],
        "high": [101.0, 102.0, 103.0],
        "low": [99.0, 100.0, 101.0],
        "close": [100.5, 101.5, 102.5],
        "volume": [5000.0, 6000.0, 7000.0],
    })


@pytest.fixture
def strong_uptrend_df() -> pd.DataFrame:
    """OHLCV DataFrame with a strong, clean uptrend."""
    n = 50
    close = np.linspace(100, 200, n)
    return pd.DataFrame({
        "open": close - 0.5,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": np.full(n, 5000.0),
    })


# =========================================================================
# ADX Tests
# =========================================================================


class TestADX:
    def test_adx_returns_dataframe(self, ohlcv_df: pd.DataFrame) -> None:
        """ADX should return a DataFrame with adx, plus_di, minus_di columns."""
        adx = ADX(period=14)
        result = adx.calculate(ohlcv_df)
        assert isinstance(result, pd.DataFrame)
        assert set(result.columns) == {"adx", "plus_di", "minus_di"}
        assert len(result) == len(ohlcv_df)

    def test_adx_range(self, ohlcv_df: pd.DataFrame) -> None:
        """ADX values should be between 0 and 100."""
        result = ADX(period=14).calculate(ohlcv_df)
        valid = result.dropna()
        assert (valid["adx"] >= 0).all()
        assert (valid["adx"] <= 100).all()
        assert (valid["plus_di"] >= 0).all()
        assert (valid["minus_di"] >= 0).all()

    def test_adx_strong_trend(self, strong_uptrend_df: pd.DataFrame) -> None:
        """ADX should be above 25 for a strong trend."""
        result = ADX(period=14).calculate(strong_uptrend_df)
        # Last value should indicate a strong trend
        valid_adx = result["adx"].dropna()
        assert valid_adx.iloc[-1] > 25

    def test_adx_flat_market(self, flat_ohlcv_df: pd.DataFrame) -> None:
        """ADX should be low for flat/trendless market."""
        # Use a larger flat dataset so ADX has enough data to produce values
        n = 100
        close = np.full(n, 100.0)
        flat_large = pd.DataFrame({
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.full(n, 5000.0),
        })
        result = ADX(period=14).calculate(flat_large)
        valid_adx = result["adx"].dropna()
        if len(valid_adx) > 0:
            # In flat market ADX should be low
            assert valid_adx.iloc[-1] < 30

    def test_adx_insufficient_data(self, short_ohlcv_df: pd.DataFrame) -> None:
        """ADX with insufficient data should return mostly NaN."""
        result = ADX(period=14).calculate(short_ohlcv_df)
        assert len(result) == len(short_ohlcv_df)
        # With only 3 bars and period=14, values should be NaN
        assert result["adx"].isna().all()

    def test_adx_invalid_period(self) -> None:
        """ADX should reject period < 1."""
        with pytest.raises(ValueError, match="must be >= 1"):
            ADX(period=0)

    def test_adx_repr(self) -> None:
        """ADX repr should contain class name and period."""
        r = repr(ADX(period=14))
        assert "ADX" in r
        assert "14" in r


# =========================================================================
# Supertrend Tests
# =========================================================================


class TestSupertrend:
    def test_supertrend_returns_dataframe(self, ohlcv_df: pd.DataFrame) -> None:
        """Supertrend should return DataFrame with supertrend and direction."""
        st = Supertrend(period=10, multiplier=3.0)
        result = st.calculate(ohlcv_df)
        assert isinstance(result, pd.DataFrame)
        assert set(result.columns) == {"supertrend", "direction"}
        assert len(result) == len(ohlcv_df)

    def test_supertrend_direction_values(self, ohlcv_df: pd.DataFrame) -> None:
        """Direction should be either +1 or -1."""
        result = Supertrend(period=10, multiplier=3.0).calculate(ohlcv_df)
        valid_dir = result["direction"].dropna()
        unique_dirs = set(valid_dir.unique())
        assert unique_dirs.issubset({1.0, -1.0})

    def test_supertrend_uptrend(self, strong_uptrend_df: pd.DataFrame) -> None:
        """In a strong uptrend, direction should mostly be +1."""
        result = Supertrend(period=10, multiplier=3.0).calculate(strong_uptrend_df)
        valid = result.dropna(subset=["supertrend"])
        # In a clean uptrend, most directions should be +1
        uptrend_count = (valid["direction"] == 1.0).sum()
        assert uptrend_count > len(valid) * 0.5

    def test_supertrend_below_price_in_uptrend(
        self, strong_uptrend_df: pd.DataFrame
    ) -> None:
        """In uptrend, supertrend should be below close price."""
        result = Supertrend(period=10, multiplier=3.0).calculate(strong_uptrend_df)
        uptrend_mask = result["direction"] == 1.0
        valid = result[uptrend_mask].dropna(subset=["supertrend"])
        if len(valid) > 0:
            close_vals = strong_uptrend_df.loc[valid.index, "close"]
            assert (valid["supertrend"] <= close_vals).all()

    def test_supertrend_insufficient_data(
        self, short_ohlcv_df: pd.DataFrame
    ) -> None:
        """With insufficient data, supertrend should have NaN values."""
        result = Supertrend(period=10, multiplier=3.0).calculate(short_ohlcv_df)
        assert len(result) == len(short_ohlcv_df)
        # With only 3 bars and period 10, supertrend values are NaN
        assert result["supertrend"].isna().all()

    def test_supertrend_invalid_period(self) -> None:
        """Supertrend should reject period < 1."""
        with pytest.raises(ValueError, match="must be >= 1"):
            Supertrend(period=0)

    def test_supertrend_invalid_multiplier(self) -> None:
        """Supertrend should reject multiplier <= 0."""
        with pytest.raises(ValueError, match="must be > 0"):
            Supertrend(multiplier=-1.0)

    def test_supertrend_repr(self) -> None:
        """Supertrend repr should contain class name and parameters."""
        r = repr(Supertrend(period=10, multiplier=3.0))
        assert "Supertrend" in r
        assert "10" in r
        assert "3.0" in r


# =========================================================================
# Ichimoku Cloud Tests
# =========================================================================


class TestIchimokuCloud:
    def test_ichimoku_returns_dataframe(self, ohlcv_df: pd.DataFrame) -> None:
        """Ichimoku should return DataFrame with all five components."""
        ichimoku = IchimokuCloud()
        result = ichimoku.calculate(ohlcv_df)
        assert isinstance(result, pd.DataFrame)
        expected_cols = {
            "tenkan_sen", "kijun_sen",
            "senkou_span_a", "senkou_span_b", "chikou_span",
        }
        assert set(result.columns) == expected_cols
        assert len(result) == len(ohlcv_df)

    def test_tenkan_shorter_than_kijun(self, ohlcv_df: pd.DataFrame) -> None:
        """Tenkan-sen should have fewer NaN values than Kijun-sen (shorter period)."""
        result = IchimokuCloud(tenkan_period=9, kijun_period=26).calculate(ohlcv_df)
        tenkan_nans = result["tenkan_sen"].isna().sum()
        kijun_nans = result["kijun_sen"].isna().sum()
        assert tenkan_nans <= kijun_nans

    def test_tenkan_is_midpoint(self, ohlcv_df: pd.DataFrame) -> None:
        """Tenkan-sen should equal (highest high + lowest low) / 2 over period."""
        period = 9
        result = IchimokuCloud(tenkan_period=period).calculate(ohlcv_df)
        # Manually compute at a specific index
        idx = period + 5  # well past the warm-up
        expected_high = ohlcv_df["high"].iloc[idx - period + 1: idx + 1].max()
        expected_low = ohlcv_df["low"].iloc[idx - period + 1: idx + 1].min()
        expected_tenkan = (expected_high + expected_low) / 2.0
        assert abs(result["tenkan_sen"].iloc[idx] - expected_tenkan) < 0.001

    def test_chikou_is_lagging_close(self, ohlcv_df: pd.DataFrame) -> None:
        """Chikou Span should equal close shifted back by kijun_period."""
        kijun_period = 26
        result = IchimokuCloud(kijun_period=kijun_period).calculate(ohlcv_df)
        # Check a value that is not NaN
        check_idx = 10
        expected = ohlcv_df["close"].iloc[check_idx]
        chikou_idx = check_idx + kijun_period
        if chikou_idx < len(ohlcv_df):
            # chikou at check_idx equals close at check_idx + kijun_period? No.
            # chikou_span = close.shift(-kijun_period), so
            # chikou at index i = close at index i + kijun_period
            pass
        # Simpler check: at index 0, chikou_span should equal close at index kijun_period
        if kijun_period < len(ohlcv_df):
            assert result["chikou_span"].iloc[0] == ohlcv_df["close"].iloc[kijun_period]

    def test_ichimoku_insufficient_data(
        self, short_ohlcv_df: pd.DataFrame
    ) -> None:
        """With insufficient data, most Ichimoku components should be NaN."""
        result = IchimokuCloud().calculate(short_ohlcv_df)
        assert len(result) == len(short_ohlcv_df)
        # With only 3 bars and default periods (9, 26, 52), most values are NaN
        assert result["kijun_sen"].isna().all()
        assert result["senkou_span_b"].isna().all()

    def test_ichimoku_invalid_period(self) -> None:
        """Ichimoku should reject invalid periods."""
        with pytest.raises(ValueError, match="tenkan_period must be >= 1"):
            IchimokuCloud(tenkan_period=0)
        with pytest.raises(ValueError, match="kijun_period must be >= 1"):
            IchimokuCloud(kijun_period=0)
        with pytest.raises(ValueError, match="senkou_span_b_period must be >= 1"):
            IchimokuCloud(senkou_span_b_period=0)

    def test_ichimoku_repr(self) -> None:
        """Ichimoku repr should contain class name and periods."""
        r = repr(IchimokuCloud(tenkan_period=9, kijun_period=26, senkou_span_b_period=52))
        assert "IchimokuCloud" in r
        assert "9" in r
        assert "26" in r
        assert "52" in r


# =========================================================================
# Parabolic SAR Tests
# =========================================================================


class TestParabolicSAR:
    def test_psar_returns_series(self, ohlcv_df: pd.DataFrame) -> None:
        """Parabolic SAR should return a Series of the same length."""
        psar = ParabolicSAR()
        result = psar.calculate(ohlcv_df)
        assert isinstance(result, pd.Series)
        assert len(result) == len(ohlcv_df)

    def test_psar_no_nan_after_start(self, ohlcv_df: pd.DataFrame) -> None:
        """SAR should have valid values from bar 0 onward."""
        result = ParabolicSAR().calculate(ohlcv_df)
        # SAR is computed from bar 0
        assert not result.iloc[0:].isna().any()

    def test_psar_below_price_in_uptrend(
        self, strong_uptrend_df: pd.DataFrame
    ) -> None:
        """In a strong uptrend, SAR should mostly be below the low."""
        result = ParabolicSAR().calculate(strong_uptrend_df)
        # After initial bars, SAR should be below price in uptrend
        # Check last 20 bars where trend is established
        last_20_sar = result.iloc[-20:]
        last_20_low = strong_uptrend_df["low"].iloc[-20:]
        below_count = (last_20_sar <= last_20_low).sum()
        assert below_count > 10  # majority should be below

    def test_psar_with_short_data(self) -> None:
        """SAR should handle very short data gracefully."""
        df = pd.DataFrame({
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [5000.0],
        })
        result = ParabolicSAR().calculate(df)
        assert len(result) == 1
        # With only 1 bar, result should be NaN
        assert result.isna().all()

    def test_psar_two_bars(self) -> None:
        """SAR should work with exactly 2 bars."""
        df = pd.DataFrame({
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.5, 101.5],
            "volume": [5000.0, 6000.0],
        })
        result = ParabolicSAR().calculate(df)
        assert len(result) == 2
        assert not result.isna().all()

    def test_psar_invalid_params(self) -> None:
        """SAR should reject invalid acceleration factor parameters."""
        with pytest.raises(ValueError, match="af_start must be > 0"):
            ParabolicSAR(af_start=0)
        with pytest.raises(ValueError, match="af_increment must be > 0"):
            ParabolicSAR(af_increment=0)
        with pytest.raises(ValueError, match="af_max must be > 0"):
            ParabolicSAR(af_max=0)
        with pytest.raises(ValueError, match="af_start.*must be <= af_max"):
            ParabolicSAR(af_start=0.5, af_max=0.2)

    def test_psar_repr(self) -> None:
        """SAR repr should contain class name and parameters."""
        r = repr(ParabolicSAR(af_start=0.02, af_increment=0.02, af_max=0.2))
        assert "ParabolicSAR" in r
        assert "0.02" in r
        assert "0.2" in r
