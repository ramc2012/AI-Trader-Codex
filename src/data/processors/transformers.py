"""Data transformation processors.

Processors for resampling candles, time alignment, normalization,
and other data transformations.
"""

from __future__ import annotations

from typing import Literal, Optional

import numpy as np
import pandas as pd

from src.data.processors.base import DataProcessor
from src.utils.logger import get_logger

logger = get_logger(__name__)


class CandleResampler(DataProcessor):
    """Resample candles to different timeframes.

    Aggregates OHLC data from finer to coarser timeframes (e.g., 1min -> 5min).

    Args:
        target_freq: Target frequency (e.g., '5min', '1H', '1D')
        label: Timestamp label for aggregated data ('right' or 'left')
        closed: Which side of interval is closed ('right' or 'left')
    """

    def __init__(
        self,
        target_freq: str,
        label: Literal["right", "left"] = "right",
        closed: Literal["right", "left"] = "right",
    ) -> None:
        super().__init__(
            name="CandleResampler",
            target_freq=target_freq,
            label=label,
            closed=closed,
        )
        self.target_freq = target_freq
        self.label = label
        self.closed = closed

    def process(self, data: pd.DataFrame) -> pd.DataFrame:
        """Resample candles to target frequency.

        Args:
            data: Input DataFrame with OHLC data

        Returns:
            Resampled DataFrame

        Raises:
            ValueError: If required columns are missing
        """
        required_cols = ["timestamp", "open", "high", "low", "close", "volume"]
        self.validate_input(data, required_cols)

        if not pd.api.types.is_datetime64_any_dtype(data["timestamp"]):
            data = data.copy()
            data["timestamp"] = pd.to_datetime(data["timestamp"])

        data = data.set_index("timestamp").sort_index()

        # Resample using OHLC aggregation
        resampled = data.resample(
            self.target_freq,
            label=self.label,
            closed=self.closed,
        ).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        })

        # Drop rows with missing data (incomplete periods)
        resampled = resampled.dropna()

        # Preserve other columns if present
        other_cols = set(data.columns) - {"open", "high", "low", "close", "volume"}
        for col in other_cols:
            if col in data.columns:
                resampled[col] = data.resample(
                    self.target_freq,
                    label=self.label,
                    closed=self.closed,
                )[col].first()

        self._stats["original_rows"] = len(data)
        self._stats["resampled_rows"] = len(resampled)
        self._stats["target_freq"] = self.target_freq

        logger.info(
            "candles_resampled",
            original=len(data),
            resampled=len(resampled),
            freq=self.target_freq,
        )

        return resampled.reset_index()


class TimeAligner(DataProcessor):
    """Align timestamps to specific time boundaries.

    Rounds timestamps to nearest boundary (e.g., align to 5-minute marks).

    Args:
        freq: Frequency to align to (e.g., '5min', '1H')
        method: Rounding method ('round', 'floor', 'ceil')
    """

    def __init__(
        self,
        freq: str,
        method: Literal["round", "floor", "ceil"] = "round",
    ) -> None:
        super().__init__(
            name="TimeAligner",
            freq=freq,
            method=method,
        )
        self.freq = freq
        self.method = method

    def process(self, data: pd.DataFrame) -> pd.DataFrame:
        """Align timestamps to frequency boundaries.

        Args:
            data: Input DataFrame with 'timestamp' column

        Returns:
            DataFrame with aligned timestamps
        """
        self.validate_input(data, ["timestamp"])

        if not pd.api.types.is_datetime64_any_dtype(data["timestamp"]):
            data = data.copy()
            data["timestamp"] = pd.to_datetime(data["timestamp"])

        data = data.copy()

        if self.method == "round":
            data["timestamp"] = data["timestamp"].dt.round(self.freq)
        elif self.method == "floor":
            data["timestamp"] = data["timestamp"].dt.floor(self.freq)
        elif self.method == "ceil":
            data["timestamp"] = data["timestamp"].dt.ceil(self.freq)

        self._stats["alignment_method"] = self.method
        self._stats["frequency"] = self.freq
        self._stats["rows_processed"] = len(data)

        logger.info(
            "timestamps_aligned",
            method=self.method,
            freq=self.freq,
            rows=len(data),
        )

        return data


