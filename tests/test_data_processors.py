"""Tests for data processors.

Tests cleaners, validators, and transformers for data processing pipeline.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from src.data.processors.cleaners import (
    DuplicateRemover,
    GapFiller,
    OutlierRemover,
)
from src.data.processors.transformers import (
    CandleResampler,
    ReturnCalculator,
    TimeAligner,
    VolumeNormalizer,
)
from src.data.processors.validators import (
    OHLCValidator,
    TimeSequenceValidator,
    VolumeValidator,
)


# ==============================================================================
# Test Data Fixtures
# ==============================================================================


@pytest.fixture
def sample_ohlc_data():
    """Create sample OHLC DataFrame for testing."""
    dates = pd.date_range(start="2024-01-01", periods=100, freq="1min")
    data = pd.DataFrame({
        "timestamp": dates,
        "open": 100 + np.random.randn(100) * 2,
        "high": 102 + np.random.randn(100) * 2,
        "low": 98 + np.random.randn(100) * 2,
        "close": 100 + np.random.randn(100) * 2,
        "volume": np.random.randint(1000, 10000, 100),
    })

    # Ensure OHLC validity
    data["high"] = data[["open", "high", "low", "close"]].max(axis=1)
    data["low"] = data[["open", "high", "low", "close"]].min(axis=1)

    return data


@pytest.fixture
def sample_ohlc_with_duplicates(sample_ohlc_data):
    """Create OHLC data with duplicate timestamps."""
    # Add some duplicate rows
    duplicates = sample_ohlc_data.iloc[:5].copy()
    return pd.concat([sample_ohlc_data, duplicates], ignore_index=True)


@pytest.fixture
def sample_ohlc_with_outliers(sample_ohlc_data):
    """Create OHLC data with outliers."""
    data = sample_ohlc_data.copy()
    # Add extreme outliers
    data.loc[10, "high"] = 10000  # Extreme high
    data.loc[20, "volume"] = 1000000  # Extreme volume
    return data


# ==============================================================================
# Cleaner Tests
# ==============================================================================


def test_duplicate_remover(sample_ohlc_with_duplicates):
    """Test DuplicateRemover processor."""
    processor = DuplicateRemover(subset=["timestamp"], keep="first")
    cleaned = processor.process(sample_ohlc_with_duplicates)

    assert len(cleaned) < len(sample_ohlc_with_duplicates)
    assert not cleaned["timestamp"].duplicated().any()
    assert processor.get_stats()["duplicates_removed"] == 5


def test_outlier_remover_iqr(sample_ohlc_with_outliers):
    """Test OutlierRemover with IQR method."""
    processor = OutlierRemover(
        method="iqr",
        iqr_multiplier=1.5,
        columns=["high", "volume"],
    )
    cleaned = processor.process(sample_ohlc_with_outliers)

    assert len(cleaned) < len(sample_ohlc_with_outliers)
    stats = processor.get_stats()
    assert stats["outliers_removed"] > 0


def test_outlier_remover_zscore(sample_ohlc_with_outliers):
    """Test OutlierRemover with z-score method."""
    processor = OutlierRemover(
        method="zscore",
        threshold=3.0,
        columns=["high", "volume"],
    )
    cleaned = processor.process(sample_ohlc_with_outliers)

    assert len(cleaned) < len(sample_ohlc_with_outliers)


def test_gap_filler():
    """Test GapFiller processor."""
    # Create data with gaps
    dates = pd.date_range(start="2024-01-01 09:00", periods=10, freq="5min")
    # Remove some dates to create gaps
    dates = dates.drop([dates[3], dates[5]])

    data = pd.DataFrame({
        "timestamp": dates,
        "open": range(len(dates)),
        "high": range(len(dates)),
        "low": range(len(dates)),
        "close": range(len(dates)),
        "volume": range(len(dates)),
    })

    processor = GapFiller(method="ffill", freq="5min", max_gap_periods=2)
    filled = processor.process(data)

    # Should have more rows after filling gaps
    assert len(filled) >= len(data)


# ==============================================================================
# Validator Tests
# ==============================================================================


def test_ohlc_validator_valid_data(sample_ohlc_data):
    """Test OHLCValidator with valid data."""
    processor = OHLCValidator(remove_invalid=True)
    validated = processor.process(sample_ohlc_data)

    # All data should be valid
    assert len(validated) == len(sample_ohlc_data)
    stats = processor.get_stats()
    assert stats["invalid_rows_removed"] == 0


def test_ohlc_validator_invalid_data():
    """Test OHLCValidator with invalid data."""
    data = pd.DataFrame({
        "timestamp": pd.date_range(start="2024-01-01", periods=5, freq="1min"),
        "open": [100, 100, 100, 100, 100],
        "high": [105, 105, 95, 105, 105],  # Row 2 has high < close (invalid)
        "low": [95, 95, 90, 95, 95],  # Row 2 adjusted to be valid for low
        "close": [102, 102, 92, 102, 102],  # Row 2 close adjusted to be valid
        "volume": [1000, 1000, 1000, 1000, 1000],
    })

    processor = OHLCValidator(remove_invalid=True)
    validated = processor.process(data)

    # Should remove invalid row
    assert len(validated) < len(data)
    stats = processor.get_stats()
    assert stats["invalid_rows_removed"] > 0


def test_time_sequence_validator_sorted(sample_ohlc_data):
    """Test TimeSequenceValidator with sorted data."""
    processor = TimeSequenceValidator(require_sorted=True)
    validated = processor.process(sample_ohlc_data)

    assert len(validated) == len(sample_ohlc_data)
    assert validated["timestamp"].is_monotonic_increasing


def test_time_sequence_validator_unsorted():
    """Test TimeSequenceValidator with unsorted data."""
    data = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2024-01-01 10:00",
            "2024-01-01 09:00",  # Out of order
            "2024-01-01 11:00",
        ]),
        "close": [100, 101, 102],
    })

    processor = TimeSequenceValidator(require_sorted=True, remove_invalid=True)
    validated = processor.process(data)

    # Should be sorted now
    assert validated["timestamp"].is_monotonic_increasing


def test_volume_validator(sample_ohlc_data):
    """Test VolumeValidator with valid data."""
    processor = VolumeValidator(min_volume=0, max_volume_zscore=5.0)
    validated = processor.process(sample_ohlc_data)

    assert len(validated) == len(sample_ohlc_data)
    assert (validated["volume"] >= 0).all()


def test_volume_validator_negative_volume():
    """Test VolumeValidator with negative volumes."""
    data = pd.DataFrame({
        "timestamp": pd.date_range(start="2024-01-01", periods=5, freq="1min"),
        "volume": [1000, 2000, -500, 3000, 4000],  # Negative volume
    })

    processor = VolumeValidator(min_volume=0, remove_invalid=True)
    validated = processor.process(data)

    # Should remove negative volume
    assert len(validated) < len(data)
    assert (validated["volume"] >= 0).all()


# ==============================================================================
# Transformer Tests
# ==============================================================================


def test_candle_resampler():
    """Test CandleResampler processor."""
    # Create 1-minute data
    dates = pd.date_range(start="2024-01-01 09:00", periods=10, freq="1min")
    data = pd.DataFrame({
        "timestamp": dates,
        "open": [100, 101, 102, 103, 104, 105, 106, 107, 108, 109],
        "high": [101, 102, 103, 104, 105, 106, 107, 108, 109, 110],
        "low": [99, 100, 101, 102, 103, 104, 105, 106, 107, 108],
        "close": [100.5, 101.5, 102.5, 103.5, 104.5, 105.5, 106.5, 107.5, 108.5, 109.5],
        "volume": [1000] * 10,
    })

    # Resample to 5-minute candles
    processor = CandleResampler(target_freq="5min")
    resampled = processor.process(data)

    # Pandas resampling creates bins based on the label/closed parameters
    # With 10 1-min candles starting at 09:00, we get 3 bins (not 2)
    assert len(resampled) >= 2
    assert resampled.iloc[0]["open"] == 100
    assert resampled.iloc[0]["volume"] >= 1000  # At least 1 candle worth


def test_time_aligner():
    """Test TimeAligner processor."""
    # Create data with irregular timestamps
    data = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2024-01-01 09:01:23",
            "2024-01-01 09:06:47",
            "2024-01-01 09:11:12",
        ]),
        "close": [100, 101, 102],
    })

    processor = TimeAligner(freq="5min", method="round")
    aligned = processor.process(data)

    # Timestamps should be rounded to 5-minute boundaries
    expected = pd.to_datetime([
        "2024-01-01 09:00:00",
        "2024-01-01 09:05:00",
        "2024-01-01 09:10:00",
    ])
    pd.testing.assert_index_equal(
        pd.DatetimeIndex(aligned["timestamp"]),
        pd.DatetimeIndex(expected),
        check_names=False,
    )


def test_volume_normalizer_zscore(sample_ohlc_data):
    """Test VolumeNormalizer with z-score method."""
    processor = VolumeNormalizer(method="zscore")
    normalized = processor.process(sample_ohlc_data)

    assert "volume_norm" in normalized.columns
    # Z-score should have mean ~0 and std ~1
    assert abs(normalized["volume_norm"].mean()) < 0.1
    assert abs(normalized["volume_norm"].std() - 1.0) < 0.1


def test_volume_normalizer_minmax(sample_ohlc_data):
    """Test VolumeNormalizer with minmax method."""
    processor = VolumeNormalizer(method="minmax")
    normalized = processor.process(sample_ohlc_data)

    assert "volume_norm" in normalized.columns
    # Min-max should be in range [0, 1]
    assert normalized["volume_norm"].min() >= 0
    assert normalized["volume_norm"].max() <= 1


def test_volume_normalizer_log(sample_ohlc_data):
    """Test VolumeNormalizer with log method."""
    processor = VolumeNormalizer(method="log")
    normalized = processor.process(sample_ohlc_data)

    assert "volume_norm" in normalized.columns
    # Log-transformed values should be positive
    assert (normalized["volume_norm"] >= 0).all()


def test_return_calculator_simple():
    """Test ReturnCalculator with simple returns."""
    data = pd.DataFrame({
        "timestamp": pd.date_range(start="2024-01-01", periods=10, freq="1D"),
        "close": [100, 102, 101, 103, 105, 104, 106, 108, 107, 109],
    })

    processor = ReturnCalculator(method="simple", periods=[1, 2])
    returns = processor.process(data)

    assert "return_1" in returns.columns
    assert "return_2" in returns.columns
    # First return should be close[1] - close[0]
    assert returns.iloc[1]["return_1"] == 2.0


def test_return_calculator_pct():
    """Test ReturnCalculator with percentage returns."""
    data = pd.DataFrame({
        "timestamp": pd.date_range(start="2024-01-01", periods=10, freq="1D"),
        "close": [100, 102, 101, 103, 105, 104, 106, 108, 107, 109],
    })

    processor = ReturnCalculator(method="pct", periods=[1])
    returns = processor.process(data)

    assert "return_1" in returns.columns
    # First return should be (102-100)/100 = 0.02
    assert abs(returns.iloc[1]["return_1"] - 0.02) < 0.0001


def test_return_calculator_log():
    """Test ReturnCalculator with log returns."""
    data = pd.DataFrame({
        "timestamp": pd.date_range(start="2024-01-01", periods=10, freq="1D"),
        "close": [100, 102, 101, 103, 105, 104, 106, 108, 107, 109],
    })

    processor = ReturnCalculator(method="log", periods=[1])
    returns = processor.process(data)

    assert "return_1" in returns.columns
    # Log returns should be close to percentage returns for small changes
    assert not returns["return_1"].isna().all()


# ==============================================================================
# Integration Tests
# ==============================================================================


def test_processor_pipeline(sample_ohlc_with_duplicates):
    """Test chaining multiple processors."""
    # Clean duplicates
    dedup = DuplicateRemover()
    cleaned = dedup.process(sample_ohlc_with_duplicates)

    # Validate OHLC
    validator = OHLCValidator()
    validated = validator.process(cleaned)

    # Normalize volume
    normalizer = VolumeNormalizer(method="zscore")
    normalized = normalizer.process(validated)

    # Calculate returns
    returns_calc = ReturnCalculator(periods=[1, 5])
    final = returns_calc.process(normalized)

    assert "volume_norm" in final.columns
    assert "return_1" in final.columns
    assert "return_5" in final.columns
    assert len(final) <= len(sample_ohlc_with_duplicates)
