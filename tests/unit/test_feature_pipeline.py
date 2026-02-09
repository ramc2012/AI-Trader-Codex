"""Tests for the ML feature extraction pipeline."""

import numpy as np
import pandas as pd
import pytest

from src.ml.features.base import FeatureExtractor
from src.ml.features.option_features import OptionFeatureExtractor
from src.ml.features.pipeline import FeaturePipeline
from src.ml.features.price_features import PriceFeatureExtractor
from src.ml.features.technical_features import TechnicalFeatureExtractor


# =========================================================================
# Fixtures — synthetic OHLCV data
# =========================================================================


def _make_ohlcv(n: int = 100) -> pd.DataFrame:
    """Generate *n* rows of realistic OHLCV data with a slight uptrend."""
    np.random.seed(42)
    close = 22000.0 + np.cumsum(np.random.normal(2, 30, n))
    high = close + np.abs(np.random.normal(20, 10, n))
    low = close - np.abs(np.random.normal(20, 10, n))
    open_ = close + np.random.normal(0, 10, n)
    volume = np.random.randint(5000, 50000, n).astype(float)
    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


@pytest.fixture
def ohlcv_100() -> pd.DataFrame:
    """100-row OHLCV DataFrame."""
    return _make_ohlcv(100)


@pytest.fixture
def ohlcv_200() -> pd.DataFrame:
    """200-row OHLCV DataFrame for technical indicators that need longer windows."""
    return _make_ohlcv(200)


@pytest.fixture
def ohlcv_single_row() -> pd.DataFrame:
    """Single-row OHLCV DataFrame (edge case)."""
    return _make_ohlcv(1)


# =========================================================================
# PriceFeatureExtractor
# =========================================================================


class TestPriceFeatureExtractor:
    def test_fit_returns_self(self, ohlcv_100: pd.DataFrame) -> None:
        ext = PriceFeatureExtractor(scale=False)
        result = ext.fit(ohlcv_100)
        assert result is ext

    def test_is_fitted_becomes_true(self, ohlcv_100: pd.DataFrame) -> None:
        ext = PriceFeatureExtractor(scale=False)
        assert ext.is_fitted is False
        ext.fit(ohlcv_100)
        assert ext.is_fitted is True

    def test_transform_returns_dataframe_with_expected_columns(
        self, ohlcv_100: pd.DataFrame
    ) -> None:
        ext = PriceFeatureExtractor(scale=False)
        ext.fit(ohlcv_100)
        features = ext.transform(ohlcv_100)
        assert isinstance(features, pd.DataFrame)
        assert len(features) == len(ohlcv_100)
        # Check key feature columns are present
        expected_substrings = ["return_", "zscore_", "momentum_", "range_pct", "gap", "cum_return_"]
        for substr in expected_substrings:
            matches = [c for c in features.columns if substr in c]
            assert len(matches) > 0, f"No column containing '{substr}'"

    def test_features_include_returns_zscores_momentum(
        self, ohlcv_100: pd.DataFrame
    ) -> None:
        ext = PriceFeatureExtractor(scale=False)
        ext.fit(ohlcv_100)
        names = ext.feature_names()
        assert "return_1" in names
        assert "zscore_10" in names
        assert "momentum_5" in names

    def test_scaling_normalises_values(self, ohlcv_100: pd.DataFrame) -> None:
        ext_scaled = PriceFeatureExtractor(scale=True)
        ext_scaled.fit(ohlcv_100)
        features_scaled = ext_scaled.transform(ohlcv_100)
        # After StandardScaler, mean should be near 0 (ignoring NaN rows)
        means = features_scaled.mean()
        # Not all columns will be exactly 0 due to NaN handling, but most should be close
        assert (means.abs() < 1.0).sum() > len(means) // 2

    def test_transform_before_fit_raises(self) -> None:
        ext = PriceFeatureExtractor(scale=False)
        with pytest.raises(RuntimeError, match="fitted"):
            ext.transform(_make_ohlcv(10))

    def test_fit_transform_works(self, ohlcv_100: pd.DataFrame) -> None:
        ext = PriceFeatureExtractor(scale=False)
        result = ext.fit_transform(ohlcv_100)
        assert isinstance(result, pd.DataFrame)
        assert ext.is_fitted is True


# =========================================================================
# TechnicalFeatureExtractor
# =========================================================================


class TestTechnicalFeatureExtractor:
    def test_transform_returns_indicator_features(
        self, ohlcv_200: pd.DataFrame
    ) -> None:
        ext = TechnicalFeatureExtractor()
        ext.fit(ohlcv_200)
        features = ext.transform(ohlcv_200)
        assert isinstance(features, pd.DataFrame)
        assert len(features) == len(ohlcv_200)

    def test_includes_rsi_macd_bb_features(
        self, ohlcv_200: pd.DataFrame
    ) -> None:
        ext = TechnicalFeatureExtractor()
        ext.fit(ohlcv_200)
        features = ext.transform(ohlcv_200)
        assert "rsi_14" in features.columns
        assert "macd_histogram" in features.columns
        assert "bb_position" in features.columns
        assert "atr_norm" in features.columns

    def test_includes_sma_and_ema_features(
        self, ohlcv_200: pd.DataFrame
    ) -> None:
        ext = TechnicalFeatureExtractor()
        ext.fit(ohlcv_200)
        names = ext.feature_names()
        assert "sma_cross_5_20" in names
        assert "ema_norm_9" in names

    def test_fit_returns_self(self, ohlcv_200: pd.DataFrame) -> None:
        ext = TechnicalFeatureExtractor()
        result = ext.fit(ohlcv_200)
        assert result is ext
        assert ext.is_fitted is True


# =========================================================================
# OptionFeatureExtractor
# =========================================================================