class VolumeNormalizer(DataProcessor):
    """Normalize volume data.

    Applies various normalization techniques to volume data for
    better cross-symbol comparison and feature scaling.

    Args:
        method: Normalization method ('zscore', 'minmax', 'log', 'pct_of_mean')
        window: Rolling window for adaptive normalization (optional)
    """

    def __init__(
        self,
        method: Literal["zscore", "minmax", "log", "pct_of_mean"] = "zscore",
        window: Optional[int] = None,
    ) -> None:
        super().__init__(
            name="VolumeNormalizer",
            method=method,
            window=window,
        )
        self.method = method
        self.window = window

    def process(self, data: pd.DataFrame) -> pd.DataFrame:
        """Normalize volume data.

        Args:
            data: Input DataFrame with 'volume' column

        Returns:
            DataFrame with normalized volume column
        """
        self.validate_input(data, ["volume"])

        data = data.copy()
        volume = data["volume"]

        if self.method == "zscore":
            if self.window:
                mean = volume.rolling(self.window).mean()
                std = volume.rolling(self.window).std()
                data["volume_norm"] = (volume - mean) / std
            else:
                data["volume_norm"] = (volume - volume.mean()) / volume.std()

        elif self.method == "minmax":
            if self.window:
                min_vol = volume.rolling(self.window).min()
                max_vol = volume.rolling(self.window).max()
                data["volume_norm"] = (volume - min_vol) / (max_vol - min_vol)
            else:
                data["volume_norm"] = (
                    (volume - volume.min()) / (volume.max() - volume.min())
                )

        elif self.method == "log":
            data["volume_norm"] = np.log1p(volume)

        elif self.method == "pct_of_mean":
            if self.window:
                mean = volume.rolling(self.window).mean()
                data["volume_norm"] = (volume / mean) * 100
            else:
                data["volume_norm"] = (volume / volume.mean()) * 100

        # Drop NaN values introduced by rolling window
        if self.window:
            data = data.dropna()

        self._stats["method"] = self.method
        self._stats["window"] = self.window
        self._stats["rows_processed"] = len(data)

        logger.info(
            "volume_normalized",
            method=self.method,
            window=self.window,
            rows=len(data),
        )

        return data.reset_index(drop=True)


class ReturnCalculator(DataProcessor):
    """Calculate price returns.

    Computes simple, log, or percentage returns over various periods.

    Args:
        method: Return calculation method ('simple', 'log', 'pct')
        periods: List of periods for return calculation
        price_column: Column to use for return calculation
    """

    def __init__(
        self,
        method: Literal["simple", "log", "pct"] = "simple",
        periods: Optional[list[int]] = None,
        price_column: str = "close",
    ) -> None:
        super().__init__(
            name="ReturnCalculator",
            method=method,
            periods=periods,
            price_column=price_column,
        )
        self.method = method
        self.periods = periods or [1, 5, 10, 20]
        self.price_column = price_column

    def process(self, data: pd.DataFrame) -> pd.DataFrame:
        """Calculate returns for specified periods.

        Args:
            data: Input DataFrame with price data

        Returns:
            DataFrame with return columns added
        """
        self.validate_input(data, [self.price_column])

        data = data.copy()
        price = data[self.price_column]

        for period in self.periods:
            col_name = f"return_{period}"

            if self.method == "simple":
                data[col_name] = price.diff(period)
            elif self.method == "log":
                data[col_name] = np.log(price / price.shift(period))
            elif self.method == "pct":
                data[col_name] = price.pct_change(period)

        self._stats["method"] = self.method
        self._stats["periods"] = self.periods
        self._stats["features_created"] = len(self.periods)

        logger.info(
            "returns_calculated",
            method=self.method,
            periods=self.periods,
            rows=len(data),
        )

        return data
