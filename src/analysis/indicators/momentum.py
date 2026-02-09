"""Momentum indicators: RSI, MACD."""

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
