"""Data cleaning processors.

Processors for removing duplicates, handling outliers, filling gaps,
and cleaning raw market data.
"""

from __future__ import annotations

from typing import Literal, Optional

import numpy as np
import pandas as pd

from src.data.processors.base import DataProcessor
from src.utils.logger import get_logger

logger = get_logger(__name__)


class DuplicateRemover(DataProcessor):
    """Remove duplicate candles based on timestamp.

    Args:
        subset: Columns to use for duplicate detection
        keep: Which duplicate to keep ('first', 'last', False)
    """

    def __init__(
        self,
        subset: Optional[list[str]] = None,
        keep: Literal["first", "last", False] = "first",
    ) -> None:
        super().__init__(
            name="DuplicateRemover",
            subset=subset,
            keep=keep,
        )
        self.subset = subset or ["timestamp"]
        self.keep = keep

    def process(self, data: pd.DataFrame) -> pd.DataFrame:
        """Remove duplicate rows.

        Args:
            data: Input DataFrame

        Returns:
            DataFrame with duplicates removed
        """
        self.validate_input(data, self.subset)

        original_count = len(data)
        cleaned = data.drop_duplicates(subset=self.subset, keep=self.keep)
        removed_count = original_count - len(cleaned)

        self._stats["duplicates_removed"] = removed_count
        self._stats["original_rows"] = original_count
        self._stats["cleaned_rows"] = len(cleaned)

        if removed_count > 0:
            logger.info(
                "duplicates_removed",
                processor=self.name,
                count=removed_count,
                original=original_count,
            )

        return cleaned.reset_index(drop=True)


class OutlierRemover(DataProcessor):
    """Remove statistical outliers from OHLC data.

    Uses z-score or IQR method to identify and remove outliers.

    Args:
        method: Outlier detection method ('zscore' or 'iqr')
        threshold: Z-score threshold (for zscore method)
        iqr_multiplier: IQR multiplier (for iqr method)
        columns: Columns to check for outliers
    """

    def __init__(
        self,
        method: Literal["zscore", "iqr"] = "iqr",
        threshold: float = 3.0,
        iqr_multiplier: float = 1.5,
        columns: Optional[list[str]] = None,
    ) -> None:
        super().__init__(
            name="OutlierRemover",
            method=method,
            threshold=threshold,
            iqr_multiplier=iqr_multiplier,
        )
        self.method = method
        self.threshold = threshold
        self.iqr_multiplier = iqr_multiplier
        self.columns = columns or ["open", "high", "low", "close", "volume"]

    def process(self, data: pd.DataFrame) -> pd.DataFrame:
        """Remove outliers from specified columns.

        Args:
            data: Input DataFrame

        Returns:
            DataFrame with outliers removed
        """
        self.validate_input(data, self.columns)

        if len(data) < 10:
            logger.warning("insufficient_data_for_outlier_detection", rows=len(data))
            return data

        original_count = len(data)
        mask = pd.Series([True] * len(data), index=data.index)

        for col in self.columns:
            if col not in data.columns:
                continue

            if self.method == "zscore":
                z_scores = np.abs((data[col] - data[col].mean()) / data[col].std())
                mask &= z_scores < self.threshold
            elif self.method == "iqr":
                Q1 = data[col].quantile(0.25)
                Q3 = data[col].quantile(0.75)
                IQR = Q3 - Q1
                lower_bound = Q1 - self.iqr_multiplier * IQR
                upper_bound = Q3 + self.iqr_multiplier * IQR
                mask &= (data[col] >= lower_bound) & (data[col] <= upper_bound)

        cleaned = data[mask]
        removed_count = original_count - len(cleaned)

        self._stats["outliers_removed"] = removed_count
        self._stats["original_rows"] = original_count
        self._stats["cleaned_rows"] = len(cleaned)

        if removed_count > 0:
            logger.info(
                "outliers_removed",
                processor=self.name,
                method=self.method,
                count=removed_count,
            )

        return cleaned.reset_index(drop=True)


class GapFiller(DataProcessor):
    """Fill gaps in time series data.

    Identifies missing timestamps and fills with forward-fill, backward-fill,
    or interpolation.

    Args:
        method: Fill method ('ffill', 'bfill', 'interpolate')
        freq: Expected frequency (e.g., '1min', '1H', '1D')
        max_gap_periods: Maximum number of periods to fill
    """

    def __init__(
        self,
        method: Literal["ffill", "bfill", "interpolate"] = "ffill",
        freq: Optional[str] = None,
        max_gap_periods: int = 3,
    ) -> None:
        super().__init__(
            name="GapFiller",
            method=method,
            freq=freq,
            max_gap_periods=max_gap_periods,
        )
        self.method = method
        self.freq = freq
        self.max_gap_periods = max_gap_periods

    def process(self, data: pd.DataFrame) -> pd.DataFrame:
        """Fill gaps in time series.

        Args:
            data: Input DataFrame with 'timestamp' column

        Returns:
            DataFrame with gaps filled
        """
        self.validate_input(data, ["timestamp"])

        if not pd.api.types.is_datetime64_any_dtype(data["timestamp"]):
            data = data.copy()
            data["timestamp"] = pd.to_datetime(data["timestamp"])

        data = data.sort_values("timestamp").reset_index(drop=True)
        original_count = len(data)

        if self.freq:
            # Create complete date range
            date_range = pd.date_range(
                start=data["timestamp"].min(),
                end=data["timestamp"].max(),
                freq=self.freq,
            )

            # Reindex to fill gaps
            data = data.set_index("timestamp")
            data = data.reindex(date_range)

            # Apply fill method
            if self.method == "ffill":
                data = data.ffill(limit=self.max_gap_periods)
            elif self.method == "bfill":
                data = data.bfill(limit=self.max_gap_periods)
            elif self.method == "interpolate":
                numeric_cols = data.select_dtypes(include=[np.number]).columns
                data[numeric_cols] = data[numeric_cols].interpolate(
                    method="time", limit=self.max_gap_periods
                )

            data = data.reset_index()
            data.columns = ["timestamp"] + list(data.columns[1:])

        filled_count = len(data) - original_count

        self._stats["gaps_filled"] = filled_count
        self._stats["original_rows"] = original_count
        self._stats["filled_rows"] = len(data)

        if filled_count > 0:
            logger.info(
                "gaps_filled",
                processor=self.name,
                method=self.method,
                count=filled_count,
            )

        return data.dropna().reset_index(drop=True)
