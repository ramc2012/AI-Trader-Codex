"""Tests for candlestick pattern detection."""

import numpy as np
import pandas as pd
import pytest

from src.analysis.patterns.candlestick import (
    CandlestickDetector,
    CandlestickPattern,
    PatternType,
)


@pytest.fixture
def detector() -> CandlestickDetector:
    """Default detector with a reasonable body threshold."""
    return CandlestickDetector(body_threshold=0.05)


def _make_ohlc(**kwargs: list) -> pd.DataFrame:
    """Helper to build a minimal OHLC DataFrame."""
    return pd.DataFrame(kwargs, dtype=float)


# =========================================================================
# Helper method tests
# =========================================================================


class TestHelpers:
    def test_body_size(self, detector: CandlestickDetector) -> None:
        df = _make_ohlc(open=[100, 105], high=[110, 110], low=[90, 90], close=[105, 100])
        result = detector._body_size(df)
        np.testing.assert_array_equal(result.values, [5.0, 5.0])

    def test_upper_shadow(self, detector: CandlestickDetector) -> None:
        df = _make_ohlc(open=[100], high=[110], low=[90], close=[105])
        result = detector._upper_shadow(df)
        assert result.iloc[0] == 5.0  # 110 - max(100, 105) = 5

    def test_lower_shadow(self, detector: CandlestickDetector) -> None:
        df = _make_ohlc(open=[100], high=[110], low=[90], close=[105])
        result = detector._lower_shadow(df)
        assert result.iloc[0] == 10.0  # min(100, 105) - 90 = 10

    def test_is_bullish_bearish(self, detector: CandlestickDetector) -> None:
        df = _make_ohlc(open=[100, 105], high=[110, 110], low=[90, 90], close=[105, 100])
        assert detector._is_bullish(df).iloc[0] == True
        assert detector._is_bearish(df).iloc[1] == True

    def test_body_midpoint(self, detector: CandlestickDetector) -> None:
        df = _make_ohlc(open=[100], high=[110], low=[90], close=[106])
        assert detector._body_midpoint(df).iloc[0] == 103.0


# =========================================================================
# Single candle pattern tests
# =========================================================================


class TestDoji:
    def test_classic_doji(self, detector: CandlestickDetector) -> None:
        """Open ~ close with wicks on both sides."""
        df = _make_ohlc(
            open=[100.0],
            high=[102.0],
            low=[98.0],
            close=[100.05],
        )
        result = detector.detect_doji(df)
        # body / range = 0.05 / 4.0 = 0.0125 < 0.05
        assert result.iloc[0] == True

    def test_not_doji_large_body(self, detector: CandlestickDetector) -> None:
        df = _make_ohlc(
            open=[100.0],
            high=[106.0],
            low=[99.0],
            close=[105.0],
        )
        result = detector.detect_doji(df)
        # body / range = 5 / 7 = 0.71
        assert result.iloc[0] == False

    def test_doji_zero_range(self, detector: CandlestickDetector) -> None:
        """All OHLC identical -- zero range should not raise."""
        df = _make_ohlc(open=[100], high=[100], low=[100], close=[100])
        result = detector.detect_doji(df)
        # NaN ratio -> fillna(False)
        assert result.iloc[0] == False


