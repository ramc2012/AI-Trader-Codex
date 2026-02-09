"""Tests for the DivergenceDetector and Divergence dataclass."""

import numpy as np
import pandas as pd
import pytest

from src.analysis.patterns.divergence import Divergence, DivergenceDetector


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def detector() -> DivergenceDetector:
    """Standard divergence detector."""
    return DivergenceDetector(lookback=20, min_swing_pct=0.5)


# =========================================================================
# Divergence dataclass
# =========================================================================


class TestDivergenceDataclass:
    def test_fields_correct(self) -> None:
        d = Divergence(
            divergence_type="bullish",
            price_start_idx=10,
            price_end_idx=20,
            indicator_name="RSI",
            confidence=0.7,
        )
        assert d.divergence_type == "bullish"
        assert d.price_start_idx == 10
        assert d.price_end_idx == 20
        assert d.indicator_name == "RSI"
        assert d.confidence == 0.7

    def test_all_divergence_types(self) -> None:
        for dtype in ["bullish", "bearish", "hidden_bullish", "hidden_bearish"]:
            d = Divergence(
                divergence_type=dtype,
                price_start_idx=0,
                price_end_idx=1,
                indicator_name="test",
                confidence=0.5,
            )
            assert d.divergence_type == dtype


# =========================================================================
# Constructor validation
# =========================================================================


class TestDetectorInit:
    def test_invalid_lookback(self) -> None:
        with pytest.raises(ValueError, match="lookback must be >= 2"):
            DivergenceDetector(lookback=1)

    def test_invalid_min_swing_pct(self) -> None:
        with pytest.raises(ValueError, match="min_swing_pct must be >= 0"):
            DivergenceDetector(min_swing_pct=-0.1)


# =========================================================================
# _find_swing_highs / _find_swing_lows
# =========================================================================


class TestSwingDetection:
    def test_find_swing_highs(self) -> None:
        """A clear peak at index 5 in a V-shaped-inverted pattern."""
        # Create: ..., 100, 110, 120, 130, 140, 150, 140, 130, 120, 110, 100, ...
        values = list(range(100, 151, 10)) + list(range(140, 89, -10))
        series = pd.Series(values, dtype=float)
        highs = DivergenceDetector._find_swing_highs(series, order=2)
        high_indices = list(series.index[highs])
        # The peak at value 150 (index 5) should be detected
        assert 5 in high_indices

    def test_find_swing_lows(self) -> None:
        """A clear trough at index 5 in a V-shaped pattern."""
        values = list(range(150, 99, -10)) + list(range(110, 161, 10))
        series = pd.Series(values, dtype=float)
        lows = DivergenceDetector._find_swing_lows(series, order=2)
        low_indices = list(series.index[lows])
        # The trough at value 100 (index 5) should be detected
        assert 5 in low_indices

    def test_no_swing_in_monotonic(self) -> None:
        """A strictly increasing series should have no swing highs in the middle."""
        series = pd.Series(np.arange(1, 21, dtype=float))
        highs = DivergenceDetector._find_swing_highs(series, order=3)
        # No internal swing highs (only the end might qualify but order excludes it)
        internal_highs = highs.iloc[3:-3]
        assert internal_highs.sum() == 0


# =========================================================================
# Regular bullish divergence
# =========================================================================


class TestRegularBullishDivergence:
    def test_price_lower_low_indicator_higher_low(self) -> None:
        """Construct price making lower lows and indicator making higher lows."""
        n = 50
        # Price: V shape at idx~10, then deeper V at idx~30
        price = np.full(n, 100.0)
        # First trough at 10
        for i in range(5, 16):
            price[i] = 100.0 - 10.0 * (1 - abs(i - 10) / 5.0)
        # Second trough at 30 (deeper)
        for i in range(25, 36):
            price[i] = 100.0 - 15.0 * (1 - abs(i - 30) / 5.0)

        # Indicator: V at same positions but second trough is higher than first
        indicator = np.full(n, 50.0)
        for i in range(5, 16):
            indicator[i] = 50.0 - 10.0 * (1 - abs(i - 10) / 5.0)
        for i in range(25, 36):
            indicator[i] = 50.0 - 5.0 * (1 - abs(i - 30) / 5.0)

        price_s = pd.Series(price)
        ind_s = pd.Series(indicator)

        detector = DivergenceDetector(lookback=30, min_swing_pct=0.0)
        divs = detector.detect_regular_bullish(price_s, ind_s)
        assert len(divs) > 0
        # Each divergence is a tuple (start_idx, end_idx)
        for start, end in divs:
            assert end > start


