"""Time-Price Opportunity (TPO) / Market Profile engine.

Generates Market Profile data from OHLC candles:
- TPO letter assignment (A-Z per 30-minute period)
- Point of Control (POC) — price level with most TPOs
- Value Area High/Low (VAH/VAL) — 70% of TPOs
- Initial Balance (IB) — first hour's range
"""

from __future__ import annotations

import string
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence

from src.database.models import IndexOHLC
from src.utils.logger import get_logger

logger = get_logger(__name__)

# TPO letters: A-Z then a-z (52 periods = 26 hours coverage)
TPO_LETTERS = list(string.ascii_uppercase) + list(string.ascii_lowercase)


@dataclass
class TPOLevel:
    """A single price level in the Market Profile."""

    price: float
    tpo_count: int = 0
    letters: list[str] = field(default_factory=list)
    volume: int = 0


@dataclass
class MarketProfile:
    """Complete Market Profile for a session."""

    date: str
    levels: list[TPOLevel]
    poc: float  # Point of Control
    vah: float  # Value Area High
    val: float  # Value Area Low
    ib_high: float  # Initial Balance High
    ib_low: float  # Initial Balance Low
    open_price: float
    close_price: float
    high: float
    low: float
    total_volume: int


def compute_tpo_profile(
    candles: Sequence[IndexOHLC],
    tick_size: float | None = None,
    value_area_pct: float = 0.70,
) -> MarketProfile | None:
    """Compute Market Profile from intraday OHLC candles (ideally 30-min).

    Args:
        candles: OHLC candles sorted by timestamp ASC (1min or 30min).
        tick_size: Price bracket size. Auto-calculated if None.
        value_area_pct: Fraction of TPOs for value area (default 70%).

    Returns:
        MarketProfile or None if insufficient data.
    """
    if len(candles) < 2:
        return None

    # Auto-calculate tick size from price range
    all_highs = [float(c.high) for c in candles]
    all_lows = [float(c.low) for c in candles]
    session_high = max(all_highs)
    session_low = min(all_lows)
    price_range = session_high - session_low

    if tick_size is None:
        # Aim for ~40-60 price levels
        tick_size = max(round(price_range / 50, 2), 0.5)

    # Build price level grid
    grid_low = (int(session_low / tick_size)) * tick_size
    grid_high = (int(session_high / tick_size) + 1) * tick_size

    levels_map: dict[float, TPOLevel] = {}
    price = grid_low
    while price <= grid_high:
        rounded = round(price, 2)
        levels_map[rounded] = TPOLevel(price=rounded)
        price += tick_size

    # Group candles into 30-minute periods
    periods: dict[int, list[IndexOHLC]] = {}
    for c in candles:
        # Period index: minutes since market open (9:15) / 30
        minutes = c.timestamp.hour * 60 + c.timestamp.minute - 555  # 9:15 = 555 mins
        period_idx = max(0, minutes // 30)
        periods.setdefault(period_idx, []).append(c)

    # Assign TPO letters to price levels
    ib_high = 0.0
    ib_low = float("inf")
    total_volume = 0

    for period_idx in sorted(periods.keys()):
        letter = TPO_LETTERS[period_idx] if period_idx < len(TPO_LETTERS) else "?"
        period_candles = periods[period_idx]

        period_high = max(float(c.high) for c in period_candles)
        period_low = min(float(c.low) for c in period_candles)
        period_volume = sum(int(c.volume) for c in period_candles)
        total_volume += period_volume

        # Initial Balance = first 2 periods (first hour)
        if period_idx < 2:
            ib_high = max(ib_high, period_high)
            ib_low = min(ib_low, period_low)

        # Mark price levels touched during this period
        for level_price, level in levels_map.items():
            if period_low <= level_price <= period_high:
                level.tpo_count += 1
                level.letters.append(letter)
                level.volume += period_volume // max(
                    1, int((period_high - period_low) / tick_size) + 1
                )

    # Find POC (price with most TPOs)
    active_levels = [l for l in levels_map.values() if l.tpo_count > 0]
    if not active_levels:
        return None

    poc_level = max(active_levels, key=lambda l: l.tpo_count)
    poc = poc_level.price

    # Calculate Value Area (70% of total TPOs centered on POC)
    total_tpos = sum(l.tpo_count for l in active_levels)
    target_tpos = int(total_tpos * value_area_pct)

    # Expand from POC outward
    sorted_levels = sorted(active_levels, key=lambda l: l.price)
    poc_idx = next(i for i, l in enumerate(sorted_levels) if l.price == poc)

    va_tpos = poc_level.tpo_count
    upper_idx = poc_idx
    lower_idx = poc_idx

    while va_tpos < target_tpos:
        upper_available = sorted_levels[upper_idx + 1].tpo_count if upper_idx + 1 < len(sorted_levels) else 0
        lower_available = sorted_levels[lower_idx - 1].tpo_count if lower_idx - 1 >= 0 else 0

        if upper_available == 0 and lower_available == 0:
            break

        if upper_available >= lower_available:
            upper_idx += 1
            va_tpos += upper_available
        else:
            lower_idx -= 1
            va_tpos += lower_available

    vah = sorted_levels[upper_idx].price
    val = sorted_levels[lower_idx].price

    session_date = candles[0].timestamp.strftime("%Y-%m-%d")

    return MarketProfile(
        date=session_date,
        levels=sorted(active_levels, key=lambda l: l.price),
        poc=poc,
        vah=vah,
        val=val,
        ib_high=ib_high if ib_high > 0 else session_high,
        ib_low=ib_low if ib_low < float("inf") else session_low,
        open_price=float(candles[0].open),
        close_price=float(candles[-1].close),
        high=session_high,
        low=session_low,
        total_volume=total_volume,
    )


def profile_to_dict(profile: MarketProfile) -> dict[str, Any]:
    """Convert MarketProfile to JSON-serialisable dict."""
    return {
        "date": profile.date,
        "poc": profile.poc,
        "vah": profile.vah,
        "val": profile.val,
        "ib_high": profile.ib_high,
        "ib_low": profile.ib_low,
        "open": profile.open_price,
        "close": profile.close_price,
        "high": profile.high,
        "low": profile.low,
        "total_volume": profile.total_volume,
        "levels": [
            {
                "price": l.price,
                "tpo_count": l.tpo_count,
                "letters": l.letters,
                "volume": l.volume,
            }
            for l in profile.levels
        ],
    }