class TestHammer:
    def test_hammer_detected(self, detector: CandlestickDetector) -> None:
        df = _make_ohlc(
            open=[100.0],
            high=[101.0],
            low=[95.0],
            close=[100.5],
        )
        result = detector.detect_hammer(df)
        # body = 0.5, range = 6, ratio ~0.08 < 0.35 -> small body
        # lower shadow = 100 - 95 = 5 >= 2 * 0.5 = 1.0 -> long lower
        # upper shadow = 101 - 100.5 = 0.5 <= 0.5 * 0.5 = 0.25? => 0.5 > 0.25
        # With this data upper = 0.5 which is == body * 1.0
        # Adjust data to make upper shadow smaller
        df2 = _make_ohlc(
            open=[100.0],
            high=[100.2],
            low=[95.0],
            close=[100.1],
        )
        result2 = detector.detect_hammer(df2)
        # body = 0.1, lower = 100.0 - 95.0 = 5.0, upper = 100.2 - 100.1 = 0.1
        # lower >= 2*body: 5.0 >= 0.2 -> True
        # upper <= body*0.5: 0.1 <= 0.05 -> False still too big
        # Let's use data where upper shadow is truly tiny
        df3 = _make_ohlc(
            open=[100.0],
            high=[100.0],
            low=[95.0],
            close=[100.0],
        )
        result3 = detector.detect_hammer(df3)
        # body = 0, which means lower >= 2*0 = 0 and upper <= 0
        # But body/range = 0/5 = 0 < 0.35 -> small body
        # Actually body=0 means this would be a doji too; let's use a clearer case
        df4 = _make_ohlc(
            open=[99.5],
            high=[100.0],
            low=[95.0],
            close=[100.0],
        )
        result4 = detector.detect_hammer(df4)
        # body = 0.5, range = 5.0, ratio = 0.1 < 0.35
        # lower = 99.5 - 95 = 4.5 >= 2*0.5 = 1.0 -> True
        # upper = 100 - 100 = 0 <= 0.5*0.5 = 0.25 -> True
        assert result4.iloc[0] == True

    def test_not_hammer_no_lower_shadow(self, detector: CandlestickDetector) -> None:
        df = _make_ohlc(
            open=[100.0],
            high=[105.0],
            low=[100.0],
            close=[100.5],
        )
        result = detector.detect_hammer(df)
        # lower shadow = 0, not >= 2 * body
        assert result.iloc[0] == False


class TestShootingStar:
    def test_shooting_star_detected(self, detector: CandlestickDetector) -> None:
        df = _make_ohlc(
            open=[100.0],
            high=[105.0],
            low=[99.5],
            close=[100.0],
        )
        # body = 0.0, but let's make a small body version
        df = _make_ohlc(
            open=[100.0],
            high=[105.0],
            low=[100.0],
            close=[100.5],
        )
        result = detector.detect_shooting_star(df)
        # body = 0.5, range = 5.0, ratio = 0.1 < 0.35
        # upper = 105 - 100.5 = 4.5 >= 2*0.5 = 1.0 -> True
        # lower = 100 - 100 = 0 <= 0.5*0.5 = 0.25 -> True
        assert result.iloc[0] == True

    def test_not_shooting_star(self, detector: CandlestickDetector) -> None:
        df = _make_ohlc(
            open=[100.0],
            high=[100.5],
            low=[95.0],
            close=[100.0],
        )
        result = detector.detect_shooting_star(df)
        # upper shadow tiny, lower shadow large -> hammer, not shooting star
        assert result.iloc[0] == False


class TestSpinningTop:
    def test_spinning_top_detected(self, detector: CandlestickDetector) -> None:
        df = _make_ohlc(
            open=[100.0],
            high=[103.0],
            low=[97.0],
            close=[100.5],
        )
        result = detector.detect_spinning_top(df)
        # body = 0.5, range = 6.0, ratio = 0.083 < 0.35
        # upper = 103 - 100.5 = 2.5 > 0.5*0.5=0.25 -> True
        # lower = 100 - 97 = 3.0 > 0.25 -> True
        # shadow ratio: max(2.5,3)/min(2.5,3) = 3/2.5 = 1.2 < 3 -> True
        assert result.iloc[0] == True

    def test_not_spinning_top_one_sided(self, detector: CandlestickDetector) -> None:
        """Only one shadow -> not spinning top."""
        df = _make_ohlc(
            open=[100.0],
            high=[105.0],
            low=[100.0],
            close=[100.5],
        )
        result = detector.detect_spinning_top(df)
        # lower shadow = 0 -> fails significant_shadows
        assert result.iloc[0] == False


# =========================================================================
# Two candle pattern tests
# =========================================================================


class TestEngulfing:
    def test_bullish_engulfing(self, detector: CandlestickDetector) -> None:
        df = _make_ohlc(
            open=[102.0, 97.0],
            high=[103.0, 104.0],
            low=[97.5, 96.5],
            close=[98.0, 103.0],
        )
        result = detector.detect_engulfing(df)
        assert result.iloc[0] == 0  # first bar: no prior
        assert result.iloc[1] == 1  # bullish engulfing

    def test_bearish_engulfing(self, detector: CandlestickDetector) -> None:
        df = _make_ohlc(
            open=[98.0, 103.0],
            high=[103.0, 104.0],
            low=[97.5, 96.5],
            close=[102.0, 97.0],
        )
        result = detector.detect_engulfing(df)
        assert result.iloc[1] == -1  # bearish engulfing

    def test_no_engulfing(self, detector: CandlestickDetector) -> None:
        df = _make_ohlc(
            open=[100.0, 101.0],
            high=[103.0, 103.0],
            low=[99.0, 99.0],
            close=[102.0, 102.0],
        )
        result = detector.detect_engulfing(df)
        assert result.iloc[1] == 0


