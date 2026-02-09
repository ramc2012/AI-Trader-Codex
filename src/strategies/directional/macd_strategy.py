"""MACD + RSI Confirmation strategy.

Generates BUY when MACD crosses above signal line AND RSI > rsi_filter,
and SELL when MACD crosses below signal line AND RSI < rsi_filter.
Includes ATR-based stop-loss and risk-reward target calculation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from src.analysis.indicators import ATR, MACD, RSI
from src.strategies.base import BaseStrategy, Signal, SignalStrength, SignalType
from src.utils.logger import get_logger

logger = get_logger(__name__)


class MACDStrategy(BaseStrategy):
    """Directional strategy combining MACD crossovers with RSI confirmation.

    Args:
        macd_fast: MACD fast EMA period (default 12).
        macd_slow: MACD slow EMA period (default 26).
        macd_signal: MACD signal line period (default 9).
        rsi_period: RSI lookback period (default 14).
        rsi_filter: RSI threshold for trend confirmation (default 50).
        atr_period: ATR period for stop-loss (default 14).
        atr_sl_multiplier: ATR multiplier for stop-loss distance (default 2.0).
        risk_reward_ratio: Target distance as multiple of stop distance (default 2.0).
    """

    name = "MACD_RSI"

    def __init__(
        self,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        rsi_period: int = 14,
        rsi_filter: float = 50.0,
        atr_period: int = 14,
        atr_sl_multiplier: float = 2.0,
        risk_reward_ratio: float = 2.0,
    ) -> None:
        if macd_fast >= macd_slow:
            raise ValueError(
                f"macd_fast ({macd_fast}) must be < macd_slow ({macd_slow})"
            )
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.rsi_period = rsi_period
        self.rsi_filter = rsi_filter
        self.atr_period = atr_period
        self.atr_sl_multiplier = atr_sl_multiplier
        self.risk_reward_ratio = risk_reward_ratio

        self._macd = MACD(
            fast_period=macd_fast,
            slow_period=macd_slow,
            signal_period=macd_signal,
        )
        self._rsi = RSI(period=rsi_period)
        self._atr = ATR(period=atr_period)

    def generate_signals(self, data: pd.DataFrame) -> list[Signal]:
        """Generate BUY/SELL signals based on MACD crossover with RSI confirmation.

        Args:
            data: DataFrame with columns: timestamp, open, high, low, close, volume.

        Returns:
            List of Signal objects at MACD crossover points confirmed by RSI.
        """
        if len(data) < self.macd_slow + self.macd_signal + 1:
            return []

        close = data["close"].astype(float)
        high = data["high"].astype(float)
        low = data["low"].astype(float)

        macd_df = self._macd.calculate(close)
        rsi = self._rsi.calculate(close)
        atr = self._atr.calculate(close, high=high, low=low)

        macd_line = macd_df["macd"]
        signal_line = macd_df["signal"]

        signals: list[Signal] = []

        for i in range(1, len(data)):
            if (
                pd.isna(macd_line.iloc[i])
                or pd.isna(signal_line.iloc[i])
                or pd.isna(macd_line.iloc[i - 1])
                or pd.isna(signal_line.iloc[i - 1])
                or pd.isna(rsi.iloc[i])
            ):
                continue

            prev_diff = float(macd_line.iloc[i - 1] - signal_line.iloc[i - 1])
            curr_diff = float(macd_line.iloc[i] - signal_line.iloc[i])
            curr_rsi = float(rsi.iloc[i])

            signal: Signal | None = None
            current_atr = atr.iloc[i] if not pd.isna(atr.iloc[i]) else 0
            price = float(close.iloc[i])
            ts = data["timestamp"].iloc[i]

            # Bullish: MACD crosses above signal AND RSI > rsi_filter
            if prev_diff <= 0 and curr_diff > 0 and curr_rsi > self.rsi_filter:
                stop_loss = price - (current_atr * self.atr_sl_multiplier)
                target = price + (current_atr * self.atr_sl_multiplier * self.risk_reward_ratio)
                strength = self._assess_strength(curr_diff, current_atr, curr_rsi)

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
                        "macd": round(float(macd_line.iloc[i]), 2),
                        "macd_signal": round(float(signal_line.iloc[i]), 2),
                        "histogram": round(float(curr_diff), 2),
                        "rsi": round(curr_rsi, 2),
                        "atr": round(float(current_atr), 2),
                    },
                )

            # Bearish: MACD crosses below signal AND RSI < rsi_filter
            elif prev_diff >= 0 and curr_diff < 0 and curr_rsi < self.rsi_filter:
                stop_loss = price + (current_atr * self.atr_sl_multiplier)
                target = price - (current_atr * self.atr_sl_multiplier * self.risk_reward_ratio)
                strength = self._assess_strength(abs(curr_diff), current_atr, curr_rsi)

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
                        "macd": round(float(macd_line.iloc[i]), 2),
                        "macd_signal": round(float(signal_line.iloc[i]), 2),
                        "histogram": round(float(curr_diff), 2),
                        "rsi": round(curr_rsi, 2),
                        "atr": round(float(current_atr), 2),
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
        self, crossover_diff: float, atr: float, rsi: float
    ) -> SignalStrength:
        """Assess signal strength based on MACD crossover magnitude and RSI extremity."""
        if atr == 0:
            return SignalStrength.WEAK
        ratio = crossover_diff / atr
        # Stronger RSI confirmation increases strength
        rsi_bonus = abs(rsi - 50) / 50  # 0 to 1 scale
        combined = ratio + rsi_bonus * 0.3
        if combined > 0.5:
            return SignalStrength.STRONG
        elif combined > 0.2:
            return SignalStrength.MODERATE
        return SignalStrength.WEAK

    def __repr__(self) -> str:
        return (
            f"<MACDStrategy(fast={self.macd_fast}, slow={self.macd_slow}, "
            f"signal={self.macd_signal}, rsi_filter={self.rsi_filter})>"
        )
