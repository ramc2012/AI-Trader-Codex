"""Data validation processors.

Processors for validating OHLC data integrity, time sequences,
volume consistency, and data quality.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from src.data.processors.base import DataProcessor
from src.utils.logger import get_logger
from src.utils.validators import validate_ohlc, validate_volume

logger = get_logger(__name__)


class OHLCValidator(DataProcessor):
    """Validate OHLC data integrity.

    Checks that:
    - Low <= Open, Close, High
    - High >= Open, Close, Low
    - Prices are positive
    - OHLC relationships are valid

    Args:
        remove_invalid: Whether to remove invalid rows (vs raising error)
        allow_zero_volume: Whether zero volume is acceptable
    """

    def __init__(
        self,
        remove_invalid: bool = True,
        allow_zero_volume: bool = False,
    ) -> None:
        super().__init__(
            name="OHLCValidator",
            remove_invalid=remove_invalid,
            allow_zero_volume=allow_zero_volume,
        )
        self.remove_invalid = remove_invalid
        self.allow_zero_volume = allow_zero_volume

    def process(self, data: pd.DataFrame) -> pd.DataFrame:
        """Validate OHLC data.

        Args:
            data: Input DataFrame with OHLC columns

        Returns:
            Validated DataFrame

        Raises:
            ValueError: If invalid data found and remove_invalid=False
        """
        required_cols = ["open", "high", "low", "close", "volume"]
        self.validate_input(data, required_cols)

        original_count = len(data)
        invalid_rows = []

        for idx, row in data.iterrows():
            try:
                validate_ohlc(
                    row["open"],
                    row["high"],
                    row["low"],
                    row["close"],
                )
                if not self.allow_zero_volume:
                    validate_volume(row["volume"])
            except (ValueError, Exception) as exc:
                invalid_rows.append(idx)
                logger.warning(
                    "invalid_ohlc_row",
                    index=idx,
                    error=str(exc),
                    row=row.to_dict(),
                )

        if invalid_rows:
            if self.remove_invalid:
                cleaned = data.drop(invalid_rows)
                self._stats["invalid_rows_removed"] = len(invalid_rows)
                self._stats["original_rows"] = original_count
                self._stats["cleaned_rows"] = len(cleaned)

                logger.info(
                    "invalid_ohlc_removed",
                    count=len(invalid_rows),
                    original=original_count,
                )
                return cleaned.reset_index(drop=True)
            else:
                raise ValueError(
                    f"Found {len(invalid_rows)} invalid OHLC rows. "
                    f"Set remove_invalid=True to filter them out."
                )

        self._stats["invalid_rows_removed"] = 0
        self._stats["original_rows"] = original_count
        self._stats["cleaned_rows"] = len(data)

        return data


class TimeSequenceValidator(DataProcessor):
    """Validate time sequence integrity.

    Checks that:
    - Timestamps are in ascending order
    - No duplicate timestamps
    - Timestamps are within expected range

    Args:
        remove_invalid: Whether to remove invalid rows
        require_sorted: Whether to enforce sorted order
    """

    def __init__(
        self,
        remove_invalid: bool = True,
        require_sorted: bool = True,
    ) -> None:
        super().__init__(
            name="TimeSequenceValidator",
            remove_invalid=remove_invalid,
            require_sorted=require_sorted,
        )
        self.remove_invalid = remove_invalid
        self.require_sorted = require_sorted

    def process(self, data: pd.DataFrame) -> pd.DataFrame:
        """Validate time sequence.

        Args:
            data: Input DataFrame with 'timestamp' column

        Returns:
            Validated DataFrame

        Raises:
            ValueError: If invalid sequence found and remove_invalid=False
        """
        self.validate_input(data, ["timestamp"])

        if not pd.api.types.is_datetime64_any_dtype(data["timestamp"]):
            data = data.copy()
            data["timestamp"] = pd.to_datetime(data["timestamp"])

        original_count = len(data)

        # Check for duplicates
        duplicates = data["timestamp"].duplicated()
        if duplicates.any():
            dup_count = duplicates.sum()
            if self.remove_invalid:
                data = data[~duplicates]
                logger.info("duplicate_timestamps_removed", count=dup_count)
            else:
                raise ValueError(f"Found {dup_count} duplicate timestamps")

        # Check sorting
        if self.require_sorted:
            is_sorted = data["timestamp"].is_monotonic_increasing
            if not is_sorted:
                if self.remove_invalid:
                    data = data.sort_values("timestamp")
                    logger.info("timestamps_sorted")
                else:
                    raise ValueError("Timestamps are not in ascending order")

        self._stats["original_rows"] = original_count
        self._stats["cleaned_rows"] = len(data)
        self._stats["invalid_removed"] = original_count - len(data)

        return data.reset_index(drop=True)


class VolumeValidator(DataProcessor):
    """Validate trading volume data.

    Checks that:
    - Volume is non-negative
    - Volume is within expected ranges
    - Detects abnormal volume spikes

    Args:
        min_volume: Minimum acceptable volume
        max_volume_zscore: Maximum z-score for volume spikes
        remove_invalid: Whether to remove invalid rows
    """

    def __init__(
        self,
        min_volume: int = 0,
        max_volume_zscore: float = 10.0,
        remove_invalid: bool = True,
    ) -> None:
        super().__init__(
            name="VolumeValidator",
            min_volume=min_volume,
            max_volume_zscore=max_volume_zscore,
            remove_invalid=remove_invalid,
        )
        self.min_volume = min_volume
        self.max_volume_zscore = max_volume_zscore
        self.remove_invalid = remove_invalid

    def process(self, data: pd.DataFrame) -> pd.DataFrame:
        """Validate volume data.

        Args:
            data: Input DataFrame with 'volume' column

        Returns:
            Validated DataFrame

        Raises:
            ValueError: If invalid volume found and remove_invalid=False
        """
        self.validate_input(data, ["volume"])

        original_count = len(data)
        invalid_mask = data["volume"] < self.min_volume

        # Check for extreme volume spikes
        if len(data) >= 10:
            volume_mean = data["volume"].mean()
            volume_std = data["volume"].std()
            if volume_std > 0:
                z_scores = (data["volume"] - volume_mean) / volume_std
                invalid_mask |= z_scores.abs() > self.max_volume_zscore

        invalid_count = invalid_mask.sum()

        if invalid_count > 0:
            if self.remove_invalid:
                cleaned = data[~invalid_mask]
                self._stats["invalid_volumes_removed"] = invalid_count
                self._stats["original_rows"] = original_count
                self._stats["cleaned_rows"] = len(cleaned)

                logger.info(
                    "invalid_volumes_removed",
                    count=invalid_count,
                    original=original_count,
                )
                return cleaned.reset_index(drop=True)
            else:
                raise ValueError(
                    f"Found {invalid_count} invalid volume rows. "
                    f"Set remove_invalid=True to filter them out."
                )

        self._stats["invalid_volumes_removed"] = 0
        self._stats["original_rows"] = original_count
        self._stats["cleaned_rows"] = len(data)

        return data
