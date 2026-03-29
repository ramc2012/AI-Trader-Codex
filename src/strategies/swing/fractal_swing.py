"""Fractal Swing Strategy.

Wraps the existing fractal radar (fractal_scan.py) into a BaseStrategy
that generates swing trading signals from fractal profile analysis.

The fractal radar does sophisticated market profile analysis:
- Builds hourly TPO profiles to detect elongated shapes
- Tracks price migration direction over consecutive hours
- Validates against daily charts and order flow
- Produces conviction-scored candidates

This strategy converts those candidates into tradeable Signal objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from src.strategies.base import (
    BaseStrategy,
    Signal,
    SignalStrength,
    SignalType,
    TradingStyle,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


class FractalSwingStrategy(BaseStrategy):
    """Swing trading strategy powered by the fractal radar.

    Converts fractal scan candidates (with conviction scores, direction,
    daily alignment, and order flow confirmation) into swing trade signals.

    This strategy expects pre-computed fractal data in the DataFrame's attrs
    or in a 'fractal_candidate' column, rather than computing fractals itself.

    Args:
        min_conviction: Minimum conviction score (1-5) to generate a signal.
        min_consecutive_hours: Minimum consecutive migration hours.
        require_orderflow: Whether to require order flow confirmation.
        profit_target_pct: Target profit percentage.
        stop_loss_pct: Maximum stop loss percentage.
        max_hold_days: Maximum number of days to hold.
    """

    name = "fractal_swing"
    trading_style = TradingStyle.SWING

    def __init__(
        self,
        min_conviction: int = 3,
        min_consecutive_hours: int = 2,
        require_orderflow: bool = True,
        profit_target_pct: float = 2.0,
        stop_loss_pct: float = 1.0,
        max_hold_days: int = 5,
    ) -> None:
        self.min_conviction = min_conviction
        self.min_consecutive_hours = min_consecutive_hours
        self.require_orderflow = require_orderflow
        self.profit_target_pct = profit_target_pct
        self.stop_loss_pct = stop_loss_pct
        self.max_hold_days = max_hold_days

    def generate_signals(self, data: pd.DataFrame) -> list[Signal]:
        """Generate swing signals from fractal radar data.

        The data DataFrame should have a 'fractal_candidate' column or
        the fractal data should be passed via data.attrs['fractal_candidates'].
        """
        signals: list[Signal] = []

        # Try to get fractal candidates from attrs (injected by agent)
        candidates = data.attrs.get("fractal_candidates", [])

        # Alternatively, check if data contains fractal analysis columns
        if not candidates and "fractal_candidate" in data.columns:
            for _, row in data.iterrows():
                candidate = row.get("fractal_candidate")
                if candidate and isinstance(candidate, dict):
                    candidates.append(candidate)

        for candidate in candidates:
            conviction = int(candidate.get("conviction", 0))
            if conviction < self.min_conviction:
                continue

            consecutive_hours = int(candidate.get("consecutive_migration_hours", 0))
            if consecutive_hours < self.min_consecutive_hours:
                continue

            daily_alignment = bool(candidate.get("daily_alignment", False))
            orderflow_confirmed = bool(candidate.get("aggressive_flow_detected", False))

            if self.require_orderflow and not orderflow_confirmed:
                continue

            direction = str(candidate.get("direction", "")).lower()
            symbol = str(candidate.get("symbol", ""))
            entry_price = float(candidate.get("entry_price", 0) or candidate.get("close", 0))

            if not symbol or entry_price <= 0:
                continue

            # Determine signal type from direction
            if direction == "bullish":
                signal_type = SignalType.BUY
                target = entry_price * (1 + self.profit_target_pct / 100)
                stop = entry_price * (1 - self.stop_loss_pct / 100)
            elif direction == "bearish":
                signal_type = SignalType.SELL
                target = entry_price * (1 - self.profit_target_pct / 100)
                stop = entry_price * (1 + self.stop_loss_pct / 100)
            else:
                continue

            # Strength from conviction level
            if conviction >= 4:
                strength = SignalStrength.STRONG
            elif conviction >= 3:
                strength = SignalStrength.MODERATE
            else:
                strength = SignalStrength.WEAK

            # Boost strength if daily alignment
            if daily_alignment and strength != SignalStrength.STRONG:
                strength = SignalStrength.MODERATE if strength == SignalStrength.WEAK else SignalStrength.STRONG

            signals.append(Signal(
                timestamp=datetime.now(),
                symbol=symbol,
                signal_type=signal_type,
                strength=strength,
                trading_style=TradingStyle.SWING,
                price=entry_price,
                stop_loss=stop,
                target=target,
                strategy_name=self.name,
                holding_period_minutes=self.max_hold_days * 390,  # Trading minutes per day
                metadata={
                    "conviction": conviction,
                    "consecutive_hours": consecutive_hours,
                    "daily_alignment": daily_alignment,
                    "orderflow_confirmed": orderflow_confirmed,
                    "direction": direction,
                    "option_contract": candidate.get("suggested_contract"),
                },
            ))

        logger.debug(
            "fractal_swing_signals",
            candidates_evaluated=len(candidates),
            signals_generated=len(signals),
        )

        return signals


class DivergenceSwingStrategy(BaseStrategy):
    """Swing strategy using RSI/MACD divergence + support/resistance.

    Detects bullish and bearish divergences between price and momentum
    indicators on hourly/daily charts for multi-day swing trades.

    Args:
        rsi_period: RSI calculation period.
        rsi_oversold: RSI level for oversold condition.
        rsi_overbought: RSI level for overbought condition.
        lookback_bars: Number of bars to search for divergence.
        profit_target_pct: Target profit percentage.
        stop_loss_pct: Stop loss percentage.
    """

    name = "divergence_swing"
    trading_style = TradingStyle.SWING

    def __init__(
        self,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        lookback_bars: int = 20,
        profit_target_pct: float = 3.0,
        stop_loss_pct: float = 1.5,
    ) -> None:
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.lookback_bars = lookback_bars
        self.profit_target_pct = profit_target_pct
        self.stop_loss_pct = stop_loss_pct

    def generate_signals(self, data: pd.DataFrame) -> list[Signal]:
        """Generate swing signals from RSI divergence."""
        if data is None or len(data) < self.rsi_period + self.lookback_bars:
            return []

        signals: list[Signal] = []
        df = data.copy()

        # Calculate RSI
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0.0).rolling(window=self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(window=self.rsi_period).mean()
        rs = gain / loss.replace(0, float("nan"))
        df["rsi"] = 100 - (100 / (1 + rs))

        # Look for divergences in the last lookback_bars
        end = len(df)
        start = max(0, end - self.lookback_bars)
        recent = df.iloc[start:end]

        if len(recent) < 5:
            return signals

        # Find swing lows in price
        price_lows = self._find_swing_points(recent["close"].values, "low")
        rsi_at_lows = [float(recent["rsi"].iloc[i]) for i in price_lows if not pd.isna(recent["rsi"].iloc[i])]

        # Bullish divergence: price makes lower low, RSI makes higher low
        if len(price_lows) >= 2:
            last_low_idx = price_lows[-1]
            prev_low_idx = price_lows[-2]
            price_last = float(recent["close"].iloc[last_low_idx])
            price_prev = float(recent["close"].iloc[prev_low_idx])
            rsi_last = float(recent["rsi"].iloc[last_low_idx])
            rsi_prev = float(recent["rsi"].iloc[prev_low_idx])

            if price_last < price_prev and rsi_last > rsi_prev and rsi_last < self.rsi_oversold + 10:
                close = float(df["close"].iloc[-1])
                symbol = df.attrs.get("symbol", "")
                signals.append(Signal(
                    timestamp=datetime.now(),
                    symbol=str(symbol),
                    signal_type=SignalType.BUY,
                    strength=SignalStrength.MODERATE,
                    trading_style=TradingStyle.SWING,
                    price=close,
                    stop_loss=close * (1 - self.stop_loss_pct / 100),
                    target=close * (1 + self.profit_target_pct / 100),
                    strategy_name=self.name,
                    holding_period_minutes=3 * 390,  # ~3 trading days
                    metadata={
                        "divergence_type": "bullish",
                        "rsi_current": round(rsi_last, 1),
                        "price_low_1": round(price_prev, 2),
                        "price_low_2": round(price_last, 2),
                    },
                ))

        # Find swing highs in price
        price_highs = self._find_swing_points(recent["close"].values, "high")

        # Bearish divergence: price makes higher high, RSI makes lower high
        if len(price_highs) >= 2:
            last_high_idx = price_highs[-1]
            prev_high_idx = price_highs[-2]
            price_last = float(recent["close"].iloc[last_high_idx])
            price_prev = float(recent["close"].iloc[prev_high_idx])
            rsi_last = float(recent["rsi"].iloc[last_high_idx])
            rsi_prev = float(recent["rsi"].iloc[prev_high_idx])

            if price_last > price_prev and rsi_last < rsi_prev and rsi_last > self.rsi_overbought - 10:
                close = float(df["close"].iloc[-1])
                symbol = df.attrs.get("symbol", "")
                signals.append(Signal(
                    timestamp=datetime.now(),
                    symbol=str(symbol),
                    signal_type=SignalType.SELL,
                    strength=SignalStrength.MODERATE,
                    trading_style=TradingStyle.SWING,
                    price=close,
                    stop_loss=close * (1 + self.stop_loss_pct / 100),
                    target=close * (1 - self.profit_target_pct / 100),
                    strategy_name=self.name,
                    holding_period_minutes=3 * 390,
                    metadata={
                        "divergence_type": "bearish",
                        "rsi_current": round(rsi_last, 1),
                        "price_high_1": round(price_prev, 2),
                        "price_high_2": round(price_last, 2),
                    },
                ))

        return signals

    @staticmethod
    def _find_swing_points(values: Any, point_type: str, order: int = 3) -> list[int]:
        """Find local minima or maxima in a series."""
        points: list[int] = []
        for i in range(order, len(values) - order):
            if point_type == "low":
                if all(values[i] <= values[i - j] for j in range(1, order + 1)) and \
                   all(values[i] <= values[i + j] for j in range(1, order + 1)):
                    points.append(i)
            elif point_type == "high":
                if all(values[i] >= values[i - j] for j in range(1, order + 1)) and \
                   all(values[i] >= values[i + j] for j in range(1, order + 1)):
                    points.append(i)
        return points
