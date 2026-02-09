"""Price-indicator divergence detection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import numpy as np
import pandas as pd


@dataclass
class Divergence:
    """A detected divergence between price and an indicator.

    Attributes:
        divergence_type: One of ``"bullish"``, ``"bearish"``,
            ``"hidden_bullish"``, ``"hidden_bearish"``.
        price_start_idx: Index of the first swing point in the price.
        price_end_idx: Index of the second swing point in the price.
        indicator_name: Name of the indicator being compared.
        confidence: Confidence score from 0.0 to 1.0.
    """

    divergence_type: str
    price_start_idx: int
    price_end_idx: int
    indicator_name: str
    confidence: float


class DivergenceDetector:
    """Detect divergences between price and a technical indicator.

    A divergence occurs when price makes a new swing high/low but the
    indicator fails to confirm.  This class detects four types:

    - **Regular bullish**: price lower low, indicator higher low.
    - **Regular bearish**: price higher high, indicator lower high.
    - **Hidden bullish**: price higher low, indicator lower low.
    - **Hidden bearish**: price lower high, indicator higher high.

    Args:
        lookback: Maximum number of bars to look back when pairing
            swing points.
        min_swing_pct: Minimum percentage move to qualify as a swing
            (relative to the local range).
    """

    def __init__(
        self,
        lookback: int = 20,
        min_swing_pct: float = 0.5,
    ) -> None:
        if lookback < 2:
            raise ValueError(f"lookback must be >= 2, got {lookback}")
        if min_swing_pct < 0:
            raise ValueError(
                f"min_swing_pct must be >= 0, got {min_swing_pct}"
            )
        self.lookback = lookback
        self.min_swing_pct = min_swing_pct

    # ------------------------------------------------------------------
    # Swing detection
    # ------------------------------------------------------------------

    @staticmethod
    def _find_swing_highs(series: pd.Series, order: int = 5) -> pd.Series:
        """Find local maxima (swing highs) in a series.

        A swing high at index *i* is a point whose value is greater than
        or equal to all values in the window ``[i - order, i + order]``.

        Args:
            series: Input numeric series.
            order: Number of bars on each side to compare.

        Returns:
            Boolean Series with True at swing high positions.
        """
        result = pd.Series(False, index=series.index)
        values = series.values

        for i in range(order, len(values) - order):
            if np.isnan(values[i]):
                continue
            window_left = values[max(0, i - order) : i]
            window_right = values[i + 1 : i + order + 1]
            if len(window_left) == 0 or len(window_right) == 0:
                continue
            if np.any(np.isnan(window_left)) or np.any(np.isnan(window_right)):
                continue
            if values[i] >= np.max(window_left) and values[i] >= np.max(
                window_right
            ):
                result.iloc[i] = True

        return result

    @staticmethod
    def _find_swing_lows(series: pd.Series, order: int = 5) -> pd.Series:
        """Find local minima (swing lows) in a series.

        A swing low at index *i* is a point whose value is less than
        or equal to all values in the window ``[i - order, i + order]``.

        Args:
            series: Input numeric series.
            order: Number of bars on each side to compare.

        Returns:
            Boolean Series with True at swing low positions.
        """
        result = pd.Series(False, index=series.index)
        values = series.values

        for i in range(order, len(values) - order):
            if np.isnan(values[i]):
                continue
            window_left = values[max(0, i - order) : i]
            window_right = values[i + 1 : i + order + 1]
            if len(window_left) == 0 or len(window_right) == 0:
                continue
            if np.any(np.isnan(window_left)) or np.any(np.isnan(window_right)):
                continue
            if values[i] <= np.min(window_left) and values[i] <= np.min(
                window_right
            ):
                result.iloc[i] = True

        return result

    # ------------------------------------------------------------------
    # Individual divergence types
    # ------------------------------------------------------------------

    def detect_regular_bullish(
        self,
        price: pd.Series,
        indicator: pd.Series,
    ) -> List[Tuple[int, int]]:
        """Detect regular bullish divergence.

        Price makes a lower low while the indicator makes a higher low.

        Args:
            price: Price series.
            indicator: Indicator series (e.g. RSI).

        Returns:
            List of ``(start_idx, end_idx)`` tuples marking divergence
            swing-low pairs.
        """
        order = max(2, min(5, len(price) // 6))
        price_lows = self._find_swing_lows(price, order=order)
        ind_lows = self._find_swing_lows(indicator, order=order)

        price_low_idxs = list(price.index[price_lows])
        ind_low_idxs = list(indicator.index[ind_lows])

        divergences: List[Tuple[int, int]] = []

        for i in range(len(price_low_idxs) - 1):
            idx_a = price_low_idxs[i]
            for j in range(i + 1, len(price_low_idxs)):
                idx_b = price_low_idxs[j]
                if abs(idx_b - idx_a) > self.lookback:
                    break

                # Price makes lower low
                if price.iloc[idx_b] >= price.iloc[idx_a]:
                    continue

                # Find indicator lows near these price lows
                ind_a = self._nearest_swing(ind_low_idxs, idx_a, tolerance=order)
                ind_b = self._nearest_swing(ind_low_idxs, idx_b, tolerance=order)
                if ind_a is None or ind_b is None:
                    continue

                # Indicator makes higher low
                if indicator.iloc[ind_b] > indicator.iloc[ind_a]:
                    divergences.append((idx_a, idx_b))

        return divergences

    def detect_regular_bearish(
        self,
        price: pd.Series,
        indicator: pd.Series,
    ) -> List[Tuple[int, int]]:
        """Detect regular bearish divergence.

        Price makes a higher high while the indicator makes a lower high.

        Args:
            price: Price series.
            indicator: Indicator series.

        Returns:
            List of ``(start_idx, end_idx)`` tuples.
        """
        order = max(2, min(5, len(price) // 6))
        price_highs = self._find_swing_highs(price, order=order)
        ind_highs = self._find_swing_highs(indicator, order=order)

        price_high_idxs = list(price.index[price_highs])
        ind_high_idxs = list(indicator.index[ind_highs])

        divergences: List[Tuple[int, int]] = []

        for i in range(len(price_high_idxs) - 1):
            idx_a = price_high_idxs[i]
            for j in range(i + 1, len(price_high_idxs)):
                idx_b = price_high_idxs[j]
                if abs(idx_b - idx_a) > self.lookback:
                    break

                # Price makes higher high
                if price.iloc[idx_b] <= price.iloc[idx_a]:
                    continue

                # Find indicator highs near these price highs
                ind_a = self._nearest_swing(
                    ind_high_idxs, idx_a, tolerance=order
                )
                ind_b = self._nearest_swing(
                    ind_high_idxs, idx_b, tolerance=order
                )
                if ind_a is None or ind_b is None:
                    continue

                # Indicator makes lower high
                if indicator.iloc[ind_b] < indicator.iloc[ind_a]:
                    divergences.append((idx_a, idx_b))

        return divergences

    def detect_hidden_bullish(
        self,
        price: pd.Series,
        indicator: pd.Series,
    ) -> List[Tuple[int, int]]:
        """Detect hidden bullish divergence.

        Price makes a higher low while the indicator makes a lower low.

        Args:
            price: Price series.
            indicator: Indicator series.

        Returns:
            List of ``(start_idx, end_idx)`` tuples.
        """
        order = max(2, min(5, len(price) // 6))
        price_lows = self._find_swing_lows(price, order=order)
        ind_lows = self._find_swing_lows(indicator, order=order)

        price_low_idxs = list(price.index[price_lows])
        ind_low_idxs = list(indicator.index[ind_lows])

        divergences: List[Tuple[int, int]] = []

        for i in range(len(price_low_idxs) - 1):
            idx_a = price_low_idxs[i]
            for j in range(i + 1, len(price_low_idxs)):
                idx_b = price_low_idxs[j]
                if abs(idx_b - idx_a) > self.lookback:
                    break

                # Price makes higher low
                if price.iloc[idx_b] <= price.iloc[idx_a]:
                    continue

                # Find indicator lows near these price lows
                ind_a = self._nearest_swing(ind_low_idxs, idx_a, tolerance=order)
                ind_b = self._nearest_swing(ind_low_idxs, idx_b, tolerance=order)
                if ind_a is None or ind_b is None:
                    continue

                # Indicator makes lower low
                if indicator.iloc[ind_b] < indicator.iloc[ind_a]:
                    divergences.append((idx_a, idx_b))

        return divergences

    def detect_hidden_bearish(
        self,
        price: pd.Series,
        indicator: pd.Series,
    ) -> List[Tuple[int, int]]:
        """Detect hidden bearish divergence.

        Price makes a lower high while the indicator makes a higher high.

        Args:
            price: Price series.
            indicator: Indicator series.

        Returns:
            List of ``(start_idx, end_idx)`` tuples.
        """
        order = max(2, min(5, len(price) // 6))
        price_highs = self._find_swing_highs(price, order=order)
        ind_highs = self._find_swing_highs(indicator, order=order)

        price_high_idxs = list(price.index[price_highs])
        ind_high_idxs = list(indicator.index[ind_highs])

        divergences: List[Tuple[int, int]] = []

        for i in range(len(price_high_idxs) - 1):
            idx_a = price_high_idxs[i]
            for j in range(i + 1, len(price_high_idxs)):
                idx_b = price_high_idxs[j]
                if abs(idx_b - idx_a) > self.lookback:
                    break

                # Price makes lower high
                if price.iloc[idx_b] >= price.iloc[idx_a]:
                    continue

                # Find indicator highs near these price highs
                ind_a = self._nearest_swing(
                    ind_high_idxs, idx_a, tolerance=order
                )
                ind_b = self._nearest_swing(
                    ind_high_idxs, idx_b, tolerance=order
                )
                if ind_a is None or ind_b is None:
                    continue

                # Indicator makes higher high
                if indicator.iloc[ind_b] > indicator.iloc[ind_a]:
                    divergences.append((idx_a, idx_b))

        return divergences

    # ------------------------------------------------------------------
    # Aggregate
    # ------------------------------------------------------------------

    def detect(
        self,
        price: pd.Series,
        indicator: pd.Series,
        indicator_name: str = "indicator",
    ) -> List[Divergence]:
        """Detect all divergences between price and indicator.

        Args:
            price: Price series.
            indicator: Indicator series (must be same length as price).
            indicator_name: Label for the indicator (used in output).

        Returns:
            List of :class:`Divergence` instances sorted by end index.

        Raises:
            ValueError: If series lengths do not match.
        """
        if len(price) != len(indicator):
            raise ValueError(
                f"price length ({len(price)}) != indicator length "
                f"({len(indicator)})"
            )

        results: List[Divergence] = []

        for start, end in self.detect_regular_bullish(price, indicator):
            results.append(
                Divergence(
                    divergence_type="bullish",
                    price_start_idx=start,
                    price_end_idx=end,
                    indicator_name=indicator_name,
                    confidence=0.7,
                )
            )

        for start, end in self.detect_regular_bearish(price, indicator):
            results.append(
                Divergence(
                    divergence_type="bearish",
                    price_start_idx=start,
                    price_end_idx=end,
                    indicator_name=indicator_name,
                    confidence=0.7,
                )
            )

        for start, end in self.detect_hidden_bullish(price, indicator):
            results.append(
                Divergence(
                    divergence_type="hidden_bullish",
                    price_start_idx=start,
                    price_end_idx=end,
                    indicator_name=indicator_name,
                    confidence=0.6,
                )
            )

        for start, end in self.detect_hidden_bearish(price, indicator):
            results.append(
                Divergence(
                    divergence_type="hidden_bearish",
                    price_start_idx=start,
                    price_end_idx=end,
                    indicator_name=indicator_name,
                    confidence=0.6,
                )
            )

        results.sort(key=lambda d: d.price_end_idx)
        return results

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _nearest_swing(
        swing_idxs: List[int],
        target: int,
        tolerance: int,
    ) -> int | None:
        """Find the swing index closest to *target* within *tolerance*.

        Args:
            swing_idxs: Sorted list of swing point indices.
            target: The index to search around.
            tolerance: Maximum distance.

        Returns:
            The nearest swing index, or ``None`` if none is within
            tolerance.
        """
        best: int | None = None
        best_dist = tolerance + 1
        for idx in swing_idxs:
            dist = abs(idx - target)
            if dist < best_dist:
                best_dist = dist
                best = idx
        if best is not None and best_dist <= tolerance:
            return best
        return None

    def __repr__(self) -> str:
        return (
            f"<DivergenceDetector(lookback={self.lookback}, "
            f"min_swing_pct={self.min_swing_pct})>"
        )
