"""Momentum indicators: RSI, MACD, stochastic, CCI, Williams %R, ROC."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.analysis.indicators.base import Indicator


class RSI(Indicator):
    """Relative Strength Index.

    Measures the speed and magnitude of recent price changes
    to evaluate overbought or oversold conditions.

    Args:
        period: Lookback period (default 14).
    """

    name = "RSI"

    def __init__(self, period: int = 14) -> None:
        if period < 1:
            raise ValueError(f"RSI period must be >= 1, got {period}")
        self.period = period

    def calculate(self, data: pd.Series) -> pd.Series:
        """Compute RSI using the Wilder smoothing method.

        Args:
            data: Price series (typically close).

        Returns:
            Series with RSI values (0-100 scale).
        """
        delta = data.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)

        # Wilder's smoothed averages (EMA with alpha = 1/period)
        avg_gain = gain.ewm(alpha=1.0 / self.period, min_periods=self.period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / self.period, min_periods=self.period, adjust=False).mean()

        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))

        return rsi

    def __repr__(self) -> str:
        return f"<RSI(period={self.period})>"


class MACD(Indicator):
    """Moving Average Convergence Divergence.

    Consists of:
    - MACD line: fast EMA - slow EMA
    - Signal line: EMA of MACD line
    - Histogram: MACD - Signal

    Args:
        fast_period: Fast EMA period (default 12).
        slow_period: Slow EMA period (default 26).
        signal_period: Signal line EMA period (default 9).
    """

    name = "MACD"

    def __init__(
        self,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
    ) -> None:
        if fast_period >= slow_period:
            raise ValueError(
                f"fast_period ({fast_period}) must be < slow_period ({slow_period})"
            )
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period

    def calculate(self, data: pd.Series) -> pd.DataFrame:
        """Compute MACD, Signal, and Histogram.

        Args:
            data: Price series (typically close).

        Returns:
            DataFrame with columns: 'macd', 'signal', 'histogram'.
        """
        fast_ema = data.ewm(span=self.fast_period, adjust=False).mean()
        slow_ema = data.ewm(span=self.slow_period, adjust=False).mean()
        macd_line = fast_ema - slow_ema
        signal_line = macd_line.ewm(span=self.signal_period, adjust=False).mean()
        histogram = macd_line - signal_line

        return pd.DataFrame(
            {
                "macd": macd_line,
                "signal": signal_line,
                "histogram": histogram,
            },
            index=data.index,
        )

    def __repr__(self) -> str:
        return (
            f"<MACD(fast={self.fast_period}, "
            f"slow={self.slow_period}, signal={self.signal_period})>"
        )


class StochasticOscillator(Indicator):
    """Stochastic oscillator (%K/%D)."""

    name = "StochasticOscillator"

    def __init__(self, period: int = 14, smooth_k: int = 3, smooth_d: int = 3) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        if smooth_k < 1 or smooth_d < 1:
            raise ValueError("smooth windows must be >= 1")
        self.period = period
        self.smooth_k = smooth_k
        self.smooth_d = smooth_d

    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        low_min = data["low"].rolling(self.period, min_periods=self.period).min()
        high_max = data["high"].rolling(self.period, min_periods=self.period).max()
        denom = (high_max - low_min).replace(0, np.nan)

        fast_k = 100.0 * (data["close"] - low_min) / denom
        k = fast_k.rolling(self.smooth_k, min_periods=1).mean()
        d = k.rolling(self.smooth_d, min_periods=1).mean()
        return pd.DataFrame({"k": k, "d": d}, index=data.index)


class CCI(Indicator):
    """Commodity Channel Index."""

    name = "CCI"

    def __init__(self, period: int = 20) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self.period = period

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        tp = (data["high"] + data["low"] + data["close"]) / 3.0
        sma = tp.rolling(window=self.period, min_periods=self.period).mean()
        mad = tp.rolling(window=self.period, min_periods=self.period).apply(
            lambda x: np.mean(np.abs(x - np.mean(x))), raw=True
        )
        cci = (tp - sma) / (0.015 * mad.replace(0, np.nan))
        return pd.Series(cci, index=data.index, name="cci")


class WilliamsR(Indicator):
    """Williams %R oscillator."""

    name = "WilliamsR"

    def __init__(self, period: int = 14) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self.period = period

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        highest = data["high"].rolling(self.period, min_periods=self.period).max()
        lowest = data["low"].rolling(self.period, min_periods=self.period).min()
        denom = (highest - lowest).replace(0, np.nan)
        wr = -100.0 * ((highest - data["close"]) / denom)
        return pd.Series(wr, index=data.index, name="williams_r")


class ROC(Indicator):
    """Rate of Change."""

    name = "ROC"

    def __init__(self, period: int = 12) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self.period = period

    def calculate(self, data: pd.Series) -> pd.Series:
        roc = data.pct_change(self.period) * 100.0
        return pd.Series(roc, index=data.index, name=f"roc_{self.period}")


class UltimateOscillator(Indicator):
    """Ultimate oscillator with multi-window buying pressure."""

    name = "UltimateOscillator"

    def __init__(
        self,
        short_period: int = 7,
        medium_period: int = 14,
        long_period: int = 28,
    ) -> None:
        if min(short_period, medium_period, long_period) < 1:
            raise ValueError("all periods must be >= 1")
        self.short_period = short_period
        self.medium_period = medium_period
        self.long_period = long_period

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        close = data["close"]
        low = data["low"]
        high = data["high"]
        prev_close = close.shift(1)

        bp = close - pd.concat([low, prev_close], axis=1).min(axis=1)
        tr = (
            pd.concat(
                [
                    high - low,
                    (high - prev_close).abs(),
                    (low - prev_close).abs(),
                ],
                axis=1,
            )
            .max(axis=1)
            .replace(0, np.nan)
        )

        avg7 = bp.rolling(self.short_period, min_periods=self.short_period).sum() / tr.rolling(
            self.short_period, min_periods=self.short_period
        ).sum()
        avg14 = bp.rolling(
            self.medium_period, min_periods=self.medium_period
        ).sum() / tr.rolling(self.medium_period, min_periods=self.medium_period).sum()
        avg28 = bp.rolling(
            self.long_period, min_periods=self.long_period
        ).sum() / tr.rolling(self.long_period, min_periods=self.long_period).sum()

        uo = 100.0 * ((4.0 * avg7) + (2.0 * avg14) + avg28) / 7.0
        return pd.Series(uo, index=data.index, name="ultimate_oscillator")
