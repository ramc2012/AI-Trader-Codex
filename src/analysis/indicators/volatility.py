"""Volatility indicators: Bollinger Bands, ATR."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.analysis.indicators.base import Indicator


class BollingerBands(Indicator):
    """Bollinger Bands — volatility bands around a moving average.

    Args:
        period: SMA period for the middle band (default 20).
        std_dev: Number of standard deviations (default 2.0).
    """

    name = "BollingerBands"

    def __init__(self, period: int = 20, std_dev: float = 2.0) -> None:
        if period < 1:
            raise ValueError(f"Period must be >= 1, got {period}")
        if std_dev <= 0:
            raise ValueError(f"std_dev must be > 0, got {std_dev}")
        self.period = period
        self.std_dev = std_dev

    def calculate(self, data: pd.Series) -> pd.DataFrame:
        """Compute upper, middle, and lower Bollinger Bands.

        Args:
            data: Price series (typically close).

        Returns:
            DataFrame with columns: 'upper', 'middle', 'lower', 'bandwidth'.
        """
        middle = data.rolling(window=self.period, min_periods=self.period).mean()
        std = data.rolling(window=self.period, min_periods=self.period).std()

        upper = middle + (self.std_dev * std)
        lower = middle - (self.std_dev * std)
        bandwidth = (upper - lower) / middle

        return pd.DataFrame(
            {
                "upper": upper,
                "middle": middle,
                "lower": lower,
                "bandwidth": bandwidth,
            },
            index=data.index,
        )

    def __repr__(self) -> str:
        return f"<BollingerBands(period={self.period}, std={self.std_dev})>"


class ATR(Indicator):
    """Average True Range — volatility measure.

    True Range = max(H-L, |H-Cprev|, |L-Cprev|).
    ATR is a smoothed average of True Range.

    Args:
        period: Smoothing period (default 14).
    """

    name = "ATR"

    def __init__(self, period: int = 14) -> None:
        if period < 1:
            raise ValueError(f"ATR period must be >= 1, got {period}")
        self.period = period

    def calculate(
        self,
        data: pd.Series,
        high: pd.Series | None = None,
        low: pd.Series | None = None,
    ) -> pd.Series:
        """Compute ATR.

        If high/low are not provided, uses `data` as close and returns NaN.
        For proper ATR, pass high, low, and data=close.

        Args:
            data: Close price series.
            high: High price series.
            low: Low price series.

        Returns:
            Series with ATR values.
        """
        if high is None or low is None:
            raise ValueError("ATR requires high and low series in addition to close")

        close_prev = data.shift(1)
        tr1 = high - low
        tr2 = (high - close_prev).abs()
        tr3 = (low - close_prev).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        atr = true_range.ewm(alpha=1.0 / self.period, min_periods=self.period, adjust=False).mean()

        return atr

    def __repr__(self) -> str:
        return f"<ATR(period={self.period})>"
