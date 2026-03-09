"""Base class for all technical indicators."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import numpy as np
import pandas as pd


class Indicator(ABC):
    """Abstract base class for technical indicators.

    All indicators operate on pandas Series or numpy arrays and
    return the same type. Subclasses must implement `calculate()`.
    """

    name: str = "BaseIndicator"

    def __init__(self, period: int | None = None) -> None:
        self.period = period
        self._cache: dict[Any, pd.Series | pd.DataFrame] = {}

    @abstractmethod
    def calculate(self, data: pd.Series) -> pd.Series | pd.DataFrame:
        """Compute the indicator from a price series.

        Args:
            data: Input price series (typically close prices).

        Returns:
            Series or DataFrame with indicator values.
        """
        ...

    def __call__(self, data: pd.Series | pd.DataFrame) -> pd.Series | pd.DataFrame:
        """Calculate indicator with lightweight in-memory caching."""
        if not isinstance(data, (pd.Series, pd.DataFrame)):
            raise TypeError("Indicator input must be pandas Series/DataFrame")

        if not hasattr(self, "_cache"):
            self._cache = {}

        key = self._cache_key(data)
        if key in self._cache:
            return self._cache[key]

        result = self.calculate(data)  # type: ignore[arg-type]
        self._cache[key] = result
        if len(self._cache) > 100:
            # Keep cache bounded.
            self._cache.pop(next(iter(self._cache)))
        return result

    def clear_cache(self) -> None:
        if hasattr(self, "_cache"):
            self._cache.clear()

    def _cache_key(self, data: pd.Series | pd.DataFrame) -> tuple[Any, ...]:
        """Create a stable-enough key for repeated calculations."""
        index = data.index
        first_idx = index[0] if len(index) else None
        last_idx = index[-1] if len(index) else None
        shape = data.shape

        if isinstance(data, pd.Series):
            checksum = float(data.tail(5).sum(skipna=True))
        else:
            checksum = float(data.tail(5).select_dtypes(include=[np.number]).sum().sum())

        return (first_idx, last_idx, shape, round(checksum, 8))

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}>"
