"""Option-specific feature extraction.

Computes features from options market data such as put-call ratio,
max pain distance, implied volatility percentile/rank, and open
interest changes.
"""

from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

from src.ml.features.base import FeatureExtractor
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Default lookback for IV rank / percentile calculations.
_IV_LOOKBACK: int = 252


class OptionFeatureExtractor(FeatureExtractor):
    """Extract option-specific features.

    Designed to work with a DataFrame that *may* contain option-market
    columns.  If a column is missing, the corresponding features are
    simply skipped rather than raising an error.

    Expected input columns (all optional):
        * ``pcr`` -- put-call ratio
        * ``max_pain`` -- max pain strike price
        * ``spot`` -- underlying spot price
        * ``iv`` -- implied volatility (annualised, e.g. 0.15 = 15%)
        * ``call_oi`` -- total call open interest
        * ``put_oi`` -- total put open interest

    Features produced (if data available):
        * ``pcr`` -- raw put-call ratio (passthrough)
        * ``max_pain_distance`` -- (spot - max_pain) / spot
        * ``iv_percentile`` -- rolling percentile of IV
        * ``iv_rank`` -- (iv - min) / (max - min) over lookback
        * ``oi_change_pct`` -- percentage change in total OI
        * ``call_put_oi_ratio_change`` -- change in call_oi / put_oi ratio

    Args:
        iv_lookback: Rolling window for IV percentile and rank.
    """

    def __init__(self, iv_lookback: int = _IV_LOOKBACK) -> None:
        super().__init__(name="OptionFeatures")
        self.iv_lookback = iv_lookback

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _has_column(data: pd.DataFrame, col: str) -> bool:
        """Check whether *col* exists and has at least one non-null value."""
        return col in data.columns and data[col].notna().any()

    def _compute_features(self, data: pd.DataFrame) -> pd.DataFrame:
        """Compute option features, skipping missing columns.

        Args:
            data: DataFrame with optional option-market columns.

        Returns:
            DataFrame of computed option features.
        """
        features: dict[str, pd.Series] = {}

        # --- PCR ---
        if self._has_column(data, "pcr"):
            features["pcr"] = data["pcr"].astype(float)

        # --- Max pain distance ---
        if self._has_column(data, "max_pain") and self._has_column(data, "spot"):
            spot = data["spot"].astype(float)
            max_pain = data["max_pain"].astype(float)
            features["max_pain_distance"] = (spot - max_pain) / spot

        # --- IV percentile ---
        if self._has_column(data, "iv"):
            iv = data["iv"].astype(float)
            features["iv_percentile"] = iv.rolling(
                window=self.iv_lookback, min_periods=1
            ).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False)

        # --- IV rank ---
        if self._has_column(data, "iv"):
            iv = data["iv"].astype(float)
            roll_min = iv.rolling(window=self.iv_lookback, min_periods=1).min()
            roll_max = iv.rolling(window=self.iv_lookback, min_periods=1).max()
            iv_range = roll_max - roll_min
            features["iv_rank"] = (iv - roll_min) / iv_range

        # --- OI change percent ---
        if self._has_column(data, "call_oi") and self._has_column(data, "put_oi"):
            call_oi = data["call_oi"].astype(float)
            put_oi = data["put_oi"].astype(float)
            total_oi = call_oi + put_oi
            features["oi_change_pct"] = total_oi.pct_change()

        # --- Call/Put OI ratio change ---
        if self._has_column(data, "call_oi") and self._has_column(data, "put_oi"):
            call_oi = data["call_oi"].astype(float)
            put_oi = data["put_oi"].astype(float)
            ratio = call_oi / put_oi
            features["call_put_oi_ratio_change"] = ratio.pct_change()

        result = pd.DataFrame(features, index=data.index)
        return result

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fit(self, data: pd.DataFrame) -> OptionFeatureExtractor:
        """Fit the extractor.

        Option features are stateless (no learned parameters),
        so this simply marks the extractor as fitted and records
        which columns are available.

        Args:
            data: DataFrame with optional option-market columns.

        Returns:
            Self for method chaining.
        """
        logger.info("fitting_option_features", rows=len(data))
        self._is_fitted = True
        return self

    def transform(self, data: pd.DataFrame) -> pd.DataFrame:
        """Extract option features.

        Gracefully skips features whose source columns are not present.

        Args:
            data: DataFrame with optional option-market columns.

        Returns:
            DataFrame of option features (may be empty if no columns match).

        Raises:
            RuntimeError: If called before ``fit()``.
        """
        if not self._is_fitted:
            raise RuntimeError(
                "OptionFeatureExtractor must be fitted before transform(). "
                "Call fit() or fit_transform() first."
            )
        return self._compute_features(data)

    def feature_names(self) -> List[str]:
        """Return list of all possible feature names.

        Note: Not all features may be present in a given ``transform()``
        call, depending on available input columns.

        Returns:
            List of all feature column names this extractor can produce.
        """
        return [
            "pcr",
            "max_pain_distance",
            "iv_percentile",
            "iv_rank",
            "oi_change_pct",
            "call_put_oi_ratio_change",
        ]
