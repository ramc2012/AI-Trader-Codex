"""Technical indicator-based feature extraction.

Wraps the existing indicator library (SMA, EMA, RSI, MACD,
BollingerBands, ATR) to produce normalized features suitable
for ML models.
"""

from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

from src.analysis.indicators.momentum import (
    CCI,
    MACD,
    ROC,
    RSI,
    StochasticOscillator,
    UltimateOscillator,
    WilliamsR,
)
from src.analysis.indicators.moving_averages import EMA, SMA
from src.analysis.indicators.trend import ADX
from src.analysis.indicators.volatility import (
    ATR,
    BollingerBands,
    DonchianChannels,
    KeltnerChannels,
    RollingStdDev,
)
from src.analysis.indicators.volume import ChaikinMoneyFlow
from src.ml.features.base import FeatureExtractor
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Default periods for each indicator group.
_SMA_FAST_SLOW_PAIRS: List[tuple[int, int]] = [(5, 20), (10, 50)]
_EMA_PERIODS: List[int] = [9, 21, 50]
_RSI_PERIODS: List[int] = [7, 14, 21]


class TechnicalFeatureExtractor(FeatureExtractor):
    """Extract features derived from technical indicators.

    Features produced:
        * SMA crossover signals (binary 1/0)
        * Normalised EMA distance: (close - ema) / ema
        * RSI values for multiple periods
        * MACD histogram
        * Bollinger Band position: (close - lower) / (upper - lower)
        * Normalised ATR: atr / close

    All indicator computations delegate to the classes in
    ``src.analysis.indicators``.

    Args:
        sma_pairs: Pairs of (fast, slow) SMA periods for crossover signals.
        ema_periods: EMA periods for normalised distance features.
        rsi_periods: RSI lookback periods.
    """

    def __init__(
        self,
        sma_pairs: List[tuple[int, int]] | None = None,
        ema_periods: List[int] | None = None,
        rsi_periods: List[int] | None = None,
    ) -> None:
        super().__init__(name="TechnicalFeatures")
        self.sma_pairs = sma_pairs or list(_SMA_FAST_SLOW_PAIRS)
        self.ema_periods = ema_periods or list(_EMA_PERIODS)
        self.rsi_periods = rsi_periods or list(_RSI_PERIODS)
        self._feature_names: List[str] = self._build_feature_names()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_feature_names(self) -> List[str]:
        """Build the ordered list of feature column names."""
        names: List[str] = []

        for fast, slow in self.sma_pairs:
            names.append(f"sma_cross_{fast}_{slow}")

        for p in self.ema_periods:
            names.append(f"ema_norm_{p}")

        for p in self.rsi_periods:
            names.append(f"rsi_{p}")

        names.append("macd_histogram")
        names.append("bb_position")
        names.append("atr_norm")
        names.append("adx")
        names.append("stoch_k")
        names.append("stoch_d")
        names.append("cci")
        names.append("williams_r")
        names.append("roc_12")
        names.append("ultimate_oscillator")
        names.append("keltner_position")
        names.append("donchian_width")
        names.append("stddev_20")
        names.append("cmf")

        return names

    def _compute_features(self, data: pd.DataFrame) -> pd.DataFrame:
        """Compute technical features from OHLCV data.

        Args:
            data: DataFrame with columns open, high, low, close, volume.

        Returns:
            DataFrame containing all technical features.
        """
        close = data["close"].astype(float)
        high = data["high"].astype(float)
        low = data["low"].astype(float)

        features: dict[str, pd.Series] = {}

        # --- SMA crossover signals ---
        for fast, slow in self.sma_pairs:
            sma_fast = SMA(period=fast).calculate(close)
            sma_slow = SMA(period=slow).calculate(close)
            features[f"sma_cross_{fast}_{slow}"] = (
                (sma_fast > sma_slow).astype(float)
            )

        # --- Normalised EMA distance ---
        for p in self.ema_periods:
            ema_val = EMA(period=p).calculate(close)
            features[f"ema_norm_{p}"] = (close - ema_val) / ema_val

        # --- RSI ---
        for p in self.rsi_periods:
            features[f"rsi_{p}"] = RSI(period=p).calculate(close)

        # --- MACD histogram ---
        macd_df = MACD().calculate(close)
        features["macd_histogram"] = macd_df["histogram"]

        # --- Bollinger Band position ---
        bb_df = BollingerBands().calculate(close)
        bb_range = bb_df["upper"] - bb_df["lower"]
        features["bb_position"] = (close - bb_df["lower"]) / bb_range

        # --- Normalised ATR ---
        atr_val = ATR().calculate(close, high=high, low=low)
        features["atr_norm"] = atr_val / close

        # --- Trend strength ---
        adx_df = ADX().calculate(data)
        features["adx"] = adx_df["adx"]

        # --- Additional momentum indicators ---
        stoch_df = StochasticOscillator().calculate(data)
        features["stoch_k"] = stoch_df["k"]
        features["stoch_d"] = stoch_df["d"]
        features["cci"] = CCI().calculate(data)
        features["williams_r"] = WilliamsR().calculate(data)
        features["roc_12"] = ROC(period=12).calculate(close)
        features["ultimate_oscillator"] = UltimateOscillator().calculate(data)

        # --- Channel and volatility enrichments ---
        keltner_df = KeltnerChannels().calculate(data)
        keltner_range = (keltner_df["upper"] - keltner_df["lower"]).replace(0, np.nan)
        features["keltner_position"] = (close - keltner_df["lower"]) / keltner_range
        features["donchian_width"] = DonchianChannels().calculate(data)["width"]
        features["stddev_20"] = RollingStdDev(period=20).calculate(close)

        # --- Volume pressure ---
        features["cmf"] = ChaikinMoneyFlow(period=20).calculate(data)

        result = pd.DataFrame(features, index=data.index)
        return result

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fit(self, data: pd.DataFrame) -> TechnicalFeatureExtractor:
        """Fit the extractor.

        Technical features are stateless (no learned parameters),
        so this simply marks the extractor as fitted.

        Args:
            data: OHLCV training DataFrame.

        Returns:
            Self for method chaining.
        """
        logger.info("fitting_technical_features", rows=len(data))
        self._is_fitted = True
        return self

    def transform(self, data: pd.DataFrame) -> pd.DataFrame:
        """Extract technical features.

        Args:
            data: OHLCV DataFrame.

        Returns:
            DataFrame of technical features.

        Raises:
            RuntimeError: If called before ``fit()``.
        """
        if not self._is_fitted:
            raise RuntimeError(
                "TechnicalFeatureExtractor must be fitted before transform(). "
                "Call fit() or fit_transform() first."
            )
        return self._compute_features(data)

    def feature_names(self) -> List[str]:
        """Return ordered list of feature names.

        Returns:
            List of feature column names.
        """
        return list(self._feature_names)
