"""Supertrend Breakout strategy.

Generates BUY when supertrend direction changes from -1 to +1,
and SELL when supertrend direction changes from +1 to -1.
Includes ATR-based stop-loss and risk-reward target calculation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from src.analysis.indicators import ATR
from src.analysis.indicators.trend import Supertrend
from src.strategies.base import BaseStrategy, Signal, SignalStrength, SignalType
from src.utils.logger import get_logger

logger = get_logger(__name__)


class SupertrendStrategy(BaseStrategy):
    """Directional strategy based on Supertrend direction changes with ATR stops.

    Args:
        st_period: Supertrend ATR lookback period (default 10).
        st_multiplier: Supertrend ATR multiplier (default 3.0).
        atr_period: ATR period for stop-loss calculation (default 14).
        atr_sl_multiplier: ATR multiplier for stop-loss distance (default 2.0).
        risk_reward_ratio: Target distance as multiple of stop distance (default 2.0).
    """

    name = "Supertrend_Breakout"

    def __init__(
        self,
        st_period: int = 10,
        st_multiplier: float = 3.0,
        atr_period: int = 14,
        atr_sl_multiplier: float = 2.0,
        risk_reward_ratio: float = 2.0,
    ) -> None:
        self.st_period = st_period
        self.st_multiplier = st_multiplier
        self.atr_period = atr_period
        self.atr_sl_multiplier = atr_sl_multiplier
        self.risk_reward_ratio = risk_reward_ratio

        self._supertrend = Supertrend(period=st_period, multiplier=st_multiplier)
        self._atr = ATR(period=atr_period)

    def generate_signals(self, data: pd.DataFrame) -> list[Signal]:
        """Generate BUY/SELL signals based on Supertrend direction changes.

        Args:
            data: DataFrame with columns: timestamp, open, high, low, close, volume.

        Returns:
            List of Signal objects at Supertrend direction change points.
        """
        min_required = max(self.st_period, self.atr_period) + 2
        if len(data) < min_required:
            return []

        close = data["close"].astype(float)
        high = data["high"].astype(float)
        low = data["low"].astype(float)

        st_df = self._supertrend.calculate(data)
        atr = self._atr.calculate(close, high=high, low=low)

        direction = st_df["direction"]
        supertrend_vals = st_df["supertrend"]

        signals: list[Signal] = []

        for i in range(1, len(data)):
            if pd.isna(direction.iloc[i]) or pd.isna(direction.iloc[i - 1]):
                continue

            prev_dir = float(direction.iloc[i - 1])
            curr_dir = float(direction.iloc[i])

            signal: Signal | None = None
            current_atr = float(atr.iloc[i]) if not pd.isna(atr.iloc[i]) else 0.0
            if current_atr == 0.0:
                continue
            price = float(close.iloc[i])
            ts = data["timestamp"].iloc[i]
            st_value = float(supertrend_vals.iloc[i]) if not pd.isna(supertrend_vals.iloc[i]) else price

            # Bullish: direction changes from -1 to +1
            if prev_dir == -1.0 and curr_dir == 1.0:
                stop_loss = price - (current_atr * self.atr_sl_multiplier)
                target = price + (current_atr * self.atr_sl_multiplier * self.risk_reward_ratio)
                strength = self._assess_strength(price, st_value, current_atr)

                signal = Signal(
                    timestamp=ts,
                    symbol=data.get("symbol", [""])[0] if "symbol" in data.columns else "",
                    signal_type=SignalType.BUY,
                    strength=strength,
                    price=price,
                    stop_loss=round(stop_loss, 2),
                    target=round(target, 2),
                    strategy_name=self.name,
                    metadata={
                        "supertrend": round(st_value, 2),
                        "direction": int(curr_dir),
                        "prev_direction": int(prev_dir),
                        "atr": round(float(current_atr), 2),
                        "trigger": "downtrend_to_uptrend",
                    },
                )

            # Bearish: direction changes from +1 to -1
            elif prev_dir == 1.0 and curr_dir == -1.0:
                stop_loss = price + (current_atr * self.atr_sl_multiplier)
                target = price - (current_atr * self.atr_sl_multiplier * self.risk_reward_ratio)
                strength = self._assess_strength(price, st_value, current_atr)

                signal = Signal(
                    timestamp=ts,
                    symbol=data.get("symbol", [""])[0] if "symbol" in data.columns else "",
                    signal_type=SignalType.SELL,
                    strength=strength,
                    price=price,
                    stop_loss=round(stop_loss, 2),
                    target=round(target, 2),
                    strategy_name=self.name,
                    metadata={
                        "supertrend": round(st_value, 2),
                        "direction": int(curr_dir),
                        "prev_direction": int(prev_dir),
                        "atr": round(float(current_atr), 2),
                        "trigger": "uptrend_to_downtrend",
                    },
                )

            if signal is not None:
                signals.append(signal)

        logger.debug(
            "signals_generated",
            strategy=self.name,
            total=len(signals),
            buys=sum(1 for s in signals if s.signal_type == SignalType.BUY),
            sells=sum(1 for s in signals if s.signal_type == SignalType.SELL),
        )
        return signals

    def _assess_strength(
        self, price: float, supertrend: float, atr: float
    ) -> SignalStrength:
        """Assess signal strength based on price distance from supertrend relative to ATR."""
        if atr == 0:
            return SignalStrength.WEAK
        distance = abs(price - supertrend) / atr
        if distance > 1.5:
            return SignalStrength.STRONG
        elif distance > 0.5:
            return SignalStrength.MODERATE
        return SignalStrength.WEAK

    def __repr__(self) -> str:
        return (
            f"<SupertrendStrategy(period={self.st_period}, "
            f"multiplier={self.st_multiplier}, atr_mult={self.atr_sl_multiplier})>"
        )
