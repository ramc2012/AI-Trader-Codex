"""RSI Reversal strategy.

Generates BUY when RSI crosses above oversold level from below,
and SELL when RSI crosses below overbought level from above.
Includes ATR-based stop-loss and risk-reward target calculation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from src.analysis.indicators import ATR, RSI
from src.strategies.base import BaseStrategy, Signal, SignalStrength, SignalType
from src.utils.logger import get_logger

logger = get_logger(__name__)


class RSIReversalStrategy(BaseStrategy):
    """Directional strategy based on RSI oversold/overbought reversals with ATR stops.

    Args:
        rsi_period: RSI lookback period (default 14).
        oversold: RSI oversold threshold (default 30).
        overbought: RSI overbought threshold (default 70).
        atr_period: ATR period for stop-loss (default 14).
        atr_sl_multiplier: ATR multiplier for stop-loss distance (default 1.5).
        risk_reward_ratio: Target distance as multiple of stop distance (default 2.0).
    """

    name = "RSI_Reversal"

    def __init__(
        self,
        rsi_period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
        atr_period: int = 14,
        atr_sl_multiplier: float = 1.5,
        risk_reward_ratio: float = 2.0,
        volume_surge_multiplier: float = 1.5,
        volume_ma_period: int = 20,
        require_volume_surge: bool = True,
    ) -> None:
        if oversold >= overbought:
            raise ValueError(
                f"oversold ({oversold}) must be < overbought ({overbought})"
            )
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.overbought = overbought
        self.atr_period = atr_period
        self.atr_sl_multiplier = atr_sl_multiplier
        self.risk_reward_ratio = risk_reward_ratio
        self.volume_surge_multiplier = volume_surge_multiplier
        self.volume_ma_period = volume_ma_period
        self.require_volume_surge = require_volume_surge

        self._rsi = RSI(period=rsi_period)
        self._atr = ATR(period=atr_period)

    def generate_signals(self, data: pd.DataFrame) -> list[Signal]:
        """Generate BUY/SELL signals based on RSI reversals.

        Args:
            data: DataFrame with columns: timestamp, open, high, low, close, volume.

        Returns:
            List of Signal objects at RSI crossover points.
        """
        if len(data) < self.rsi_period + 2:
            return []

        close = data["close"].astype(float)
        high = data["high"].astype(float)
        low = data["low"].astype(float)
        volume = data["volume"].astype(float) if "volume" in data.columns else None

        rsi = self._rsi.calculate(close)
        atr = self._atr.calculate(close, high=high, low=low)

        # Volume moving average for surge detection
        volume_ma = (
            volume.rolling(window=self.volume_ma_period, min_periods=1).mean()
            if volume is not None
            else None
        )

        signals: list[Signal] = []

        for i in range(1, len(data)):
            if pd.isna(rsi.iloc[i]) or pd.isna(rsi.iloc[i - 1]):
                continue

            # Volume surge filter: skip if volume is not elevated
            volume_ratio = 1.0
            volume_surge = True
            if self.require_volume_surge and volume_ma is not None:
                vol_ma_val = float(volume_ma.iloc[i]) if not pd.isna(volume_ma.iloc[i]) else 0.0
                vol_val = float(volume.iloc[i]) if not pd.isna(volume.iloc[i]) else 0.0
                volume_ratio = (vol_val / vol_ma_val) if vol_ma_val > 0 else 1.0
                volume_surge = volume_ratio >= self.volume_surge_multiplier
                if not volume_surge:
                    continue

            signal: Signal | None = None
            current_atr = atr.iloc[i] if not pd.isna(atr.iloc[i]) else 0
            price = float(close.iloc[i])
            ts = data["timestamp"].iloc[i]
            prev_rsi = float(rsi.iloc[i - 1])
            curr_rsi = float(rsi.iloc[i])

            # Bullish reversal: RSI crosses above oversold from below
            if prev_rsi <= self.oversold and curr_rsi > self.oversold:
                stop_loss = price - (current_atr * self.atr_sl_multiplier)
                target = price + (current_atr * self.atr_sl_multiplier * self.risk_reward_ratio)
                strength = self._assess_strength(curr_rsi, "buy")

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
                        "rsi": round(curr_rsi, 2),
                        "prev_rsi": round(prev_rsi, 2),
                        "atr": round(float(current_atr), 2),
                        "trigger": "oversold_crossover",
                        "volume_surge": volume_surge,
                        "volume_ratio": round(volume_ratio, 2),
                    },
                )

            # Bearish reversal: RSI crosses below overbought from above
            elif prev_rsi >= self.overbought and curr_rsi < self.overbought:
                stop_loss = price + (current_atr * self.atr_sl_multiplier)
                target = price - (current_atr * self.atr_sl_multiplier * self.risk_reward_ratio)
                strength = self._assess_strength(curr_rsi, "sell")

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
                        "rsi": round(curr_rsi, 2),
                        "prev_rsi": round(prev_rsi, 2),
                        "atr": round(float(current_atr), 2),
                        "trigger": "overbought_crossover",
                        "volume_surge": volume_surge,
                        "volume_ratio": round(volume_ratio, 2),
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

    def _assess_strength(self, rsi_value: float, side: str) -> SignalStrength:
        """Assess signal strength based on RSI extremity.

        Stronger signals come from more extreme RSI values.
        """
        if side == "buy":
            # The lower the RSI was, the stronger the reversal signal
            if rsi_value < 25:
                return SignalStrength.STRONG
            elif rsi_value < 35:
                return SignalStrength.MODERATE
            return SignalStrength.WEAK
        else:
            # The higher the RSI was, the stronger the reversal signal
            if rsi_value > 75:
                return SignalStrength.STRONG
            elif rsi_value > 65:
                return SignalStrength.MODERATE
            return SignalStrength.WEAK

    def __repr__(self) -> str:
        return (
            f"<RSIReversalStrategy(rsi_period={self.rsi_period}, "
            f"oversold={self.oversold}, overbought={self.overbought}, "
            f"atr_mult={self.atr_sl_multiplier})>"
        )