class TestHarami:
    def test_bullish_harami(self, detector: CandlestickDetector) -> None:
        df = _make_ohlc(
            open=[105.0, 100.0],
            high=[106.0, 103.0],
            low=[98.0, 99.0],
            close=[99.0, 101.0],
        )
        result = detector.detect_harami(df)
        # prev: open=105, close=99 (bearish, body [99, 105])
        # curr: open=100, close=101 (bullish, body [100, 101])
        # 100 >= 99 and 101 <= 105 -> inside
        assert result.iloc[1] == 1

    def test_bearish_harami(self, detector: CandlestickDetector) -> None:
        df = _make_ohlc(
            open=[99.0, 104.0],
            high=[106.0, 105.0],
            low=[98.0, 100.0],
            close=[105.0, 103.0],
        )
        result = detector.detect_harami(df)
        # prev: open=99, close=105 (bullish, body [99, 105])
        # curr: open=104, close=103 (bearish, body [103, 104])
        # 104 <= 105 and 103 >= 99 -> inside
        assert result.iloc[1] == -1


# =========================================================================
# Three candle pattern tests
# =========================================================================


class TestMorningStar:
    def test_morning_star_detected(self, detector: CandlestickDetector) -> None:
        df = _make_ohlc(
            open=[110.0, 101.0, 102.0],
            high=[111.0, 102.0, 109.0],
            low=[100.0, 99.5, 101.0],
            close=[101.0, 101.5, 108.0],
        )
        result = detector.detect_morning_star(df)
        # 1st: open=110, close=101, bearish, body=9, range=11, ratio=0.82 > 0.5
        # 2nd: body=0.5, range=2.5, ratio=0.2 < 0.35
        # 3rd: bullish, body=6, range=8, ratio=0.75 > 0.5
        # midpoint of first = (110+101)/2 = 105.5, close=108 > 105.5
        assert result.iloc[2] == True

    def test_morning_star_not_detected_third_not_above_mid(
        self, detector: CandlestickDetector
    ) -> None:
        df = _make_ohlc(
            open=[110.0, 101.0, 102.0],
            high=[111.0, 102.0, 105.0],
            low=[100.0, 99.5, 101.0],
            close=[101.0, 101.5, 104.0],
        )
        result = detector.detect_morning_star(df)
        # midpoint of first = 105.5, close=104 < 105.5 -> fails
        assert result.iloc[2] == False


class TestEveningStar:
    def test_evening_star_detected(self, detector: CandlestickDetector) -> None:
        df = _make_ohlc(
            open=[100.0, 109.0, 108.0],
            high=[110.0, 110.5, 109.0],
            low=[99.0, 108.5, 101.0],
            close=[109.0, 109.5, 102.0],
        )
        result = detector.detect_evening_star(df)
        # 1st: open=100, close=109, bullish, body=9, range=11, ratio=0.82 > 0.5
        # 2nd: body=0.5, range=2.0, ratio=0.25 < 0.35
        # 3rd: bearish, body=6, range=8, ratio=0.75 > 0.5
        # midpoint of first = (100+109)/2 = 104.5, close=102 < 104.5
        assert result.iloc[2] == True


class TestThreeWhiteSoldiers:
    def test_three_white_soldiers_detected(
        self, detector: CandlestickDetector
    ) -> None:
        df = _make_ohlc(
            open=[100.0, 103.0, 106.0],
            high=[105.0, 108.0, 111.0],
            low=[99.0, 102.0, 105.0],
            close=[104.0, 107.0, 110.0],
        )
        result = detector.detect_three_white_soldiers(df)
        # All bullish: 104>100, 107>103, 110>106
        # Higher closes: 110 > 107 > 104
        # Opens within prev body: 103 >= 100, 103 <= 104; 106 >= 103, 106 <= 107
        assert result.iloc[2] == True

    def test_not_three_white_soldiers_one_bearish(
        self, detector: CandlestickDetector
    ) -> None:
        df = _make_ohlc(
            open=[100.0, 106.0, 106.0],
            high=[105.0, 108.0, 111.0],
            low=[99.0, 102.0, 105.0],
            close=[104.0, 103.0, 110.0],
        )
        result = detector.detect_three_white_soldiers(df)
        # Second candle is bearish: open=106, close=103
        assert result.iloc[2] == False


