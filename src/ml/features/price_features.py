"""Price-based feature extraction.

Computes returns, z-scores, momentum, range features, gaps,
and cumulative returns from OHLCV data. All features are optionally
scaled via a StandardScaler fitted during ``fit()``.
"""

from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from src.ml.features.base import FeatureExtractor
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Default window sets for each feature group.
_RETURN_WINDOWS: List[int] = [1, 5, 10, 20]
_ZSCORE_WINDOWS: List[int] = [10, 20, 50]
_MOMENTUM_WINDOWS: List[int] = [5, 10, 20]
_CUM_RETURN_WINDOWS: List[int] = [5, 10, 20]


class PriceFeatureExtractor(FeatureExtractor):
    """Extract price-based features from OHLCV data.

    Features produced:
        * Simple and log returns for multiple windows
        * Z-scores (distance from rolling mean in std units)
        * Momentum ratios
        * Intra-bar range features (range pct, close position)
        * Overnight gap
        * Cumulative log returns

    The extractor maintains a ``StandardScaler`` that is fitted on the
    training set during ``fit()`` and applied during ``transform()``.

    Args:
        return_windows: Windows for return calculations.
        zscore_windows: Windows for z-score calculations.
        momentum_windows: Windows for momentum calculations.
        cum_return_windows: Windows for cumulative return calculations.
        scale: Whether to apply StandardScaler to features.
    """

    def __init__(
        self,
        return_windows: List[int] | None = None,
        zscore_windows: List[int] | None = None,
        momentum_windows: List[int] | None = None,
        cum_return_windows: List[int] | None = None,
        scale: bool = True,
    ) -> None:
        super().__init__(name="PriceFeatures")
        self.return_windows = return_windows or list(_RETURN_WINDOWS)
        self.zscore_windows = zscore_windows or list(_ZSCORE_WINDOWS)
        self.momentum_windows = momentum_windows or list(_MOMENTUM_WINDOWS)
        self.cum_return_windows = cum_return_windows or list(_CUM_RETURN_WINDOWS)
        self.scale = scale
        self._scaler: StandardScaler = StandardScaler()
        self._feature_names: List[str] = self._build_feature_names()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_feature_names(self) -> List[str]:
        """Build the ordered list of feature column names."""
        names: List[str] = []

        # Returns
        for w in self.return_windows:
            names.append(f"return_{w}")
            names.append(f"log_return_{w}")

        # Z-scores
        for w in self.zscore_windows:
            names.append(f"zscore_{w}")

        # Momentum
        for w in self.momentum_windows:
            names.append(f"momentum_{w}")

        # Range features
        names.append("range_pct")
        names.append("close_position")

        # Gap
        names.append("gap")

        # Cumulative returns
        for w in self.cum_return_windows:
            names.append(f"cum_return_{w}")

        return names

    def _compute_features(self, data: pd.DataFrame) -> pd.DataFrame:
        """Compute raw (unscaled) features from OHLCV data.

        Args:
            data: DataFrame with columns open, high, low, close.

        Returns:
            DataFrame containing all price features.
        """
        close = data["close"].astype(float)
        high = data["high"].astype(float)
        low = data["low"].astype(float)
        open_ = data["open"].astype(float)

        features: dict[str, pd.Series] = {}

        # --- Returns ---
        for w in self.return_windows:
            features[f"return_{w}"] = close.pct_change(periods=w)
            features[f"log_return_{w}"] = np.log(close / close.shift(w))

        # --- Z-scores ---
        for w in self.zscore_windows:
            rolling_mean = close.rolling(window=w, min_periods=w).mean()
            rolling_std = close.rolling(window=w, min_periods=w).std()
            features[f"zscore_{w}"] = (close - rolling_mean) / rolling_std

        # --- Momentum ---
        for w in self.momentum_windows:
            features[f"momentum_{w}"] = close / close.shift(w) - 1

        # --- Range features ---
        price_range = high - low
        features["range_pct"] = price_range / close
        # Close position within daily range (0 = at low, 1 = at high)
        features["close_position"] = (close - low) / price_range

        # --- Gap (open vs previous close) ---
        prev_close = close.shift(1)
        features["gap"] = (open_ - prev_close) / prev_close

        # --- Cumulative returns ---
        log_returns_1 = np.log(close / close.shift(1))
        for w in self.cum_return_windows:
            features[f"cum_return_{w}"] = log_returns_1.rolling(
                window=w, min_periods=1
            ).sum()

        result = pd.DataFrame(features, index=data.index)
        return result

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fit(self, data: pd.DataFrame) -> PriceFeatureExtractor:
        """Fit the StandardScaler on training data.

        Args:
            data: OHLCV training DataFrame.

        Returns:
            Self for method chaining.
        """
        logger.info("fitting_price_features", rows=len(data))
        raw = self._compute_features(data)
        if self.scale:
            self._scaler.fit(raw.values)
        self._is_fitted = True
        return self

    def transform(self, data: pd.DataFrame) -> pd.DataFrame:
        """Extract and scale price features.

        Args:
            data: OHLCV DataFrame.

        Returns:
            DataFrame of scaled price features.

        Raises:
            RuntimeError: If called before ``fit()``.
        """
        if not self._is_fitted:
            raise RuntimeError(
                "PriceFeatureExtractor must be fitted before transform(). "
                "Call fit() or fit_transform() first."
            )
        raw = self._compute_features(data)
        if self.scale:
            scaled = self._scaler.transform(raw.values)
            return pd.DataFrame(scaled, columns=self._feature_names, index=data.index)
        return raw

    def feature_names(self) -> List[str]:
        """Return ordered list of feature names.

        Returns:
            List of feature column names.
        """
        return list(self._feature_names)
