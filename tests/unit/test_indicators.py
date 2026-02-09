"""Tests for technical indicators with known reference values."""

import numpy as np
import pandas as pd
import pytest

from src.analysis.indicators import (
    ATR,
    EMA,
    MACD,
    RSI,
    SMA,
    WMA,
    BollingerBands,
)


@pytest.fixture
def prices() -> pd.Series:
    """Sample close price series for testing."""
    return pd.Series(
        [44.0, 44.34, 44.09, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
         45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 46.21,
         45.64, 46.21, 46.25, 45.71, 46.45, 45.78, 45.35, 44.03, 44.18, 44.22],
        dtype=float,
    )


@pytest.fixture
def ohlc_df() -> pd.DataFrame:
    """Sample OHLC DataFrame for ATR testing."""
    return pd.DataFrame(
        {
            "high": [48.70, 48.72, 48.90, 48.87, 48.82, 49.05, 49.20, 49.35,
                     49.92, 50.19, 50.12, 49.66, 49.88, 50.19, 50.36, 50.57,
                     50.65, 50.43, 49.63, 50.33],
            "low": [47.79, 48.14, 48.39, 48.37, 48.24, 48.64, 48.94, 48.86,
                    49.50, 49.87, 49.20, 48.90, 49.43, 49.73, 49.26, 50.09,
                    50.30, 49.21, 48.98, 49.61],
            "close": [48.16, 48.61, 48.75, 48.63, 48.74, 49.03, 49.07, 49.32,
                      49.91, 50.13, 49.53, 49.50, 49.75, 50.03, 49.99, 50.31,
                      50.52, 50.41, 49.34, 49.69],
        }
    )


# =========================================================================
# SMA Tests
# =========================================================================


class TestSMA:
    def test_sma_basic(self, prices: pd.Series) -> None:
        sma = SMA(period=10)
        result = sma.calculate(prices)
        assert len(result) == len(prices)
        # First 9 values should be NaN
        assert result.iloc[:9].isna().all()
        # 10th value should be mean of first 10
        expected = prices.iloc[:10].mean()
        assert abs(result.iloc[9] - expected) < 0.001

    def test_sma_period_1(self, prices: pd.Series) -> None:
        sma = SMA(period=1)
        result = sma.calculate(prices)
        # SMA(1) should equal the original series
        np.testing.assert_array_almost_equal(result.values, prices.values)

    def test_sma_invalid_period(self) -> None:
        with pytest.raises(ValueError, match="must be >= 1"):
            SMA(period=0)

    def test_sma_repr(self) -> None:
        assert "SMA" in repr(SMA(period=20))
        assert "20" in repr(SMA(period=20))


# =========================================================================
# EMA Tests
# =========================================================================


class TestEMA:
    def test_ema_basic(self, prices: pd.Series) -> None:
        ema = EMA(period=10)
        result = ema.calculate(prices)
        assert len(result) == len(prices)
        # EMA should not have NaN (ewm gives values from start)
        assert not result.isna().any()

    def test_ema_more_responsive_than_sma(self, prices: pd.Series) -> None:
        ema = EMA(period=10).calculate(prices)
        sma = SMA(period=10).calculate(prices)
        # After the initial period, EMA should track more closely to recent prices
        # Check the last value — EMA reacts faster to recent moves
        last_price = prices.iloc[-1]
        ema_diff = abs(ema.iloc[-1] - last_price)
        sma_diff = abs(sma.iloc[-1] - last_price)
        # In a downtrend (prices drop at end), EMA should be closer to current price
        assert ema_diff <= sma_diff + 1.0  # some tolerance

    def test_ema_invalid_period(self) -> None:
        with pytest.raises(ValueError, match="must be >= 1"):
            EMA(period=0)


# =========================================================================
# WMA Tests
# =========================================================================


class TestWMA:
    def test_wma_basic(self) -> None:
        # Simple known case: [1, 2, 3, 4, 5] with period=3
        # WMA at index 2 = (1*1 + 2*2 + 3*3) / (1+2+3) = 14/6 ≈ 2.333
        data = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        wma = WMA(period=3)
        result = wma.calculate(data)
        assert result.iloc[:2].isna().all()
        assert abs(result.iloc[2] - 14.0 / 6.0) < 0.001

    def test_wma_invalid_period(self) -> None:
        with pytest.raises(ValueError, match="must be >= 1"):
            WMA(period=0)