class TestThreeBlackCrows:
    def test_three_black_crows_detected(
        self, detector: CandlestickDetector
    ) -> None:
        df = _make_ohlc(
            open=[110.0, 107.0, 104.0],
            high=[111.0, 108.0, 105.0],
            low=[105.0, 102.0, 99.0],
            close=[106.0, 103.0, 100.0],
        )
        result = detector.detect_three_black_crows(df)
        # All bearish: 106<110, 103<107, 100<104
        # Lower closes: 100 < 103 < 106
        # Opens within prev body (bearish body: open is top, close is bottom):
        #   107 <= 110, 107 >= 106; 104 <= 107, 104 >= 103
        assert result.iloc[2] == True

    def test_not_three_black_crows_higher_close(
        self, detector: CandlestickDetector
    ) -> None:
        df = _make_ohlc(
            open=[110.0, 107.0, 104.0],
            high=[111.0, 108.0, 105.0],
            low=[105.0, 102.0, 99.0],
            close=[106.0, 103.0, 103.5],
        )
        result = detector.detect_three_black_crows(df)
        # Third close 103.5 > 103 -> not lower
        assert result.iloc[2] == False


# =========================================================================
# detect_all aggregate tests
# =========================================================================


class TestDetectAll:
    def test_detect_all_returns_list(self, detector: CandlestickDetector) -> None:
        df = _make_ohlc(
            open=[100.0, 100.0],
            high=[102.0, 102.0],
            low=[98.0, 98.0],
            close=[100.05, 100.05],
        )
        patterns = detector.detect_all(df)
        assert isinstance(patterns, list)
        for p in patterns:
            assert isinstance(p, CandlestickPattern)

    def test_detect_all_missing_columns(self, detector: CandlestickDetector) -> None:
        df = pd.DataFrame({"open": [1], "close": [2]})
        with pytest.raises(ValueError, match="missing columns"):
            detector.detect_all(df)

    def test_detect_all_finds_bullish_engulfing(
        self, detector: CandlestickDetector
    ) -> None:
        df = _make_ohlc(
            open=[102.0, 97.0],
            high=[103.0, 104.0],
            low=[97.5, 96.5],
            close=[98.0, 103.0],
        )
        patterns = detector.detect_all(df)
        names = [p.name for p in patterns]
        assert "Bullish Engulfing" in names

    def test_detect_all_sorted_by_index(
        self, detector: CandlestickDetector
    ) -> None:
        # Multi-bar data with patterns at different indices
        df = _make_ohlc(
            open=[110.0, 101.0, 102.0, 102.0, 97.0],
            high=[111.0, 102.0, 109.0, 103.0, 104.0],
            low=[100.0, 99.5, 101.0, 97.5, 96.5],
            close=[101.0, 101.5, 108.0, 98.0, 103.0],
        )
        patterns = detector.detect_all(df)
        indices = [p.index for p in patterns]
        assert indices == sorted(indices)


# =========================================================================
# Edge cases
# =========================================================================


class TestEdgeCases:
    def test_empty_dataframe(self, detector: CandlestickDetector) -> None:
        df = pd.DataFrame(columns=["open", "high", "low", "close"])
        patterns = detector.detect_all(df)
        assert patterns == []

    def test_single_bar(self, detector: CandlestickDetector) -> None:
        df = _make_ohlc(open=[100], high=[102], low=[98], close=[100.05])
        patterns = detector.detect_all(df)
        # Should detect single-candle patterns but not multi-candle ones
        assert all(
            p.name in ("Doji", "Hammer", "Shooting Star", "Spinning Top")
            for p in patterns
        )

    def test_invalid_body_threshold(self) -> None:
        with pytest.raises(ValueError, match="body_threshold must be >= 0"):
            CandlestickDetector(body_threshold=-0.1)

    def test_repr(self, detector: CandlestickDetector) -> None:
        r = repr(detector)
        assert "CandlestickDetector" in r
        assert "0.05" in r

    def test_pattern_type_enum(self) -> None:
        assert PatternType.BULLISH.value == "bullish"
        assert PatternType.BEARISH.value == "bearish"
        assert PatternType.NEUTRAL.value == "neutral"
