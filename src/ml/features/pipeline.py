"""Feature pipeline orchestrator.

Combines multiple ``FeatureExtractor`` instances into a single
fit/transform pipeline, concatenating their outputs column-wise.
"""

from __future__ import annotations

from typing import List, Optional

import pandas as pd

from src.ml.features.base import FeatureExtractor
from src.ml.features.option_features import OptionFeatureExtractor
from src.ml.features.price_features import PriceFeatureExtractor
from src.ml.features.technical_features import TechnicalFeatureExtractor
from src.utils.logger import get_logger

logger = get_logger(__name__)


class FeaturePipeline:
    """Orchestrate multiple feature extractors.

    Each extractor produces its own DataFrame of features.  The pipeline
    concatenates them column-wise so downstream consumers get a single
    wide feature matrix.

    Args:
        extractors: Initial list of extractors. More can be added later
            via ``add_extractor()``.
    """

    def __init__(
        self, extractors: Optional[List[FeatureExtractor]] = None
    ) -> None:
        self.extractors: List[FeatureExtractor] = extractors or []
        self._is_fitted: bool = False

    # ------------------------------------------------------------------
    # Builder
    # ------------------------------------------------------------------

    def add_extractor(self, extractor: FeatureExtractor) -> FeaturePipeline:
        """Append an extractor to the pipeline.

        Args:
            extractor: A ``FeatureExtractor`` instance.

        Returns:
            Self for method chaining.
        """
        self.extractors.append(extractor)
        return self

    # ------------------------------------------------------------------
    # Fit / Transform
    # ------------------------------------------------------------------

    def fit(self, data: pd.DataFrame) -> FeaturePipeline:
        """Fit all extractors.

        Args:
            data: Training DataFrame.

        Returns:
            Self for method chaining.
        """
        logger.info(
            "fitting_feature_pipeline",
            n_extractors=len(self.extractors),
            rows=len(data),
        )
        for ext in self.extractors:
            ext.fit(data)
        self._is_fitted = True
        return self

    def transform(self, data: pd.DataFrame) -> pd.DataFrame:
        """Transform data through all extractors and concatenate.

        Args:
            data: Input DataFrame.

        Returns:
            Wide DataFrame with features from all extractors.

        Raises:
            RuntimeError: If called before ``fit()``.
        """
        if not self._is_fitted:
            raise RuntimeError(
                "FeaturePipeline must be fitted before transform(). "
                "Call fit() or fit_transform() first."
            )
        all_features: List[pd.DataFrame] = []
        for ext in self.extractors:
            features = ext.transform(data)
            all_features.append(features)

        if not all_features:
            return pd.DataFrame(index=data.index)

        combined = pd.concat(all_features, axis=1)
        logger.info(
            "pipeline_transform_complete",
            total_features=combined.shape[1],
            rows=combined.shape[0],
        )
        return combined

    def fit_transform(self, data: pd.DataFrame) -> pd.DataFrame:
        """Fit all extractors then transform in one step.

        Args:
            data: Training DataFrame.

        Returns:
            Wide DataFrame with features from all extractors.
        """
        return self.fit(data).transform(data)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def is_fitted(self) -> bool:
        """Whether the pipeline has been fitted."""
        return self._is_fitted

    def get_feature_names(self) -> List[str]:
        """Return combined feature names from all extractors.

        Returns:
            Ordered list of all feature column names.
        """
        names: List[str] = []
        for ext in self.extractors:
            names.extend(ext.feature_names())
        return names

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @staticmethod
    def create_default() -> FeaturePipeline:
        """Create a pipeline with the default set of extractors.

        Includes ``PriceFeatureExtractor`` and ``TechnicalFeatureExtractor``.

        Returns:
            Pre-configured ``FeaturePipeline``.
        """
        return FeaturePipeline([
            PriceFeatureExtractor(),
            TechnicalFeatureExtractor(),
        ])

    def __repr__(self) -> str:
        names = [ext.name for ext in self.extractors]
        return f"<FeaturePipeline(extractors={names}, fitted={self._is_fitted})>"
