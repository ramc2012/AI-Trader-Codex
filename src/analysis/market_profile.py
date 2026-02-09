"""Market Profile engine for volume-at-price analysis.

Builds Market Profile (TPO) charts from OHLCV data, identifying:
- Value Area (VA), Point of Control (POC)
- Initial Balance (IB) range
- Single prints and excess zones
- Profile shape classification

Based on concepts from "Mind Over Markets" by James Dalton.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd

from src.utils.logger import get_logger

logger = get_logger(__name__)

# TPO letters used for each period
TPO_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


class ProfileShape(str, Enum):
    """Market Profile shape classifications."""
    NORMAL = "normal"        # bell-shaped, balanced
    B_SHAPE = "b_shape"      # buying tail, wide bottom
    P_SHAPE = "p_shape"      # selling tail, wide top
    D_SHAPE = "d_shape"      # double distribution
    TREND = "trend"          # elongated, trending
    NEUTRAL = "neutral"      # narrow, no clear direction


@dataclass
class TPORow:
    """A single price level in the profile."""
    price: float
    tpo_count: int = 0
    tpo_letters: str = ""
    volume: int = 0
    is_poc: bool = False
    is_value_area: bool = False


@dataclass
class MarketProfileResult:
    """Complete Market Profile analysis for a session."""

    date: datetime
    tick_size: float
    tpo_rows: list[TPORow] = field(default_factory=list)

    # Key levels
    poc: float | None = None          # Point of Control
    vah: float | None = None          # Value Area High
    val: float | None = None          # Value Area Low
    session_high: float | None = None
    session_low: float | None = None

    # Initial Balance (first hour)
    ib_high: float | None = None
    ib_low: float | None = None

    # Derived metrics
    profile_shape: ProfileShape = ProfileShape.NEUTRAL
    value_area_pct: float = 70.0

    @property
    def ib_range(self) -> float | None:
        if self.ib_high is not None and self.ib_low is not None:
            return self.ib_high - self.ib_low
        return None

    @property
    def session_range(self) -> float | None:
        if self.session_high is not None and self.session_low is not None:
            return self.session_high - self.session_low
        return None

    @property
    def ib_extension(self) -> float | None:
        """How far price extended beyond IB as a ratio."""
        if self.ib_range and self.session_range and self.ib_range > 0:
            return self.session_range / self.ib_range
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "poc": self.poc,
            "vah": self.vah,
            "val": self.val,
            "session_high": self.session_high,
            "session_low": self.session_low,
            "ib_high": self.ib_high,
            "ib_low": self.ib_low,
            "ib_range": self.ib_range,
            "profile_shape": self.profile_shape.value,
            "tpo_count": len(self.tpo_rows),
        }


class MarketProfileEngine:
    """Builds Market Profile (TPO) from intraday OHLCV data.

    Args:
        tick_size: Price increment for binning (e.g., 0.05 for Nifty).
        value_area_pct: Percentage of TPOs for value area (default 70%).
        ib_periods: Number of initial periods for Initial Balance (default 2 for 30-min bars = 1 hour).
    """

    def __init__(
        self,
        tick_size: float = 0.05,
        value_area_pct: float = 70.0,
        ib_periods: int = 2,
    ) -> None:
        self.tick_size = tick_size
        self.value_area_pct = value_area_pct
        self.ib_periods = ib_periods

    def build_profile(
        self,
        candles: pd.DataFrame,
        session_date: datetime | None = None,
    ) -> MarketProfileResult:
        """Build a Market Profile from intraday candle data.

        Args:
            candles: DataFrame with columns: timestamp, open, high, low, close, volume.
                     Should contain one session's worth of intraday data.
            session_date: Date label for the profile.

        Returns:
            MarketProfileResult with POC, VA, IB, and TPO details.
        """
        if candles.empty:
            return MarketProfileResult(
                date=session_date or datetime.now(),
                tick_size=self.tick_size,
            )

        session_date = session_date or candles["timestamp"].iloc[0]

        # Build TPO counts per price level
        price_tpos: Counter[float] = Counter()
        price_volume: Counter[float] = Counter()
        all_prices: list[float] = []

        for idx, row in candles.iterrows():
            period_idx = idx if isinstance(idx, int) else 0
            letter = TPO_LETTERS[min(period_idx, len(TPO_LETTERS) - 1)]
            low_bin = self._round_to_tick(row["low"])
            high_bin = self._round_to_tick(row["high"])

            price = low_bin
            while price <= high_bin:
                price_tpos[price] += 1
                vol_per_level = int(row.get("volume", 0) / max(1, int((high_bin - low_bin) / self.tick_size) + 1))
                price_volume[price] += vol_per_level
                all_prices.append(price)
                price = round(price + self.tick_size, 6)

        if not price_tpos:
            return MarketProfileResult(date=session_date, tick_size=self.tick_size)

        # POC: price with most TPOs
        poc_price = price_tpos.most_common(1)[0][0]

        # Session high/low
        session_high = max(price_tpos.keys())
        session_low = min(price_tpos.keys())

        # Value Area calculation
        vah, val = self._calculate_value_area(price_tpos, poc_price)

        # Initial Balance
        ib_high, ib_low = self._calculate_initial_balance(candles)

        # Build TPO rows
        tpo_rows = []
        sorted_prices = sorted(price_tpos.keys())
        for price in sorted_prices:
            tpo_rows.append(TPORow(
                price=price,
                tpo_count=price_tpos[price],
                volume=price_volume[price],
                is_poc=(price == poc_price),
                is_value_area=(val is not None and vah is not None and val <= price <= vah),
            ))

        # Classify shape
        shape = self._classify_shape(price_tpos, poc_price, session_high, session_low)

        result = MarketProfileResult(
            date=session_date,
            tick_size=self.tick_size,
            tpo_rows=tpo_rows,
            poc=poc_price,
            vah=vah,
            val=val,
            session_high=session_high,
            session_low=session_low,
            ib_high=ib_high,
            ib_low=ib_low,
            profile_shape=shape,
            value_area_pct=self.value_area_pct,
        )

        logger.debug(
            "profile_built",
            poc=poc_price,
            vah=vah,
            val=val,
            shape=shape.value,
        )
        return result

    def _round_to_tick(self, price: float) -> float:
        """Round price down to nearest tick size."""
        return round(round(price / self.tick_size) * self.tick_size, 6)

    def _calculate_value_area(
        self, price_tpos: Counter[float], poc_price: float
    ) -> tuple[float | None, float | None]:
        """Calculate Value Area High and Low using the TPO method.

        Starts at POC and expands outward until capturing value_area_pct
        of total TPOs.
        """
        total_tpos = sum(price_tpos.values())
        target = total_tpos * (self.value_area_pct / 100.0)

        sorted_prices = sorted(price_tpos.keys())
        if not sorted_prices:
            return None, None

        poc_idx = sorted_prices.index(poc_price)
        va_tpos = price_tpos[poc_price]
        low_idx = poc_idx
        high_idx = poc_idx

        while va_tpos < target:
            expand_up = price_tpos[sorted_prices[high_idx + 1]] if high_idx + 1 < len(sorted_prices) else 0
            expand_down = price_tpos[sorted_prices[low_idx - 1]] if low_idx - 1 >= 0 else 0

            if expand_up >= expand_down and high_idx + 1 < len(sorted_prices):
                high_idx += 1
                va_tpos += price_tpos[sorted_prices[high_idx]]
            elif low_idx - 1 >= 0:
                low_idx -= 1
                va_tpos += price_tpos[sorted_prices[low_idx]]
            else:
                break

        return sorted_prices[high_idx], sorted_prices[low_idx]

    def _calculate_initial_balance(
        self, candles: pd.DataFrame
    ) -> tuple[float | None, float | None]:
        """Calculate Initial Balance from the first N periods."""
        if len(candles) < self.ib_periods:
            ib_candles = candles
        else:
            ib_candles = candles.iloc[: self.ib_periods]

        if ib_candles.empty:
            return None, None

        return float(ib_candles["high"].max()), float(ib_candles["low"].min())

    def _classify_shape(
        self,
        price_tpos: Counter[float],
        poc: float,
        high: float,
        low: float,
    ) -> ProfileShape:
        """Classify the profile shape based on TPO distribution."""
        total_range = high - low
        if total_range == 0:
            return ProfileShape.NEUTRAL

        poc_position = (poc - low) / total_range  # 0 = bottom, 1 = top

        sorted_prices = sorted(price_tpos.keys())
        mid_idx = len(sorted_prices) // 2
        upper_tpos = sum(price_tpos[p] for p in sorted_prices[mid_idx:])
        lower_tpos = sum(price_tpos[p] for p in sorted_prices[:mid_idx])
        total = upper_tpos + lower_tpos

        if total == 0:
            return ProfileShape.NEUTRAL

        upper_ratio = upper_tpos / total
        max_tpo = max(price_tpos.values())
        avg_tpo = sum(price_tpos.values()) / len(price_tpos)

        # Trend day: elongated, low TPO concentration
        if max_tpo <= avg_tpo * 1.5 and len(sorted_prices) > 20:
            return ProfileShape.TREND

        # B-shape: fat bottom (POC in lower third)
        if poc_position < 0.35 and lower_tpos > upper_tpos * 1.3:
            return ProfileShape.B_SHAPE

        # P-shape: fat top (POC in upper third)
        if poc_position > 0.65 and upper_tpos > lower_tpos * 1.3:
            return ProfileShape.P_SHAPE

        # Normal: bell-shaped, POC near middle
        if 0.35 <= poc_position <= 0.65:
            return ProfileShape.NORMAL

        return ProfileShape.NEUTRAL