# =========================================================================
# RSI Tests
# =========================================================================


class TestRSI:
    def test_rsi_range(self, prices: pd.Series) -> None:
        rsi = RSI(period=14)
        result = rsi.calculate(prices)
        valid = result.dropna()
        assert (valid >= 0).all()
        assert (valid <= 100).all()

    def test_rsi_monotonic_up(self) -> None:
        # Strictly increasing prices → RSI should be near 100
        data = pd.Series(range(1, 50), dtype=float)
        rsi = RSI(period=14)
        result = rsi.calculate(data)
        assert result.iloc[-1] > 90

    def test_rsi_monotonic_down(self) -> None:
        # Strictly decreasing prices → RSI should be near 0
        data = pd.Series(range(50, 1, -1), dtype=float)
        rsi = RSI(period=14)
        result = rsi.calculate(data)
        assert result.iloc[-1] < 10

    def test_rsi_invalid_period(self) -> None:
        with pytest.raises(ValueError, match="must be >= 1"):
            RSI(period=0)


# =========================================================================
# MACD Tests
# =========================================================================


class TestMACD:
    def test_macd_returns_dataframe(self, prices: pd.Series) -> None:
        macd = MACD()
        result = macd.calculate(prices)
        assert isinstance(result, pd.DataFrame)
        assert set(result.columns) == {"macd", "signal", "histogram"}
        assert len(result) == len(prices)

    def test_macd_histogram_equals_diff(self, prices: pd.Series) -> None:
        result = MACD().calculate(prices)
        np.testing.assert_array_almost_equal(
            result["histogram"].values,
            (result["macd"] - result["signal"]).values,
        )

    def test_macd_invalid_periods(self) -> None:
        with pytest.raises(ValueError, match="fast_period.*must be < slow_period"):
            MACD(fast_period=26, slow_period=12)

    def test_macd_repr(self) -> None:
        r = repr(MACD(12, 26, 9))
        assert "12" in r
        assert "26" in r
        assert "9" in r


# =========================================================================
# Bollinger Bands Tests
# =========================================================================


class TestBollingerBands:
    def test_bb_returns_dataframe(self, prices: pd.Series) -> None:
        bb = BollingerBands(period=20)
        result = bb.calculate(prices)
        assert isinstance(result, pd.DataFrame)
        assert set(result.columns) == {"upper", "middle", "lower", "bandwidth"}

    def test_upper_above_lower(self, prices: pd.Series) -> None:
        result = BollingerBands(period=10).calculate(prices)
        valid = result.dropna()
        assert (valid["upper"] >= valid["lower"]).all()

    def test_middle_is_sma(self, prices: pd.Series) -> None:
        period = 10
        bb_result = BollingerBands(period=period).calculate(prices)
        sma_result = SMA(period=period).calculate(prices)
        np.testing.assert_array_almost_equal(
            bb_result["middle"].dropna().values,
            sma_result.dropna().values,
        )

    def test_bb_invalid_period(self) -> None:
        with pytest.raises(ValueError, match="Period must be >= 1"):
            BollingerBands(period=0)

    def test_bb_invalid_std(self) -> None:
        with pytest.raises(ValueError, match="std_dev must be > 0"):
            BollingerBands(std_dev=-1)


# =========================================================================
# ATR Tests
# =========================================================================


class TestATR:
    def test_atr_positive(self, ohlc_df: pd.DataFrame) -> None:
        atr = ATR(period=14)
        result = atr.calculate(
            data=ohlc_df["close"],
            high=ohlc_df["high"],
            low=ohlc_df["low"],
        )
        valid = result.dropna()
        assert (valid > 0).all()

    def test_atr_length(self, ohlc_df: pd.DataFrame) -> None:
        atr = ATR(period=14)
        result = atr.calculate(
            data=ohlc_df["close"],
            high=ohlc_df["high"],
            low=ohlc_df["low"],
        )
        assert len(result) == len(ohlc_df)

    def test_atr_requires_high_low(self) -> None:
        atr = ATR(period=14)
        with pytest.raises(ValueError, match="requires high and low"):
            atr.calculate(pd.Series([1.0, 2.0]))

    def test_atr_invalid_period(self) -> None:
        with pytest.raises(ValueError, match="must be >= 1"):
            ATR(period=0)
