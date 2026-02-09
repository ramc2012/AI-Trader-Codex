"""Candlestick pattern detection for OHLC data."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List

import numpy as np
import pandas as pd


class PatternType(Enum):
    """Type of candlestick pattern signal."""

    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass
class CandlestickPattern:
    """A detected candlestick pattern.

    Attributes:
        name: Human-readable pattern name.
        pattern_type: Whether the pattern is bullish, bearish, or neutral.
        index: Bar index where the pattern was detected (last candle of pattern).
        confidence: Confidence score from 0.0 to 1.0.
        description: Short explanation of the pattern.
    """

    name: str
    pattern_type: PatternType
    index: int
    confidence: float
    description: str


class CandlestickDetector:
    """Detect candlestick patterns in OHLC data.

    The detector operates on a DataFrame that must contain columns:
    ``open``, ``high``, ``low``, ``close``.

    Args:
        body_threshold: Minimum body-to-range ratio for a candle to be
            considered a non-doji.  Values below this ratio are treated
            as doji candles.
    """

    def __init__(self, body_threshold: float = 0.01) -> None:
        if body_threshold < 0:
            raise ValueError(
                f"body_threshold must be >= 0, got {body_threshold}"
            )
        self.body_threshold = body_threshold

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    @staticmethod
    def _body_size(data: pd.DataFrame) -> pd.Series:
        """Absolute body size: abs(close - open)."""
        return (data["close"] - data["open"]).abs()

    @staticmethod
    def _upper_shadow(data: pd.DataFrame) -> pd.Series:
        """Upper shadow length: high - max(open, close)."""
        return data["high"] - np.maximum(data["open"], data["close"])

    @staticmethod
    def _lower_shadow(data: pd.DataFrame) -> pd.Series:
        """Lower shadow length: min(open, close) - low."""
        return np.minimum(data["open"], data["close"]) - data["low"]

    @staticmethod
    def _is_bullish(data: pd.DataFrame) -> pd.Series:
        """Boolean Series: True where close > open."""
        return data["close"] > data["open"]

    @staticmethod
    def _is_bearish(data: pd.DataFrame) -> pd.Series:
        """Boolean Series: True where close < open."""
        return data["close"] < data["open"]

    @staticmethod
    def _body_midpoint(data: pd.DataFrame) -> pd.Series:
        """Midpoint of the candle body: (open + close) / 2."""
        return (data["open"] + data["close"]) / 2.0

    def _candle_range(self, data: pd.DataFrame) -> pd.Series:
        """Total candle range: high - low (floored to avoid zero-div)."""
        return (data["high"] - data["low"]).replace(0.0, np.nan)

    # ------------------------------------------------------------------
    # Single-candle patterns
    # ------------------------------------------------------------------

    def detect_doji(self, data: pd.DataFrame) -> pd.Series:
        """Detect doji candles (very small body relative to range).

        Args:
            data: OHLC DataFrame.

        Returns:
            Boolean Series -- True where a doji is detected.
        """
        body = self._body_size(data)
        candle_range = self._candle_range(data)
        ratio = body / candle_range
        return ratio.lt(self.body_threshold).fillna(False)

    def detect_hammer(self, data: pd.DataFrame) -> pd.Series:
        """Detect hammer candles.

        A hammer has a small body near the top of the range, a lower
        shadow at least 2x the body, and a small upper shadow.

        Args:
            data: OHLC DataFrame.

        Returns:
            Boolean Series -- True where a hammer is detected.
        """
        body = self._body_size(data)
        upper = self._upper_shadow(data)
        lower = self._lower_shadow(data)
        candle_range = self._candle_range(data)

        small_body = body / candle_range < 0.35
        long_lower = lower >= 2.0 * body
        small_upper = upper <= body * 0.5

        return (small_body & long_lower & small_upper).fillna(False)

    def detect_shooting_star(self, data: pd.DataFrame) -> pd.Series:
        """Detect shooting star candles.

        A shooting star has a small body near the bottom of the range,
        an upper shadow at least 2x the body, and a small lower shadow.

        Args:
            data: OHLC DataFrame.

        Returns:
            Boolean Series -- True where a shooting star is detected.
        """
        body = self._body_size(data)
        upper = self._upper_shadow(data)
        lower = self._lower_shadow(data)
        candle_range = self._candle_range(data)

        small_body = body / candle_range < 0.35
        long_upper = upper >= 2.0 * body
        small_lower = lower <= body * 0.5

        return (small_body & long_upper & small_lower).fillna(False)

    def detect_spinning_top(self, data: pd.DataFrame) -> pd.Series:
        """Detect spinning top candles.

        A spinning top has a small body with roughly equal upper and
        lower shadows, both of which are significant.

        Args:
            data: OHLC DataFrame.

        Returns:
            Boolean Series -- True where a spinning top is detected.
        """
        body = self._body_size(data)
        upper = self._upper_shadow(data)
        lower = self._lower_shadow(data)
        candle_range = self._candle_range(data)

        small_body = body / candle_range < 0.35
        significant_shadows = (upper > body * 0.5) & (lower > body * 0.5)
        # Shadows roughly balanced: neither is more than 3x the other
        shadow_max = np.maximum(upper, lower)
        shadow_min = np.minimum(upper, lower).replace(0.0, np.nan)
        balanced = shadow_max / shadow_min < 3.0

        return (small_body & significant_shadows & balanced).fillna(False)

    # ------------------------------------------------------------------
    # Two-candle patterns
    # ------------------------------------------------------------------

    def detect_engulfing(self, data: pd.DataFrame) -> pd.Series:
        """Detect bullish and bearish engulfing patterns.

        Args:
            data: OHLC DataFrame.

        Returns:
            Integer Series: +1 for bullish engulfing, -1 for bearish
            engulfing, 0 for none.  Index 0 is always 0 (needs prior bar).
        """
        result = pd.Series(0, index=data.index, dtype=int)
        if len(data) < 2:
            return result

        prev_open = data["open"].shift(1)
        prev_close = data["close"].shift(1)
        curr_open = data["open"]
        curr_close = data["close"]

        prev_bearish = prev_close < prev_open
        prev_bullish = prev_close > prev_open
        curr_bullish = curr_close > curr_open
        curr_bearish = curr_close < curr_open

        # Bullish engulfing: previous red, current green engulfs
        bull_engulf = (
            prev_bearish
            & curr_bullish
            & (curr_open <= prev_close)
            & (curr_close >= prev_open)
        )

        # Bearish engulfing: previous green, current red engulfs
        bear_engulf = (
            prev_bullish
            & curr_bearish
            & (curr_open >= prev_close)
            & (curr_close <= prev_open)
        )

        result = result.where(~bull_engulf, 1)
        result = result.where(~bear_engulf, -1)
        return result

    def detect_harami(self, data: pd.DataFrame) -> pd.Series:
        """Detect bullish and bearish harami patterns.

        Args:
            data: OHLC DataFrame.

        Returns:
            Integer Series: +1 for bullish harami, -1 for bearish
            harami, 0 for none.
        """
        result = pd.Series(0, index=data.index, dtype=int)
        if len(data) < 2:
            return result

        prev_open = data["open"].shift(1)
        prev_close = data["close"].shift(1)
        curr_open = data["open"]
        curr_close = data["close"]

        prev_body_high = np.maximum(prev_open, prev_close)
        prev_body_low = np.minimum(prev_open, prev_close)
        curr_body_high = np.maximum(curr_open, curr_close)
        curr_body_low = np.minimum(curr_open, curr_close)

        prev_bearish = prev_close < prev_open
        prev_bullish = prev_close > prev_open

        # Current body is within previous body
        inside = (curr_body_high <= prev_body_high) & (
            curr_body_low >= prev_body_low
        )

        # Bullish harami: previous red, current (smaller) inside
        bull_harami = prev_bearish & inside & (curr_close >= curr_open)
        # Bearish harami: previous green, current (smaller) inside
        bear_harami = prev_bullish & inside & (curr_close <= curr_open)

        result = result.where(~bull_harami, 1)
        result = result.where(~bear_harami, -1)
        return result

    # ------------------------------------------------------------------
    # Three-candle patterns
    # ------------------------------------------------------------------

    def detect_morning_star(self, data: pd.DataFrame) -> pd.Series:
        """Detect morning star pattern (bullish reversal).

        Three-candle pattern: big red candle, small body (gap down),
        big green candle closing above the midpoint of the first candle.

        Args:
            data: OHLC DataFrame.

        Returns:
            Boolean Series -- True at the third candle of a morning star.
        """
        result = pd.Series(False, index=data.index)
        if len(data) < 3:
            return result

        body = self._body_size(data)
        candle_range = self._candle_range(data)
        body_ratio = body / candle_range

        # First candle: large bearish
        first_bearish = data["close"].shift(2) < data["open"].shift(2)
        first_large = body.shift(2) / candle_range.shift(2) > 0.5

        # Second candle: small body
        second_small = body_ratio.shift(1) < 0.35

        # Third candle: large bullish closing above midpoint of first
        third_bullish = data["close"] > data["open"]
        third_large = body_ratio > 0.5
        first_midpoint = (data["open"].shift(2) + data["close"].shift(2)) / 2.0
        third_above_mid = data["close"] > first_midpoint

        pattern = (
            first_bearish
            & first_large
            & second_small
            & third_bullish
            & third_large
            & third_above_mid
        )

        return pattern.fillna(False)

    def detect_evening_star(self, data: pd.DataFrame) -> pd.Series:
        """Detect evening star pattern (bearish reversal).

        Three-candle pattern: big green candle, small body (gap up),
        big red candle closing below the midpoint of the first candle.

        Args:
            data: OHLC DataFrame.

        Returns:
            Boolean Series -- True at the third candle of an evening star.
        """
        result = pd.Series(False, index=data.index)
        if len(data) < 3:
            return result

        body = self._body_size(data)
        candle_range = self._candle_range(data)
        body_ratio = body / candle_range

        # First candle: large bullish
        first_bullish = data["close"].shift(2) > data["open"].shift(2)
        first_large = body.shift(2) / candle_range.shift(2) > 0.5

        # Second candle: small body
        second_small = body_ratio.shift(1) < 0.35

        # Third candle: large bearish closing below midpoint of first
        third_bearish = data["close"] < data["open"]
        third_large = body_ratio > 0.5
        first_midpoint = (data["open"].shift(2) + data["close"].shift(2)) / 2.0
        third_below_mid = data["close"] < first_midpoint

        pattern = (
            first_bullish
            & first_large
            & second_small
            & third_bearish
            & third_large
            & third_below_mid
        )

        return pattern.fillna(False)

    def detect_three_white_soldiers(self, data: pd.DataFrame) -> pd.Series:
        """Detect three white soldiers (bullish continuation).

        Three consecutive green candles, each closing higher than the
        previous, each opening within the body of the previous candle.

        Args:
            data: OHLC DataFrame.

        Returns:
            Boolean Series -- True at the third candle of the pattern.
        """
        result = pd.Series(False, index=data.index)
        if len(data) < 3:
            return result

        bullish = self._is_bullish(data)

        # All three candles are bullish
        three_bullish = bullish & bullish.shift(1) & bullish.shift(2)

        # Each closes higher than the previous
        higher_close = (
            (data["close"] > data["close"].shift(1))
            & (data["close"].shift(1) > data["close"].shift(2))
        )

        # Each opens within the body of the previous candle
        opens_in_prev = (
            (data["open"] >= data["open"].shift(1))
            & (data["open"] <= data["close"].shift(1))
            & (data["open"].shift(1) >= data["open"].shift(2))
            & (data["open"].shift(1) <= data["close"].shift(2))
        )

        pattern = three_bullish & higher_close & opens_in_prev
        return pattern.fillna(False)

    def detect_three_black_crows(self, data: pd.DataFrame) -> pd.Series:
        """Detect three black crows (bearish continuation).

        Three consecutive red candles, each closing lower than the
        previous, each opening within the body of the previous candle.

        Args:
            data: OHLC DataFrame.

        Returns:
            Boolean Series -- True at the third candle of the pattern.
        """
        result = pd.Series(False, index=data.index)
        if len(data) < 3:
            return result

        bearish = self._is_bearish(data)

        # All three candles are bearish
        three_bearish = bearish & bearish.shift(1) & bearish.shift(2)

        # Each closes lower than the previous
        lower_close = (
            (data["close"] < data["close"].shift(1))
            & (data["close"].shift(1) < data["close"].shift(2))
        )

        # Each opens within the body of the previous candle (for bearish:
        # body top is open, body bottom is close)
        opens_in_prev = (
            (data["open"] <= data["open"].shift(1))
            & (data["open"] >= data["close"].shift(1))
            & (data["open"].shift(1) <= data["open"].shift(2))
            & (data["open"].shift(1) >= data["close"].shift(2))
        )

        pattern = three_bearish & lower_close & opens_in_prev
        return pattern.fillna(False)

    # ------------------------------------------------------------------
    # Aggregate detection
    # ------------------------------------------------------------------

    def detect_all(self, data: pd.DataFrame) -> List[CandlestickPattern]:
        """Detect all supported candlestick patterns in the data.

        Args:
            data: OHLC DataFrame with columns ``open``, ``high``,
                ``low``, ``close``.

        Returns:
            List of :class:`CandlestickPattern` instances sorted by
            bar index.

        Raises:
            ValueError: If required columns are missing.
        """
        required = {"open", "high", "low", "close"}
        missing = required - set(data.columns)
        if missing:
            raise ValueError(f"DataFrame missing columns: {missing}")

        patterns: List[CandlestickPattern] = []

        # --- Single candle ---
        doji = self.detect_doji(data)
        for idx in data.index[doji]:
            patterns.append(
                CandlestickPattern(
                    name="Doji",
                    pattern_type=PatternType.NEUTRAL,
                    index=idx,
                    confidence=0.6,
                    description="Indecision candle with very small body.",
                )
            )

        hammer = self.detect_hammer(data)
        for idx in data.index[hammer]:
            patterns.append(
                CandlestickPattern(
                    name="Hammer",
                    pattern_type=PatternType.BULLISH,
                    index=idx,
                    confidence=0.65,
                    description="Small body at top with long lower shadow.",
                )
            )

        shooting = self.detect_shooting_star(data)
        for idx in data.index[shooting]:
            patterns.append(
                CandlestickPattern(
                    name="Shooting Star",
                    pattern_type=PatternType.BEARISH,
                    index=idx,
                    confidence=0.65,
                    description="Small body at bottom with long upper shadow.",
                )
            )

        spinning = self.detect_spinning_top(data)
        for idx in data.index[spinning]:
            patterns.append(
                CandlestickPattern(
                    name="Spinning Top",
                    pattern_type=PatternType.NEUTRAL,
                    index=idx,
                    confidence=0.5,
                    description="Small body with balanced upper and lower shadows.",
                )
            )

        # --- Two candle ---
        engulfing = self.detect_engulfing(data)
        for idx in data.index[engulfing == 1]:
            patterns.append(
                CandlestickPattern(
                    name="Bullish Engulfing",
                    pattern_type=PatternType.BULLISH,
                    index=idx,
                    confidence=0.75,
                    description="Current green candle engulfs previous red candle.",
                )
            )
        for idx in data.index[engulfing == -1]:
            patterns.append(
                CandlestickPattern(
                    name="Bearish Engulfing",
                    pattern_type=PatternType.BEARISH,
                    index=idx,
                    confidence=0.75,
                    description="Current red candle engulfs previous green candle.",
                )
            )

        harami = self.detect_harami(data)
        for idx in data.index[harami == 1]:
            patterns.append(
                CandlestickPattern(
                    name="Bullish Harami",
                    pattern_type=PatternType.BULLISH,
                    index=idx,
                    confidence=0.6,
                    description="Small green candle inside previous red candle body.",
                )
            )
        for idx in data.index[harami == -1]:
            patterns.append(
                CandlestickPattern(
                    name="Bearish Harami",
                    pattern_type=PatternType.BEARISH,
                    index=idx,
                    confidence=0.6,
                    description="Small red candle inside previous green candle body.",
                )
            )

        # --- Three candle ---
        morning = self.detect_morning_star(data)
        for idx in data.index[morning]:
            patterns.append(
                CandlestickPattern(
                    name="Morning Star",
                    pattern_type=PatternType.BULLISH,
                    index=idx,
                    confidence=0.8,
                    description="Three-candle bullish reversal pattern.",
                )
            )

        evening = self.detect_evening_star(data)
        for idx in data.index[evening]:
            patterns.append(
                CandlestickPattern(
                    name="Evening Star",
                    pattern_type=PatternType.BEARISH,
                    index=idx,
                    confidence=0.8,
                    description="Three-candle bearish reversal pattern.",
                )
            )

        soldiers = self.detect_three_white_soldiers(data)
        for idx in data.index[soldiers]:
            patterns.append(
                CandlestickPattern(
                    name="Three White Soldiers",
                    pattern_type=PatternType.BULLISH,
                    index=idx,
                    confidence=0.8,
                    description="Three consecutive green candles closing higher.",
                )
            )

        crows = self.detect_three_black_crows(data)
        for idx in data.index[crows]:
            patterns.append(
                CandlestickPattern(
                    name="Three Black Crows",
                    pattern_type=PatternType.BEARISH,
                    index=idx,
                    confidence=0.8,
                    description="Three consecutive red candles closing lower.",
                )
            )

        # Sort by bar index
        patterns.sort(key=lambda p: p.index)
        return patterns

    def __repr__(self) -> str:
        return f"<CandlestickDetector(body_threshold={self.body_threshold})>"
