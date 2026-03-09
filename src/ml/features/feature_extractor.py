"""Feature extraction facade used by the training and signal pipeline.

This module keeps a plan-compatible import path while reusing the
project's specialized extractors in ``price_features``, ``technical_features``,
and ``option_features``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA

from src.ml.features.base import FeatureExtractor as _BaseFeatureExtractor
from src.ml.features.option_features import OptionFeatureExtractor
from src.ml.features.pipeline import FeaturePipeline
from src.ml.features.price_features import PriceFeatureExtractor
from src.ml.features.technical_features import TechnicalFeatureExtractor
from src.utils.logger import get_logger

logger = get_logger(__name__)


class FeatureExtractor(_BaseFeatureExtractor):
    """Plan-compatible alias for the project's abstract base extractor."""


@dataclass
class FeatureSelectionConfig:
    """Configuration for lightweight feature selection."""

    drop_constant_std: float = 1e-10
    correlation_threshold: float = 0.98
    max_features: int | None = None


class FeatureSelector:
    """Deterministic feature selector for tabular OHLCV features."""

    def __init__(self, config: FeatureSelectionConfig | None = None) -> None:
        self.config = config or FeatureSelectionConfig()
        self._selected_columns: list[str] = []

    def fit(self, features: pd.DataFrame) -> FeatureSelector:
        """Learn selected columns from a feature matrix."""
        if features.empty:
            self._selected_columns = []
            return self

        selected = self._drop_constant_columns(features)
        selected = self._drop_correlated_columns(selected)

        if self.config.max_features and len(selected.columns) > self.config.max_features:
            variance = selected.var(numeric_only=True).sort_values(ascending=False)
            selected = selected[variance.head(self.config.max_features).index]

        self._selected_columns = list(selected.columns)
        logger.info("feature_selector_fit", input_cols=features.shape[1], selected=len(self._selected_columns))
        return self

    def transform(self, features: pd.DataFrame) -> pd.DataFrame:
        """Apply learned selection to a feature matrix."""
        if not self._selected_columns:
            return pd.DataFrame(index=features.index)
        keep = [c for c in self._selected_columns if c in features.columns]
        return features[keep].copy()

    def fit_transform(self, features: pd.DataFrame) -> pd.DataFrame:
        return self.fit(features).transform(features)

    def _drop_constant_columns(self, features: pd.DataFrame) -> pd.DataFrame:
        if features.empty:
            return features
        numeric = features.select_dtypes(include=["number"]).copy()
        std = numeric.std(numeric_only=True)
        keep_num = std[std > self.config.drop_constant_std].index.tolist()
        keep_non_num = [c for c in features.columns if c not in numeric.columns]
        return features[keep_non_num + keep_num]

    def _drop_correlated_columns(self, features: pd.DataFrame) -> pd.DataFrame:
        numeric = features.select_dtypes(include=["number"])
        if numeric.shape[1] < 2:
            return features

        corr = numeric.corr().abs()
        upper = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
        drop_cols = [
            col
            for col in upper.columns
            if (upper[col] > self.config.correlation_threshold).any()
        ]
        if not drop_cols:
            return features
        return features.drop(columns=drop_cols, errors="ignore")

    @property
    def selected_columns(self) -> list[str]:
        return list(self._selected_columns)


class DimensionalityReducer:
    """PCA-based dimensionality reduction for dense feature frames."""

    def __init__(self, n_components: float | int = 0.95) -> None:
        self.n_components = n_components
        self._pca = PCA(n_components=n_components)
        self._is_fitted = False

    def fit(self, features: pd.DataFrame) -> DimensionalityReducer:
        numeric = features.select_dtypes(include=["number"]).fillna(0.0)
        if numeric.empty:
            self._is_fitted = True
            return self
        self._pca.fit(numeric.values)
        self._is_fitted = True
        return self

    def transform(self, features: pd.DataFrame) -> pd.DataFrame:
        if not self._is_fitted:
            raise RuntimeError("DimensionalityReducer must be fitted before transform().")
        numeric = features.select_dtypes(include=["number"]).fillna(0.0)
        if numeric.empty:
            return pd.DataFrame(index=features.index)
        reduced = self._pca.transform(numeric.values)
        cols = [f"pc_{i+1}" for i in range(reduced.shape[1])]
        return pd.DataFrame(reduced, columns=cols, index=features.index)

    def fit_transform(self, features: pd.DataFrame) -> pd.DataFrame:
        return self.fit(features).transform(features)


class UnifiedFeatureExtractor:
    """Orchestrates extraction, selection, and optional PCA reduction."""

    def __init__(
        self,
        use_option_features: bool = True,
        selection_config: FeatureSelectionConfig | None = None,
        pca_components: float | int | None = None,
    ) -> None:
        extractors: list[_BaseFeatureExtractor] = [
            PriceFeatureExtractor(),
            TechnicalFeatureExtractor(),
        ]
        if use_option_features:
            extractors.append(OptionFeatureExtractor())

        self.pipeline = FeaturePipeline(extractors)
        self.selector = FeatureSelector(selection_config)
        self.reducer = (
            DimensionalityReducer(n_components=pca_components)
            if pca_components is not None
            else None
        )
        self._is_fitted = False

    def fit(self, data: pd.DataFrame) -> UnifiedFeatureExtractor:
        features = self.pipeline.fit_transform(data)
        selected = self.selector.fit_transform(features)
        if self.reducer is not None:
            self.reducer.fit(selected)
        self._is_fitted = True
        return self

    def transform(self, data: pd.DataFrame) -> pd.DataFrame:
        if not self._is_fitted:
            raise RuntimeError("UnifiedFeatureExtractor must be fitted before transform().")
        features = self.pipeline.transform(data)
        selected = self.selector.transform(features)
        if self.reducer is None:
            return selected
        return self.reducer.transform(selected)

    def fit_transform(self, data: pd.DataFrame) -> pd.DataFrame:
        return self.fit(data).transform(data)

    def metadata(self) -> dict[str, Any]:
        return {
            "selected_features": self.selector.selected_columns,
            "pipeline_features": self.pipeline.get_feature_names(),
            "pca_enabled": self.reducer is not None,
        }