class TestOptionFeatureExtractor:
    def test_handles_missing_columns_gracefully(
        self, ohlcv_100: pd.DataFrame
    ) -> None:
        """OHLCV data has no option columns — should return empty features."""
        ext = OptionFeatureExtractor()
        ext.fit(ohlcv_100)
        features = ext.transform(ohlcv_100)
        assert isinstance(features, pd.DataFrame)
        assert len(features) == len(ohlcv_100)
        # No option columns → empty features
        assert features.shape[1] == 0

    def test_computes_iv_rank_when_iv_present(self) -> None:
        """When IV column is present, iv_rank should be computed."""
        np.random.seed(42)
        n = 50
        df = _make_ohlcv(n)
        df["iv"] = np.random.uniform(0.10, 0.30, n)

        ext = OptionFeatureExtractor(iv_lookback=20)
        ext.fit(df)
        features = ext.transform(df)
        assert "iv_rank" in features.columns
        assert "iv_percentile" in features.columns

    def test_computes_pcr_when_present(self) -> None:
        np.random.seed(42)
        n = 50
        df = _make_ohlcv(n)
        df["pcr"] = np.random.uniform(0.8, 1.2, n)

        ext = OptionFeatureExtractor()
        ext.fit(df)
        features = ext.transform(df)
        assert "pcr" in features.columns

    def test_computes_oi_features_when_present(self) -> None:
        np.random.seed(42)
        n = 50
        df = _make_ohlcv(n)
        df["call_oi"] = np.random.randint(10000, 50000, n).astype(float)
        df["put_oi"] = np.random.randint(10000, 50000, n).astype(float)

        ext = OptionFeatureExtractor()
        ext.fit(df)
        features = ext.transform(df)
        assert "oi_change_pct" in features.columns
        assert "call_put_oi_ratio_change" in features.columns

    def test_feature_names_lists_all_possible(self) -> None:
        ext = OptionFeatureExtractor()
        names = ext.feature_names()
        assert "pcr" in names
        assert "iv_rank" in names
        assert "max_pain_distance" in names


# =========================================================================
# FeaturePipeline
# =========================================================================


class TestFeaturePipeline:
    def test_combines_multiple_extractors(self, ohlcv_200: pd.DataFrame) -> None:
        pipe = FeaturePipeline([
            PriceFeatureExtractor(scale=False),
            TechnicalFeatureExtractor(),
        ])
        pipe.fit(ohlcv_200)
        features = pipe.transform(ohlcv_200)
        assert isinstance(features, pd.DataFrame)
        # Should have columns from both extractors
        assert "return_1" in features.columns
        assert "rsi_14" in features.columns

    def test_fit_transform_works(self, ohlcv_200: pd.DataFrame) -> None:
        pipe = FeaturePipeline([
            PriceFeatureExtractor(scale=False),
        ])
        features = pipe.fit_transform(ohlcv_200)
        assert pipe.is_fitted is True
        assert isinstance(features, pd.DataFrame)

    def test_create_default_returns_pipeline(self) -> None:
        pipe = FeaturePipeline.create_default()
        assert isinstance(pipe, FeaturePipeline)
        assert len(pipe.extractors) == 2
        # Should have PriceFeatureExtractor and TechnicalFeatureExtractor
        extractor_types = {type(e).__name__ for e in pipe.extractors}
        assert "PriceFeatureExtractor" in extractor_types
        assert "TechnicalFeatureExtractor" in extractor_types

    def test_get_feature_names(self) -> None:
        pipe = FeaturePipeline([
            PriceFeatureExtractor(scale=False),
            TechnicalFeatureExtractor(),
        ])
        names = pipe.get_feature_names()
        assert isinstance(names, list)
        assert len(names) > 0
        # Should contain features from both extractors
        assert any("return_" in n for n in names)
        assert any("rsi_" in n for n in names)

    def test_transform_before_fit_raises(self) -> None:
        pipe = FeaturePipeline([PriceFeatureExtractor(scale=False)])
        with pytest.raises(RuntimeError, match="fitted"):
            pipe.transform(_make_ohlcv(10))

    def test_add_extractor_chaining(self) -> None:
        pipe = FeaturePipeline()
        result = pipe.add_extractor(PriceFeatureExtractor(scale=False))
        assert result is pipe
        assert len(pipe.extractors) == 1

    def test_is_fitted_property(self, ohlcv_200: pd.DataFrame) -> None:
        pipe = FeaturePipeline([PriceFeatureExtractor(scale=False)])
        assert pipe.is_fitted is False
        pipe.fit(ohlcv_200)
        assert pipe.is_fitted is True


# =========================================================================
# Edge cases
# =========================================================================


class TestEdgeCases:
    def test_single_row_dataframe(self, ohlcv_single_row: pd.DataFrame) -> None:
        """Single-row input should not crash."""
        ext = PriceFeatureExtractor(scale=False)
        ext.fit(ohlcv_single_row)
        features = ext.transform(ohlcv_single_row)
        assert len(features) == 1

    def test_fit_transform_default_pipeline_on_ohlcv(
        self, ohlcv_200: pd.DataFrame
    ) -> None:
        pipe = FeaturePipeline.create_default()
        features = pipe.fit_transform(ohlcv_200)
        assert isinstance(features, pd.DataFrame)
        assert len(features) == len(ohlcv_200)
        # Should have many features
        assert features.shape[1] > 10

    def test_empty_pipeline_returns_empty_features(
        self, ohlcv_100: pd.DataFrame
    ) -> None:
        pipe = FeaturePipeline([])
        pipe.fit(ohlcv_100)
        features = pipe.transform(ohlcv_100)
        assert isinstance(features, pd.DataFrame)
        assert features.shape[1] == 0
