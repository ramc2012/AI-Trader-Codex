"""Market Regime Detection.

Classifies the current market regime to enable adaptive strategy selection.
Uses ADX (trend strength), ATR/historical volatility, and Bollinger Band
width to determine whether the market is trending, range-bound, or volatile.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd

from src.utils.logger import get_logger

logger = get_logger(__name__)


class MarketRegime(str, Enum):
    """Classified market regime states."""

    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGE_BOUND = "range_bound"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"
    UNKNOWN = "unknown"


@dataclass
class RegimeState:
    """Current market regime with supporting metrics."""

    regime: MarketRegime
    confidence: float  # 0.0 - 1.0
    adx: float
    atr_pct: float  # ATR as percentage of price
    bb_width_pct: float  # Bollinger Band width as percentage
    trend_direction: str  # "up", "down", "flat"
    ema_spread_pct: float  # 50/200 EMA spread as percentage

    def to_dict(self) -> dict[str, Any]:
        return {
            "regime": self.regime.value,
            "confidence": round(self.confidence, 2),
            "adx": round(self.adx, 2),
            "atr_pct": round(self.atr_pct, 3),
            "bb_width_pct": round(self.bb_width_pct, 3),
            "trend_direction": self.trend_direction,
            "ema_spread_pct": round(self.ema_spread_pct, 3),
        }

    @property
    def is_trending(self) -> bool:
        return self.regime in (MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN)

    @property
    def is_volatile(self) -> bool:
        return self.regime == MarketRegime.HIGH_VOLATILITY

    @property
    def favors_scalping(self) -> bool:
        """Scalping works best in range-bound or low-volatility regimes."""
        return self.regime in (MarketRegime.RANGE_BOUND, MarketRegime.LOW_VOLATILITY)

    @property
    def favors_swing(self) -> bool:
        """Swing trading works best in trending regimes."""
        return self.is_trending

    @property
    def favors_positional(self) -> bool:
        """Positional trading works in strong trends."""
        return self.is_trending and self.confidence >= 0.7


class RegimeDetector:
    """Market regime classifier using multiple technical indicators.

    Args:
        adx_period: Period for ADX calculation.
        atr_period: Period for ATR calculation.
        bb_period: Period for Bollinger Band calculation.
        bb_std: Standard deviation multiplier for Bollinger Bands.
        ema_fast: Fast EMA period for trend detection.
        ema_slow: Slow EMA period for trend detection.
        adx_trending_threshold: ADX level above which market is trending.
        adx_strong_threshold: ADX level for strong trend.
        vol_high_threshold: ATR percentile for high volatility regime.
        vol_low_threshold: ATR percentile for low volatility regime.
    """

    def __init__(
        self,
        adx_period: int = 14,
        atr_period: int = 14,
        bb_period: int = 20,
        bb_std: float = 2.0,
        ema_fast: int = 50,
        ema_slow: int = 200,
        adx_trending_threshold: float = 25.0,
        adx_strong_threshold: float = 40.0,
        vol_high_threshold: float = 75.0,
        vol_low_threshold: float = 25.0,
    ) -> None:
        self.adx_period = adx_period
        self.atr_period = atr_period
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.adx_trending_threshold = adx_trending_threshold
        self.adx_strong_threshold = adx_strong_threshold
        self.vol_high_threshold = vol_high_threshold
        self.vol_low_threshold = vol_low_threshold

    def detect(self, data: pd.DataFrame) -> RegimeState:
        """Classify the current market regime from OHLCV data.

        Args:
            data: DataFrame with columns: open, high, low, close, volume.
                  Must have at least `ema_slow + 10` rows.

        Returns:
            RegimeState with classified regime and supporting metrics.
        """
        min_rows = max(self.ema_slow, self.adx_period * 3, self.bb_period) + 10
        if data is None or len(data) < min_rows:
            return RegimeState(
                regime=MarketRegime.UNKNOWN,
                confidence=0.0,
                adx=0.0,
                atr_pct=0.0,
                bb_width_pct=0.0,
                trend_direction="flat",
                ema_spread_pct=0.0,
            )

        df = data.copy()

        # Calculate ADX
        adx = self._calculate_adx(df)

        # Calculate ATR as percentage of price
        atr = self._calculate_atr(df)
        atr_pct = (atr / float(df["close"].iloc[-1])) * 100 if float(df["close"].iloc[-1]) > 0 else 0.0

        # ATR percentile (relative to recent history)
        atr_series = self._atr_series(df)
        atr_percentile = self._percentile_rank(atr_series, atr)

        # Bollinger Band width
        bb_width_pct = self._bb_width(df)

        # EMA trend
        ema_fast = df["close"].ewm(span=self.ema_fast, adjust=False).mean().iloc[-1]
        ema_slow = df["close"].ewm(span=self.ema_slow, adjust=False).mean().iloc[-1]
        ema_spread_pct = ((ema_fast - ema_slow) / ema_slow) * 100 if ema_slow > 0 else 0.0

        # Determine trend direction
        if ema_fast > ema_slow and float(df["close"].iloc[-1]) > ema_fast:
            trend_direction = "up"
        elif ema_fast < ema_slow and float(df["close"].iloc[-1]) < ema_fast:
            trend_direction = "down"
        else:
            trend_direction = "flat"

        # Classify regime
        regime, confidence = self._classify(
            adx=adx,
            atr_percentile=atr_percentile,
            bb_width_pct=bb_width_pct,
            trend_direction=trend_direction,
            ema_spread_pct=ema_spread_pct,
        )

        state = RegimeState(
            regime=regime,
            confidence=confidence,
            adx=adx,
            atr_pct=atr_pct,
            bb_width_pct=bb_width_pct,
            trend_direction=trend_direction,
            ema_spread_pct=ema_spread_pct,
        )

        logger.debug("regime_detected", **state.to_dict())
        return state

    def _classify(
        self,
        adx: float,
        atr_percentile: float,
        bb_width_pct: float,
        trend_direction: str,
        ema_spread_pct: float,
    ) -> tuple[MarketRegime, float]:
        """Classify regime from indicator values."""

        # High volatility takes precedence
        if atr_percentile >= self.vol_high_threshold and bb_width_pct > 4.0:
            confidence = min(atr_percentile / 100.0, 0.95)
            return MarketRegime.HIGH_VOLATILITY, confidence

        # Strong trend
        if adx >= self.adx_trending_threshold:
            confidence = min(adx / 60.0, 0.95)
            if trend_direction == "up":
                return MarketRegime.TRENDING_UP, confidence
            elif trend_direction == "down":
                return MarketRegime.TRENDING_DOWN, confidence
            else:
                # ADX high but no clear direction — transitional
                return MarketRegime.RANGE_BOUND, confidence * 0.5

        # Low volatility
        if atr_percentile <= self.vol_low_threshold and bb_width_pct < 2.0:
            confidence = 1.0 - (atr_percentile / 100.0)
            return MarketRegime.LOW_VOLATILITY, min(confidence, 0.9)

        # Default: range-bound
        confidence = max(0.3, 1.0 - (adx / self.adx_trending_threshold))
        return MarketRegime.RANGE_BOUND, min(confidence, 0.85)

    def _calculate_adx(self, df: pd.DataFrame) -> float:
        """Calculate current ADX value."""
        high = df["high"]
        low = df["low"]
        close = df["close"]

        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)

        atr = tr.ewm(span=self.adx_period, adjust=False).mean()
        plus_di = 100 * (plus_dm.ewm(span=self.adx_period, adjust=False).mean() / atr.replace(0, float("nan")))
        minus_di = 100 * (minus_dm.ewm(span=self.adx_period, adjust=False).mean() / atr.replace(0, float("nan")))

        dx = (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, float("nan"))) * 100
        adx = dx.ewm(span=self.adx_period, adjust=False).mean()

        return float(adx.iloc[-1]) if not pd.isna(adx.iloc[-1]) else 0.0

    def _calculate_atr(self, df: pd.DataFrame) -> float:
        """Calculate current ATR value."""
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ], axis=1).max(axis=1)
        atr = tr.ewm(span=self.atr_period, adjust=False).mean()
        return float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else 0.0

    def _atr_series(self, df: pd.DataFrame) -> pd.Series:
        """Full ATR series for percentile calculation."""
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ], axis=1).max(axis=1)
        return tr.ewm(span=self.atr_period, adjust=False).mean()

    def _bb_width(self, df: pd.DataFrame) -> float:
        """Bollinger Band width as percentage of middle band."""
        ma = df["close"].rolling(window=self.bb_period).mean()
        std = df["close"].rolling(window=self.bb_period).std()
        upper = ma + self.bb_std * std
        lower = ma - self.bb_std * std
        width = ((upper - lower) / ma) * 100
        val = float(width.iloc[-1])
        return val if not pd.isna(val) else 0.0

    @staticmethod
    def _percentile_rank(series: pd.Series, value: float) -> float:
        """Calculate percentile rank of a value within a series."""
        clean = series.dropna()
        if len(clean) == 0:
            return 50.0
        return float((clean < value).sum() / len(clean) * 100)
