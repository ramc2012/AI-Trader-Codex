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

    @abstractmethod
    def calculate(self, data: pd.Series) -> pd.Series | pd.DataFrame:
        """Compute the indicator from a price series.

        Args:
            data: Input price series (typically close prices).

        Returns:
            Series or DataFrame with indicator values.
        """
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}>"
