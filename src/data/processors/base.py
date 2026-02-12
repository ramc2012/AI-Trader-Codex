"""Base data processor interface.

Defines abstract base class for all data processors with common
transformation pipeline interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

import pandas as pd

from src.utils.logger import get_logger

logger = get_logger(__name__)


class DataProcessor(ABC):
    """Abstract base class for data processors.

    All processors should inherit from this class and implement
    the `process()` method to transform DataFrames.

    Args:
        name: Human-readable processor name
        **config: Processor-specific configuration parameters
    """

    def __init__(self, name: str, **config: Any) -> None:
        self.name = name
        self.config = config
        self._stats: Dict[str, Any] = {}

    @abstractmethod
    def process(self, data: pd.DataFrame) -> pd.DataFrame:
        """Transform input data.

        Args:
            data: Input DataFrame to process

        Returns:
            Processed DataFrame

        Raises:
            ValueError: If data is invalid or processing fails
        """
        pass

    def validate_input(self, data: pd.DataFrame, required_columns: list[str]) -> None:
        """Validate input DataFrame has required columns.

        Args:
            data: DataFrame to validate
            required_columns: List of required column names

        Raises:
            ValueError: If required columns are missing
        """
        missing = set(required_columns) - set(data.columns)
        if missing:
            raise ValueError(
                f"{self.name}: Missing required columns: {missing}"
            )

    def get_stats(self) -> Dict[str, Any]:
        """Get processing statistics.

        Returns:
            Dictionary with processor stats
        """
        return {
            "name": self.name,
            "config": self.config,
            **self._stats,
        }

    def reset_stats(self) -> None:
        """Reset processing statistics."""
        self._stats.clear()

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name={self.name})>"
