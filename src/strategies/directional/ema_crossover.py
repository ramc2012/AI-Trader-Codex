"""EMA Crossover strategy — the first directional strategy.

Generates BUY when fast EMA crosses above slow EMA, and SELL when
fast EMA crosses below slow EMA. Includes ATR-based stop-loss
and risk-reward target calculation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from src.analysis.indicators import ADX, ATR, EMA
from src.strategies.base import BaseStrategy, Signal, SignalStrength, SignalType
from src.utils.logger import get_logger

logger = get_logger(__name__)


class EMACrossoverStrategy(BaseStrategy):
    """Directional strategy based on EMA crossovers with ATR stops.

    Args:
        fast_period: Fast EMA period (default 9).
        slow_period: Slow EMA period (default 21).
        atr_period: ATR period for stop-loss (default 14).
        atr_multiplier: ATR multiplier for stop-loss distance (default 1.5).
        risk_reward: Target distance as multiple of stop distance (default 2.0).
    """

    name = "EMA_Crossover"

    def __init__(
        self,
        fast_period: int = 9,
        slow_period: int = 21,
        atr_period: int = 14,
        atr_multiplier: float = 1.5,
        risk_reward: float = 2.0,
        adx_period: int = 14,
        adx_threshold: float = 20.0,
    ) -> None:
        if fast_period >= slow_period:
            raise ValueError(
                f"fast_period ({fast_period}) must be < slow_period ({slow_period})"
            )
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.atr_period = atr_period
        self.atr_multiplier = atr_multiplier
        self.risk_reward = risk_reward
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold

        self._fast_ema = EMA(period=fast_period)
        self._slow_ema = EMA(period=slow_period)
        self._atr = ATR(period=atr_period)
        self._adx = ADX(period=adx_period)

    def generate_signals(self, data: pd.DataFrame) -> list[Signal]:
        """Generate BUY/SELL signals based on EMA crossovers.

        Args:
            data: DataFrame with columns: timestamp, open, high, low, close, volume.

        Returns:
            List of Signal objects at crossover points.
        """
        if len(data) < self.slow_period + 1:
            return []

        close = data["close"].astype(float)
        high = data["high"].astype(float)
        low = data["low"].astype(float)

        fast = self._fast_ema.calculate(close)
        slow = self._slow_ema.calculate(close)
        atr = self._atr.calculate(close, high=high, low=low)
        adx_series = self._adx.calculate(data)["adx"]

        signals: list[Signal] = []

        for i in range(1, len(data)):
            if pd.isna(fast.iloc[i]) or pd.isna(slow.iloc[i]) or pd.isna(fast.iloc[i - 1]):
                continue

            prev_diff = fast.iloc[i - 1] - slow.iloc[i - 1]
            curr_diff = fast.iloc[i] - slow.iloc[i]

            # ADX trend filter — only trade when trend is strong enough
            current_adx = float(adx_series.iloc[i]) if not pd.isna(adx_series.iloc[i]) else 0.0
            if current_adx < self.adx_threshold:
                continue  # Choppy / sideways market — skip EMA crossover

            signal: Signal | None = None
            current_atr = atr.iloc[i] if not pd.isna(atr.iloc[i]) else 0
            price = float(close.iloc[i])
            ts = data["timestamp"].iloc[i]

            # Bullish crossover: fast crosses above slow
            if prev_diff <= 0 and curr_diff > 0:
                stop_loss = price - (current_atr * self.atr_multiplier)
                target = price + (current_atr * self.atr_multiplier * self.risk_reward)
                strength = self._assess_strength(curr_diff, current_atr)

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
                        "fast_ema": round(float(fast.iloc[i]), 2),
                        "slow_ema": round(float(slow.iloc[i]), 2),
                        "atr": round(float(current_atr), 2),
                        "crossover_diff": round(float(curr_diff), 2),
                        "adx": round(current_adx, 2),
                    },
                )

            # Bearish crossover: fast crosses below slow
            elif prev_diff >= 0 and curr_diff < 0:
                stop_loss = price + (current_atr * self.atr_multiplier)
                target = price - (current_atr * self.atr_multiplier * self.risk_reward)
                strength = self._assess_strength(abs(curr_diff), current_atr)

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
                        "fast_ema": round(float(fast.iloc[i]), 2),
                        "slow_ema": round(float(slow.iloc[i]), 2),
                        "atr": round(float(current_atr), 2),
                        "crossover_diff": round(float(curr_diff), 2),
                        "adx": round(current_adx, 2),
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

    def _assess_strength(self, crossover_diff: float, atr: float) -> SignalStrength:
        """Assess signal strength based on crossover magnitude relative to ATR."""
        if atr == 0:
            return SignalStrength.WEAK
        ratio = crossover_diff / atr
        if ratio > 0.5:
            return SignalStrength.STRONG
        elif ratio > 0.2:
            return SignalStrength.MODERATE
        return SignalStrength.WEAK

    def __repr__(self) -> str:
        return (
            f"<EMACrossoverStrategy(fast={self.fast_period}, "
            f"slow={self.slow_period}, atr_mult={self.atr_multiplier})>"
        )
