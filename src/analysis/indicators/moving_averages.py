"""Moving average indicators: SMA, EMA, WMA."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.analysis.indicators.base import Indicator


class SMA(Indicator):
    """Simple Moving Average.

    Args:
        period: Number of periods for the average.
    """

    name = "SMA"

    def __init__(self, period: int = 20) -> None:
        if period < 1:
            raise ValueError(f"SMA period must be >= 1, got {period}")
        self.period = period

    def calculate(self, data: pd.Series) -> pd.Series:
        """Compute SMA.

        Args:
            data: Price series.

        Returns:
            Series with SMA values (NaN for initial period).
        """
        return data.rolling(window=self.period, min_periods=self.period).mean()

    def __repr__(self) -> str:
        return f"<SMA(period={self.period})>"


class EMA(Indicator):
    """Exponential Moving Average.

    Args:
        period: Number of periods (span) for the EMA.
    """

    name = "EMA"

    def __init__(self, period: int = 20) -> None:
        if period < 1:
            raise ValueError(f"EMA period must be >= 1, got {period}")
        self.period = period

    def calculate(self, data: pd.Series) -> pd.Series:
        """Compute EMA.

        Args:
            data: Price series.

        Returns:
            Series with EMA values.
        """
        return data.ewm(span=self.period, adjust=False).mean()

    def __repr__(self) -> str:
        return f"<EMA(period={self.period})>"


class WMA(Indicator):
    """Weighted Moving Average.

    Linearly weights recent prices more heavily.

    Args:
        period: Number of periods.
    """

    name = "WMA"

    def __init__(self, period: int = 20) -> None:
        if period < 1:
            raise ValueError(f"WMA period must be >= 1, got {period}")
        self.period = period

    def calculate(self, data: pd.Series) -> pd.Series:
        """Compute WMA.

        Args:
            data: Price series.

        Returns:
            Series with WMA values (NaN for initial period).
        """
        weights = np.arange(1, self.period + 1, dtype=float)

        def _wma(window: np.ndarray) -> float:
            return np.dot(window, weights) / weights.sum()

        return data.rolling(window=self.period, min_periods=self.period).apply(
            _wma, raw=True
        )

    def __repr__(self) -> str:
        return f"<WMA(period={self.period})>"
