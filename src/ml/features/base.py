"""Base classes for feature extraction.

Provides the abstract base class that all feature extractors inherit
from, ensuring a consistent fit/transform API across the pipeline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler, StandardScaler

from src.utils.logger import get_logger

logger = get_logger(__name__)


class FeatureExtractor(ABC):
    """Base class for all feature extractors.

    Follows the sklearn-style fit/transform pattern so that scaling
    parameters learned on training data can be applied consistently
    to validation and live data.

    Args:
        name: Human-readable name for the extractor.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._is_fitted: bool = False

    @abstractmethod
    def fit(self, data: pd.DataFrame) -> FeatureExtractor:
        """Fit the extractor (learn scaling params, etc.).

        Args:
            data: OHLCV DataFrame with at minimum columns:
                  open, high, low, close, volume.

        Returns:
            Self for method chaining.
        """
        ...

    @abstractmethod
    def transform(self, data: pd.DataFrame) -> pd.DataFrame:
        """Extract features from data.

        Args:
            data: OHLCV DataFrame.

        Returns:
            DataFrame of extracted features (same row count as input).
        """
        ...

    def fit_transform(self, data: pd.DataFrame) -> pd.DataFrame:
        """Fit the extractor then transform data in one step.

        Args:
            data: OHLCV DataFrame.

        Returns:
            DataFrame of extracted features.
        """
        return self.fit(data).transform(data)

    @property
    def is_fitted(self) -> bool:
        """Whether the extractor has been fitted."""
        return self._is_fitted

    @abstractmethod
    def feature_names(self) -> List[str]:
        """Return list of feature names this extractor produces.

        Returns:
            Ordered list of column names produced by ``transform()``.
        """
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name={self.name!r}, fitted={self._is_fitted})>"