# =========================================================================
# Regular bearish divergence
# =========================================================================


class TestRegularBearishDivergence:
    def test_price_higher_high_indicator_lower_high(self) -> None:
        """Construct price making higher highs and indicator making lower highs."""
        n = 50
        # Price: peak at idx~10, then higher peak at idx~30
        price = np.full(n, 100.0)
        for i in range(5, 16):
            price[i] = 100.0 + 10.0 * (1 - abs(i - 10) / 5.0)
        for i in range(25, 36):
            price[i] = 100.0 + 15.0 * (1 - abs(i - 30) / 5.0)

        # Indicator: peak at same positions but second peak lower
        indicator = np.full(n, 50.0)
        for i in range(5, 16):
            indicator[i] = 50.0 + 10.0 * (1 - abs(i - 10) / 5.0)
        for i in range(25, 36):
            indicator[i] = 50.0 + 5.0 * (1 - abs(i - 30) / 5.0)

        price_s = pd.Series(price)
        ind_s = pd.Series(indicator)

        detector = DivergenceDetector(lookback=30, min_swing_pct=0.0)
        divs = detector.detect_regular_bearish(price_s, ind_s)
        assert len(divs) > 0


# =========================================================================
# No divergence in trending data
# =========================================================================


class TestNoDivergence:
    def test_trending_data_no_divergence(self) -> None:
        """Monotonically increasing price and indicator: no regular divergences."""
        n = 50
        price = pd.Series(np.linspace(100, 200, n))
        indicator = pd.Series(np.linspace(30, 70, n))

        detector = DivergenceDetector(lookback=30)
        divs_bull = detector.detect_regular_bullish(price, indicator)
        divs_bear = detector.detect_regular_bearish(price, indicator)
        assert len(divs_bull) == 0
        assert len(divs_bear) == 0


# =========================================================================
# detect() aggregate method
# =========================================================================


class TestDetectAggregate:
    def test_returns_list_of_divergence_objects(self) -> None:
        """Verify detect() returns Divergence dataclass instances."""
        n = 50
        price = np.full(n, 100.0)
        indicator = np.full(n, 50.0)
        # Create two peaks with divergence
        for i in range(5, 16):
            price[i] = 100.0 + 10.0 * (1 - abs(i - 10) / 5.0)
        for i in range(25, 36):
            price[i] = 100.0 + 15.0 * (1 - abs(i - 30) / 5.0)
        for i in range(5, 16):
            indicator[i] = 50.0 + 10.0 * (1 - abs(i - 10) / 5.0)
        for i in range(25, 36):
            indicator[i] = 50.0 + 5.0 * (1 - abs(i - 30) / 5.0)

        price_s = pd.Series(price)
        ind_s = pd.Series(indicator)

        detector = DivergenceDetector(lookback=30, min_swing_pct=0.0)
        results = detector.detect(price_s, ind_s, indicator_name="RSI")
        for d in results:
            assert isinstance(d, Divergence)
            assert d.indicator_name == "RSI"
            assert 0.0 <= d.confidence <= 1.0

    def test_length_mismatch_raises(self) -> None:
        detector = DivergenceDetector(lookback=10)
        with pytest.raises(ValueError, match="length"):
            detector.detect(pd.Series([1, 2, 3]), pd.Series([1, 2]))


# =========================================================================
# Edge cases
# =========================================================================


class TestEdgeCases:
    def test_empty_series_no_divergences(self, detector: DivergenceDetector) -> None:
        price = pd.Series(dtype=float)
        indicator = pd.Series(dtype=float)
        results = detector.detect(price, indicator, indicator_name="RSI")
        assert results == []

    def test_short_series_no_divergences(self, detector: DivergenceDetector) -> None:
        """Very short series (< 2 * order) should produce no divergences."""
        price = pd.Series([100.0, 101.0, 99.0])
        indicator = pd.Series([50.0, 52.0, 48.0])
        results = detector.detect(price, indicator, indicator_name="RSI")
        assert results == []

    def test_repr(self, detector: DivergenceDetector) -> None:
        r = repr(detector)
        assert "DivergenceDetector" in r
        assert "20" in r
