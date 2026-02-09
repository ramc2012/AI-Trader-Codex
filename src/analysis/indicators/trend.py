"""Trend indicators: ADX, Supertrend, Ichimoku Cloud, Parabolic SAR."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.analysis.indicators.base import Indicator


class ADX(Indicator):
    """Average Directional Index.

    Measures the strength of a trend regardless of direction.
    Values above 25 indicate a strong trend; below 20 is weak/no trend.

    Args:
        period: Smoothing period (default 14).
    """

    name = "ADX"

    def __init__(self, period: int = 14) -> None:
        if period < 1:
            raise ValueError(f"ADX period must be >= 1, got {period}")
        self.period = period

    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """Compute ADX, +DI, and -DI.

        Args:
            data: DataFrame with columns: open, high, low, close, volume.

        Returns:
            DataFrame with columns: 'adx', 'plus_di', 'minus_di'.
        """
        high = data["high"]
        low = data["low"]
        close = data["close"]

        # Directional movement
        up_move = high.diff()
        down_move = -low.diff()

        plus_dm = pd.Series(np.where(
            (up_move > down_move) & (up_move > 0), up_move, 0.0
        ), index=data.index, dtype=float)

        minus_dm = pd.Series(np.where(
            (down_move > up_move) & (down_move > 0), down_move, 0.0
        ), index=data.index, dtype=float)

        # True Range
        close_prev = close.shift(1)
        tr1 = high - low
        tr2 = (high - close_prev).abs()
        tr3 = (low - close_prev).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # Wilder smoothing (EMA with alpha = 1/period)
        alpha = 1.0 / self.period
        smoothed_tr = true_range.ewm(
            alpha=alpha, min_periods=self.period, adjust=False
        ).mean()
        smoothed_plus_dm = plus_dm.ewm(
            alpha=alpha, min_periods=self.period, adjust=False
        ).mean()
        smoothed_minus_dm = minus_dm.ewm(
            alpha=alpha, min_periods=self.period, adjust=False
        ).mean()

        # Directional indicators
        plus_di = 100.0 * smoothed_plus_dm / smoothed_tr
        minus_di = 100.0 * smoothed_minus_dm / smoothed_tr

        # DX and ADX
        di_sum = plus_di + minus_di
        di_diff = (plus_di - minus_di).abs()
        dx = 100.0 * di_diff / di_sum.replace(0, np.nan)

        adx = dx.ewm(
            alpha=alpha, min_periods=self.period, adjust=False
        ).mean()

        return pd.DataFrame(
            {
                "adx": adx,
                "plus_di": plus_di,
                "minus_di": minus_di,
            },
            index=data.index,
        )

    def __repr__(self) -> str:
        return f"<ADX(period={self.period})>"


class Supertrend(Indicator):
    """Supertrend indicator.

    A trend-following overlay that uses ATR to define dynamic
    support/resistance levels. Direction is +1 for uptrend, -1 for downtrend.

    Args:
        period: ATR lookback period (default 10).
        multiplier: ATR multiplier for band width (default 3.0).
    """

    name = "Supertrend"

    def __init__(self, period: int = 10, multiplier: float = 3.0) -> None:
        if period < 1:
            raise ValueError(f"Supertrend period must be >= 1, got {period}")
        if multiplier <= 0:
            raise ValueError(
                f"Supertrend multiplier must be > 0, got {multiplier}"
            )
        self.period = period
        self.multiplier = multiplier

    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """Compute Supertrend and direction.

        Args:
            data: DataFrame with columns: open, high, low, close, volume.

        Returns:
            DataFrame with columns: 'supertrend', 'direction'.
            direction: 1 = uptrend, -1 = downtrend.
        """
        high = data["high"]
        low = data["low"]
        close = data["close"]

        # ATR calculation
        close_prev = close.shift(1)
        tr1 = high - low
        tr2 = (high - close_prev).abs()
        tr3 = (low - close_prev).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = true_range.ewm(
            alpha=1.0 / self.period, min_periods=self.period, adjust=False
        ).mean()

        hl2 = (high + low) / 2.0
        upper_band = hl2 + self.multiplier * atr
        lower_band = hl2 - self.multiplier * atr

        n = len(data)
        supertrend = np.full(n, np.nan)
        direction = np.full(n, 1.0)

        # Find the first valid index (where ATR is not NaN)
        first_valid = atr.first_valid_index()
        if first_valid is None:
            return pd.DataFrame(
                {"supertrend": supertrend, "direction": direction},
                index=data.index,
            )

        start_pos = data.index.get_loc(first_valid)

        upper_vals = upper_band.values.copy()
        lower_vals = lower_band.values.copy()
        close_vals = close.values.copy()

        # Initialize at first valid position
        supertrend[start_pos] = upper_vals[start_pos]
        direction[start_pos] = -1.0

        for i in range(start_pos + 1, n):
            if np.isnan(upper_vals[i]) or np.isnan(lower_vals[i]):
                supertrend[i] = np.nan
                direction[i] = direction[i - 1]
                continue

            # Adjust bands based on previous values
            if lower_vals[i] > lower_vals[i - 1] or close_vals[i - 1] < lower_vals[i - 1]:
                pass  # keep current lower band
            else:
                lower_vals[i] = lower_vals[i - 1]

            if upper_vals[i] < upper_vals[i - 1] or close_vals[i - 1] > upper_vals[i - 1]:
                pass  # keep current upper band
            else:
                upper_vals[i] = upper_vals[i - 1]

            # Determine direction
            if direction[i - 1] == 1.0:  # previous uptrend
                if close_vals[i] < lower_vals[i]:
                    direction[i] = -1.0
                    supertrend[i] = upper_vals[i]
                else:
                    direction[i] = 1.0
                    supertrend[i] = lower_vals[i]
            else:  # previous downtrend
                if close_vals[i] > upper_vals[i]:
                    direction[i] = 1.0
                    supertrend[i] = lower_vals[i]
                else:
                    direction[i] = -1.0
                    supertrend[i] = upper_vals[i]

        return pd.DataFrame(
            {
                "supertrend": supertrend,
                "direction": direction,
            },
            index=data.index,
        )

    def __repr__(self) -> str:
        return (
            f"<Supertrend(period={self.period}, "
            f"multiplier={self.multiplier})>"
        )


class IchimokuCloud(Indicator):
    """Ichimoku Kinko Hyo (Ichimoku Cloud).

    A comprehensive indicator providing support/resistance, trend direction,
    and momentum signals.

    Args:
        tenkan_period: Tenkan-sen (conversion line) period (default 9).
        kijun_period: Kijun-sen (base line) period (default 26).
        senkou_span_b_period: Senkou Span B period (default 52).
    """

    name = "IchimokuCloud"

    def __init__(
        self,
        tenkan_period: int = 9,
        kijun_period: int = 26,
        senkou_span_b_period: int = 52,
    ) -> None:
        if tenkan_period < 1:
            raise ValueError(
                f"tenkan_period must be >= 1, got {tenkan_period}"
            )
        if kijun_period < 1:
            raise ValueError(
                f"kijun_period must be >= 1, got {kijun_period}"
            )
        if senkou_span_b_period < 1:
            raise ValueError(
                f"senkou_span_b_period must be >= 1, got {senkou_span_b_period}"
            )
        self.tenkan_period = tenkan_period
        self.kijun_period = kijun_period
        self.senkou_span_b_period = senkou_span_b_period

    def _midpoint(self, high: pd.Series, low: pd.Series, period: int) -> pd.Series:
        """Calculate the midpoint of highest high and lowest low over a period.

        Args:
            high: High price series.
            low: Low price series.
            period: Lookback period.

        Returns:
            Series of midpoint values.
        """
        highest = high.rolling(window=period, min_periods=period).max()
        lowest = low.rolling(window=period, min_periods=period).min()
        return (highest + lowest) / 2.0

    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """Compute Ichimoku Cloud components.

        Args:
            data: DataFrame with columns: open, high, low, close, volume.

        Returns:
            DataFrame with columns: 'tenkan_sen', 'kijun_sen',
            'senkou_span_a', 'senkou_span_b', 'chikou_span'.
        """
        high = data["high"]
        low = data["low"]
        close = data["close"]

        # Tenkan-sen (Conversion Line): (highest high + lowest low) / 2 over tenkan_period
        tenkan_sen = self._midpoint(high, low, self.tenkan_period)

        # Kijun-sen (Base Line): (highest high + lowest low) / 2 over kijun_period
        kijun_sen = self._midpoint(high, low, self.kijun_period)

        # Senkou Span A (Leading Span A): (tenkan + kijun) / 2, shifted forward by kijun_period
        senkou_span_a = ((tenkan_sen + kijun_sen) / 2.0).shift(self.kijun_period)

        # Senkou Span B (Leading Span B): midpoint over senkou_span_b_period, shifted forward
        senkou_span_b = self._midpoint(
            high, low, self.senkou_span_b_period
        ).shift(self.kijun_period)

        # Chikou Span (Lagging Span): close shifted back by kijun_period
        chikou_span = close.shift(-self.kijun_period)

        return pd.DataFrame(
            {
                "tenkan_sen": tenkan_sen,
                "kijun_sen": kijun_sen,
                "senkou_span_a": senkou_span_a,
                "senkou_span_b": senkou_span_b,
                "chikou_span": chikou_span,
            },
            index=data.index,
        )

    def __repr__(self) -> str:
        return (
            f"<IchimokuCloud(tenkan={self.tenkan_period}, "
            f"kijun={self.kijun_period}, "
            f"senkou_b={self.senkou_span_b_period})>"
        )


class ParabolicSAR(Indicator):
    """Parabolic Stop and Reverse (SAR).

    A trend-following indicator that provides potential entry/exit points.
    SAR trails price with an acceleration factor that increases as the
    trend continues.

    Args:
        af_start: Initial acceleration factor (default 0.02).
        af_increment: AF increment per new extreme point (default 0.02).
        af_max: Maximum acceleration factor (default 0.2).
    """

    name = "ParabolicSAR"

    def __init__(
        self,
        af_start: float = 0.02,
        af_increment: float = 0.02,
        af_max: float = 0.2,
    ) -> None:
        if af_start <= 0:
            raise ValueError(f"af_start must be > 0, got {af_start}")
        if af_increment <= 0:
            raise ValueError(f"af_increment must be > 0, got {af_increment}")
        if af_max <= 0:
            raise ValueError(f"af_max must be > 0, got {af_max}")
        if af_start > af_max:
            raise ValueError(
                f"af_start ({af_start}) must be <= af_max ({af_max})"
            )
        self.af_start = af_start
        self.af_increment = af_increment
        self.af_max = af_max

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        """Compute Parabolic SAR values.

        Args:
            data: DataFrame with columns: open, high, low, close, volume.

        Returns:
            Series with SAR values.
        """
        high = data["high"].values
        low = data["low"].values
        close = data["close"].values
        n = len(data)

        if n < 2:
            return pd.Series(np.full(n, np.nan), index=data.index, name="psar")

        sar = np.full(n, np.nan)
        af = self.af_start
        # Determine initial trend from first two bars
        is_uptrend = close[1] >= close[0]

        if is_uptrend:
            sar[0] = low[0]
            ep = high[0]  # extreme point
        else:
            sar[0] = high[0]
            ep = low[0]

        for i in range(1, n):
            prev_sar = sar[i - 1]

            if is_uptrend:
                sar[i] = prev_sar + af * (ep - prev_sar)
                # SAR cannot be above prior two lows
                sar[i] = min(sar[i], low[i - 1])
                if i >= 2:
                    sar[i] = min(sar[i], low[i - 2])

                if low[i] < sar[i]:
                    # Trend reversal to downtrend
                    is_uptrend = False
                    sar[i] = ep  # SAR flips to the extreme point
                    ep = low[i]
                    af = self.af_start
                else:
                    if high[i] > ep:
                        ep = high[i]
                        af = min(af + self.af_increment, self.af_max)
            else:
                sar[i] = prev_sar + af * (ep - prev_sar)
                # SAR cannot be below prior two highs
                sar[i] = max(sar[i], high[i - 1])
                if i >= 2:
                    sar[i] = max(sar[i], high[i - 2])

                if high[i] > sar[i]:
                    # Trend reversal to uptrend
                    is_uptrend = True
                    sar[i] = ep  # SAR flips to the extreme point
                    ep = high[i]
                    af = self.af_start
                else:
                    if low[i] < ep:
                        ep = low[i]
                        af = min(af + self.af_increment, self.af_max)

        return pd.Series(sar, index=data.index, name="psar")

    def __repr__(self) -> str:
        return (
            f"<ParabolicSAR(af_start={self.af_start}, "
            f"af_increment={self.af_increment}, "
            f"af_max={self.af_max})>"
        )
