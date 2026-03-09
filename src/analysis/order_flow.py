"""Order-flow analytics and footprint candle construction.

Builds bid/ask volume distribution at each price level from OHLCV candles.
Since historical candle data does not include true bid/ask prints, this
module uses a deterministic heuristic based on candle direction to split
volume between bid and ask.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class PriceLevel:
    """Bid/ask breakdown for a single price level."""

    price: float
    bid: int
    ask: int
    delta: int
    imbalance: float
    stack: bool = False

    @property
    def dominant_side(self) -> str:
        if self.ask > self.bid:
            return "ask"
        if self.bid > self.ask:
            return "bid"
        return "neutral"

    def to_dict(self) -> dict[str, Any]:
        return {
            "price": round(self.price, 6),
            "bid": self.bid,
            "ask": self.ask,
            "delta": self.delta,
            "imbalance": round(self.imbalance, 4),
            "stack": self.stack,
            "dominant_side": self.dominant_side,
        }


@dataclass
class FootprintBar:
    """Aggregated order-flow bar composed of multiple 1-min candles."""

    time: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    delta: int
    vwap: float
    cvd: int
    levels: list[PriceLevel] = field(default_factory=list)
    imbalance_count: int = 0
    buying_pressure: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return {
            "time": self.time,
            "open": round(self.open, 6),
            "high": round(self.high, 6),
            "low": round(self.low, 6),
            "close": round(self.close, 6),
            "volume": self.volume,
            "delta": self.delta,
            "vwap": round(self.vwap, 6),
            "cvd": self.cvd,
            "levels": [level.to_dict() for level in self.levels],
            "imbalance_count": self.imbalance_count,
            "buying_pressure": round(self.buying_pressure, 4),
            "selling_pressure": round(1.0 - self.buying_pressure, 4),
        }


class OrderFlowAnalyzer:
    """Build and summarize order-flow/footprint data."""

    def __init__(
        self,
        tick_size: float = 0.05,
        imbalance_threshold: float = 0.30,
        stack_threshold: int = 3,
        bullish_ask_ratio: float = 0.60,
        bearish_ask_ratio: float = 0.40,
    ) -> None:
        if tick_size <= 0:
            raise ValueError("tick_size must be > 0")
        if not 0.0 < imbalance_threshold < 1.0:
            raise ValueError("imbalance_threshold must be between 0 and 1")
        if stack_threshold < 2:
            raise ValueError("stack_threshold must be >= 2")
        if not 0.0 < bullish_ask_ratio < 1.0:
            raise ValueError("bullish_ask_ratio must be between 0 and 1")
        if not 0.0 < bearish_ask_ratio < 1.0:
            raise ValueError("bearish_ask_ratio must be between 0 and 1")

        self.tick_size = tick_size
        self.imbalance_threshold = imbalance_threshold
        self.stack_threshold = stack_threshold
        self.bullish_ask_ratio = bullish_ask_ratio
        self.bearish_ask_ratio = bearish_ask_ratio

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_footprints(
        self,
        candles: list[Any],
        bar_minutes: int = 15,
    ) -> list[FootprintBar]:
        """Aggregate 1-minute candles into footprint bars."""
        if bar_minutes <= 0:
            raise ValueError("bar_minutes must be > 0")
        if not candles:
            return []

        bars = self._group_candles(candles, bar_minutes)
        footprints: list[FootprintBar] = []
        cumulative_delta = 0

        for group in bars:
            if not group:
                continue

            bar_open = float(self._value(group[0], "open"))
            bar_close = float(self._value(group[-1], "close"))
            bar_high = max(float(self._value(c, "high")) for c in group)
            bar_low = min(float(self._value(c, "low")) for c in group)
            bar_volume = sum(int(self._value(c, "volume", 0)) for c in group)
            bar_time = self._timestamp(group[0]).isoformat()

            merged: dict[float, dict[str, int]] = {}
            for candle in group:
                for level in self._build_price_levels(candle):
                    bucket = merged.setdefault(level.price, {"bid": 0, "ask": 0})
                    bucket["bid"] += level.bid
                    bucket["ask"] += level.ask

            levels = self._merged_levels_to_objects(merged)
            self._mark_stacks(levels)
            imbalance_count = sum(
                1 for lv in levels if lv.imbalance >= self.imbalance_threshold
            )

            bar_delta = sum(lv.delta for lv in levels)
            cumulative_delta += bar_delta

            total_bid = sum(lv.bid for lv in levels)
            total_ask = sum(lv.ask for lv in levels)
            total = max(total_bid + total_ask, 1)
            buying_pressure = total_ask / total

            vwap = (bar_high + bar_low + bar_close) / 3.0

            footprints.append(
                FootprintBar(
                    time=bar_time,
                    open=bar_open,
                    high=bar_high,
                    low=bar_low,
                    close=bar_close,
                    volume=bar_volume,
                    delta=bar_delta,
                    vwap=vwap,
                    cvd=cumulative_delta,
                    levels=levels,
                    imbalance_count=imbalance_count,
                    buying_pressure=buying_pressure,
                )
            )

        return footprints

    def build_cvd_series(self, candles: list[Any]) -> list[dict[str, Any]]:
        """Build cumulative volume delta (CVD) from 1-minute candles."""
        if not candles:
            return []

        out: list[dict[str, Any]] = []
        cvd = 0
        for candle in sorted(candles, key=self._timestamp):
            c_open = float(self._value(candle, "open"))
            c_close = float(self._value(candle, "close"))
            c_volume = int(self._value(candle, "volume", 0))
            ask_ratio = (
                self.bullish_ask_ratio if c_close >= c_open else self.bearish_ask_ratio
            )
            ask_vol = int(c_volume * ask_ratio)
            bid_vol = c_volume - ask_vol
            delta = ask_vol - bid_vol
            cvd += delta

            out.append(
                {
                    "time": self._timestamp(candle).isoformat(),
                    "close": c_close,
                    "volume": c_volume,
                    "delta": delta,
                    "cvd": cvd,
                }
            )
        return out

    def summarize(self, footprints: list[FootprintBar]) -> dict[str, Any]:
        """Compute headline order-flow metrics from footprint bars."""
        if not footprints:
            return {
                "bars": 0,
                "latest_delta": 0,
                "latest_cvd": 0,
                "delta_trend": "flat",
                "avg_buying_pressure": 0.5,
                "imbalance_ratio": 0.0,
            }

        latest = footprints[-1]
        avg_buy_pressure = sum(fp.buying_pressure for fp in footprints) / len(footprints)
        all_levels = [lv for fp in footprints for lv in fp.levels]
        imbalance_levels = [
            lv for lv in all_levels if lv.imbalance >= self.imbalance_threshold
        ]
        imbalance_ratio = len(imbalance_levels) / max(len(all_levels), 1)

        first_cvd = footprints[0].cvd
        last_cvd = latest.cvd
        if last_cvd > first_cvd:
            trend = "up"
        elif last_cvd < first_cvd:
            trend = "down"
        else:
            trend = "flat"

        return {
            "bars": len(footprints),
            "latest_delta": latest.delta,
            "latest_cvd": latest.cvd,
            "delta_trend": trend,
            "avg_buying_pressure": round(avg_buy_pressure, 4),
            "imbalance_ratio": round(imbalance_ratio, 4),
            "stacked_levels": sum(1 for lv in all_levels if lv.stack),
        }

    @classmethod
    def from_dataframe(
        cls,
        data: pd.DataFrame,
        tick_size: float = 0.05,
    ) -> OrderFlowAnalyzer:
        """Build analyzer instance tuned to dataframe's price precision."""
        if data.empty:
            return cls(tick_size=tick_size)

        inferred_tick = tick_size
        if {"high", "low"}.issubset(data.columns):
            diffs = (data["high"] - data["low"]).abs()
            min_diff = float(diffs[diffs > 0].min()) if (diffs > 0).any() else tick_size
            inferred_tick = min(tick_size, max(round(min_diff / 20.0, 6), 0.01))

        return cls(tick_size=inferred_tick)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_price_levels(self, candle: Any) -> list[PriceLevel]:
        c_open = float(self._value(candle, "open"))
        c_close = float(self._value(candle, "close"))
        c_high = float(self._value(candle, "high"))
        c_low = float(self._value(candle, "low"))
        c_vol = int(self._value(candle, "volume", 0))

        if c_high < c_low:
            return []

        if c_vol <= 0:
            # Provider fallbacks (notably US/Nasdaq) can return intraday
            # prices without reliable minute volume. Derive a stable proxy so
            # order-flow panes render instead of appearing empty.
            range_ticks = int(abs(c_high - c_low) / max(self.tick_size, 1e-6))
            body_ticks = int(abs(c_close - c_open) / max(self.tick_size, 1e-6))
            c_vol = max((range_ticks + body_ticks + 1) * 40, 1)

        ask_ratio = self.bullish_ask_ratio if c_close >= c_open else self.bearish_ask_ratio
        levels_count = max(1, int(round((c_high - c_low) / self.tick_size)))
        levels_count = min(levels_count, 80)
        step = ((c_high - c_low) / levels_count) if levels_count > 0 else 0.0
        vol_per_level = c_vol / levels_count

        levels: list[PriceLevel] = []
        for i in range(levels_count):
            if c_high == c_low:
                price = round(c_close, 6)
            else:
                price = round(c_low + i * step, 6)
            ask = int(vol_per_level * ask_ratio)
            bid = int(vol_per_level * (1.0 - ask_ratio))
            delta = ask - bid
            denom = max(ask, bid, 1)
            imbalance = abs(delta) / denom
            levels.append(
                PriceLevel(
                    price=price,
                    bid=bid,
                    ask=ask,
                    delta=delta,
                    imbalance=imbalance,
                )
            )
        return levels

    def _group_candles(self, candles: list[Any], bar_minutes: int) -> list[list[Any]]:
        ordered = sorted(candles, key=self._timestamp)
        groups: list[list[Any]] = []
        current: list[Any] = []
        bar_start: datetime | None = None

        for candle in ordered:
            ts = self._timestamp(candle)
            if bar_start is None:
                bar_start = ts
                current = [candle]
                continue

            elapsed = (ts - bar_start).total_seconds()
            if elapsed < bar_minutes * 60:
                current.append(candle)
            else:
                groups.append(current)
                bar_start = ts
                current = [candle]

        if current:
            groups.append(current)
        return groups

    def _merged_levels_to_objects(
        self,
        merged: dict[float, dict[str, int]],
    ) -> list[PriceLevel]:
        levels: list[PriceLevel] = []
        for price in sorted(merged.keys()):
            bid = int(merged[price]["bid"])
            ask = int(merged[price]["ask"])
            delta = ask - bid
            denom = max(ask, bid, 1)
            levels.append(
                PriceLevel(
                    price=price,
                    bid=bid,
                    ask=ask,
                    delta=delta,
                    imbalance=abs(delta) / denom,
                )
            )
        return levels

    def _mark_stacks(self, levels: list[PriceLevel]) -> None:
        if len(levels) < self.stack_threshold:
            return

        run_start = 0
        sides = [lv.dominant_side for lv in levels]
        for i in range(1, len(sides) + 1):
            if i < len(sides) and sides[i] == sides[run_start] and sides[i] != "neutral":
                continue

            run_len = i - run_start
            if run_len >= self.stack_threshold and sides[run_start] != "neutral":
                for j in range(run_start, i):
                    levels[j].stack = True

            run_start = i

    @staticmethod
    def _timestamp(candle: Any) -> datetime:
        ts = candle["timestamp"] if isinstance(candle, dict) else getattr(candle, "timestamp")
        if isinstance(ts, datetime):
            return ts
        return pd.to_datetime(ts).to_pydatetime()

    @staticmethod
    def _value(candle: Any, key: str, default: Any = None) -> Any:
        if isinstance(candle, dict):
            return candle.get(key, default)
        return getattr(candle, key, default)
