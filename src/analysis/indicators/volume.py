"""Volume indicators: OBV, VWAP, MFI, A/D, CMF, and volume profile."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.analysis.indicators.base import Indicator


class OBV(Indicator):
    """On Balance Volume.

    Cumulative volume indicator that adds volume on up days and
    subtracts on down days. Used to confirm price trends.
    """

    name = "OBV"

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        """Compute On Balance Volume.

        Args:
            data: DataFrame with columns: open, high, low, close, volume.

        Returns:
            Series with cumulative OBV values.
        """
        close = data["close"]
        volume = data["volume"]

        # Determine direction: +1 if close > prev close, -1 if <, 0 if equal
        direction = np.sign(close.diff())
        # First bar has no previous close; set direction to 0
        direction.iloc[0] = 0.0

        obv = (direction * volume).cumsum()

        return pd.Series(obv, index=data.index, name="obv")

    def __repr__(self) -> str:
        return "<OBV()>"


class VWAP(Indicator):
    """Volume Weighted Average Price.

    Session-based indicator that provides the average price weighted
    by volume. Commonly used as an intraday benchmark.

    Note:
        This implementation computes a cumulative VWAP from the start
        of the provided data (treating it as a single session).
        For multi-session data, split by date before calling.
    """

    name = "VWAP"

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        """Compute VWAP.

        Uses the typical price (H+L+C)/3 weighted by volume.

        Args:
            data: DataFrame with columns: open, high, low, close, volume.

        Returns:
            Series with VWAP values.
        """
        typical_price = (data["high"] + data["low"] + data["close"]) / 3.0
        volume = data["volume"]

        cum_tp_vol = (typical_price * volume).cumsum()
        cum_vol = volume.cumsum()

        vwap = cum_tp_vol / cum_vol.replace(0, np.nan)

        return pd.Series(vwap, index=data.index, name="vwap")

    def __repr__(self) -> str:
        return "<VWAP()>"


class MFI(Indicator):
    """Money Flow Index.

    A volume-weighted RSI that measures buying and selling pressure.
    Oscillates between 0 and 100. Values above 80 indicate overbought;
    below 20 indicate oversold.

    Args:
        period: Lookback period (default 14).
    """

    name = "MFI"

    def __init__(self, period: int = 14) -> None:
        if period < 1:
            raise ValueError(f"MFI period must be >= 1, got {period}")
        self.period = period

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        """Compute Money Flow Index.

        Args:
            data: DataFrame with columns: open, high, low, close, volume.

        Returns:
            Series with MFI values (0-100 scale).
        """
        typical_price = (data["high"] + data["low"] + data["close"]) / 3.0
        raw_money_flow = typical_price * data["volume"]

        tp_diff = typical_price.diff()

        positive_flow = pd.Series(
            np.where(tp_diff > 0, raw_money_flow, 0.0),
            index=data.index,
            dtype=float,
        )
        negative_flow = pd.Series(
            np.where(tp_diff < 0, raw_money_flow, 0.0),
            index=data.index,
            dtype=float,
        )

        positive_sum = positive_flow.rolling(
            window=self.period, min_periods=self.period
        ).sum()
        negative_sum = negative_flow.rolling(
            window=self.period, min_periods=self.period
        ).sum()

        # When negative_sum is 0, money_ratio is infinite → MFI = 100
        # When positive_sum is 0, money_ratio is 0 → MFI = 0
        money_ratio = positive_sum / negative_sum.replace(0, np.nan)
        mfi = 100.0 - (100.0 / (1.0 + money_ratio))

        # Handle edge cases: all positive flow → MFI = 100, all negative → MFI = 0
        both_valid = positive_sum.notna() & negative_sum.notna()
        all_positive = both_valid & (negative_sum == 0) & (positive_sum > 0)
        all_negative = both_valid & (positive_sum == 0) & (negative_sum > 0)
        mfi = mfi.where(~all_positive, 100.0)
        mfi = mfi.where(~all_negative, 0.0)

        return pd.Series(mfi, index=data.index, name="mfi")

    def __repr__(self) -> str:
        return f"<MFI(period={self.period})>"


class AccumulationDistribution(Indicator):
    """Accumulation/Distribution Line.

    A cumulative indicator that uses volume and price to assess
    whether a stock is being accumulated (bought) or distributed (sold).
    The money flow multiplier captures the position of the close
    relative to the high-low range.
    """

    name = "AccumulationDistribution"

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        """Compute Accumulation/Distribution Line.

        Args:
            data: DataFrame with columns: open, high, low, close, volume.

        Returns:
            Series with cumulative A/D values.
        """
        high = data["high"]
        low = data["low"]
        close = data["close"]
        volume = data["volume"]

        # Money Flow Multiplier: ((close - low) - (high - close)) / (high - low)
        hl_range = high - low
        mfm = pd.Series(
            np.where(
                hl_range != 0,
                ((close - low) - (high - close)) / hl_range,
                0.0,
            ),
            index=data.index,
            dtype=float,
        )

        # Money Flow Volume
        mfv = mfm * volume

        # Cumulative A/D line
        ad_line = mfv.cumsum()

        return pd.Series(ad_line, index=data.index, name="ad_line")

    def __repr__(self) -> str:
        return "<AccumulationDistribution()>"


class ChaikinMoneyFlow(Indicator):
    """Chaikin Money Flow (CMF)."""

    name = "ChaikinMoneyFlow"

    def __init__(self, period: int = 20) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self.period = period

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        high = data["high"]
        low = data["low"]
        close = data["close"]
        volume = data["volume"]

        hl = (high - low).replace(0, np.nan)
        money_flow_multiplier = ((close - low) - (high - close)) / hl
        money_flow_volume = money_flow_multiplier.fillna(0.0) * volume

        cmf = (
            money_flow_volume.rolling(window=self.period, min_periods=self.period).sum()
            / volume.rolling(window=self.period, min_periods=self.period).sum().replace(0, np.nan)
        )
        return pd.Series(cmf, index=data.index, name="cmf")


class VolumeProfile(Indicator):
    """Volume profile using fixed number of price bins."""

    name = "VolumeProfile"

    def __init__(self, bins: int = 30) -> None:
        if bins < 2:
            raise ValueError("bins must be >= 2")
        self.bins = bins

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        if data.empty:
            return pd.Series(dtype=float, name="volume_profile")

        low = float(data["low"].min())
        high = float(data["high"].max())
        if high <= low:
            return pd.Series(dtype=float, name="volume_profile")

        edges = np.linspace(low, high, self.bins + 1)
        mids = (edges[:-1] + edges[1:]) / 2.0
        volumes = np.zeros(self.bins, dtype=float)

        for _, row in data.iterrows():
            c_low = float(row["low"])
            c_high = float(row["high"])
            c_vol = float(row["volume"])
            mask = (mids >= c_low) & (mids <= c_high)
            count = int(mask.sum())
            if count > 0:
                volumes[mask] += c_vol / count

        return pd.Series(volumes, index=np.round(mids, 6), name="volume_profile")
