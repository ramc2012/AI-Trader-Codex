"""Bollinger Band Mean Reversion strategy.

Generates BUY when close crosses below lower band with RSI < 30,
and SELL when close crosses above upper band with RSI > 70.
Includes ATR-based stop-loss and risk-reward target calculation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from src.analysis.indicators import ATR, RSI, BollingerBands
from src.strategies.base import BaseStrategy, Signal, SignalStrength, SignalType
from src.utils.logger import get_logger

logger = get_logger(__name__)


class BollingerBandStrategy(BaseStrategy):
    """Mean reversion strategy using Bollinger Bands with RSI confirmation.

    Args:
        bb_period: Bollinger Bands SMA period (default 20).
        bb_std: Bollinger Bands standard deviation multiplier (default 2.0).
        rsi_period: RSI lookback period (default 14).
        atr_period: ATR period for stop-loss (default 14).
        atr_sl_multiplier: ATR multiplier for stop-loss distance (default 1.5).
        risk_reward_ratio: Target distance as multiple of stop distance (default 2.0).
    """

    name = "Bollinger_MeanReversion"

    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        rsi_period: int = 14,
        atr_period: int = 14,
        atr_sl_multiplier: float = 1.5,
        risk_reward_ratio: float = 2.0,
    ) -> None:
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.atr_sl_multiplier = atr_sl_multiplier
        self.risk_reward_ratio = risk_reward_ratio

        self._bb = BollingerBands(period=bb_period, std_dev=bb_std)
        self._rsi = RSI(period=rsi_period)
        self._atr = ATR(period=atr_period)

    def generate_signals(self, data: pd.DataFrame) -> list[Signal]:
        """Generate BUY/SELL signals based on Bollinger Band mean reversion.

        Args:
            data: DataFrame with columns: timestamp, open, high, low, close, volume.

        Returns:
            List of Signal objects at band crossover points with RSI confirmation.
        """
        min_required = max(self.bb_period, self.rsi_period, self.atr_period) + 2
        if len(data) < min_required:
            return []

        close = data["close"].astype(float)
        high = data["high"].astype(float)
        low = data["low"].astype(float)

        bb = self._bb.calculate(close)
        rsi = self._rsi.calculate(close)
        atr = self._atr.calculate(close, high=high, low=low)

        upper_band = bb["upper"]
        lower_band = bb["lower"]
        middle_band = bb["middle"]

        signals: list[Signal] = []

        for i in range(1, len(data)):
            if (
                pd.isna(upper_band.iloc[i])
                or pd.isna(lower_band.iloc[i])
                or pd.isna(rsi.iloc[i])
                or pd.isna(close.iloc[i - 1])
            ):
                continue

            signal: Signal | None = None
            current_atr = atr.iloc[i] if not pd.isna(atr.iloc[i]) else 0
            price = float(close.iloc[i])
            prev_price = float(close.iloc[i - 1])
            ts = data["timestamp"].iloc[i]
            curr_rsi = float(rsi.iloc[i])
            curr_lower = float(lower_band.iloc[i])
            curr_upper = float(upper_band.iloc[i])
            prev_lower = float(lower_band.iloc[i - 1]) if not pd.isna(lower_band.iloc[i - 1]) else curr_lower
            prev_upper = float(upper_band.iloc[i - 1]) if not pd.isna(upper_band.iloc[i - 1]) else curr_upper

            # Bullish: close crosses below lower band with RSI < 30
            if price <= curr_lower and curr_rsi < 30:
                stop_loss = price - (current_atr * self.atr_sl_multiplier)
                target = price + (current_atr * self.atr_sl_multiplier * self.risk_reward_ratio)
                strength = self._assess_strength(curr_rsi, price, curr_lower, curr_upper)

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
                        "upper_band": round(curr_upper, 2),
                        "lower_band": round(curr_lower, 2),
                        "middle_band": round(float(middle_band.iloc[i]), 2) if not pd.isna(middle_band.iloc[i]) else 0.0,
                        "atr": round(float(current_atr), 2),
                        "trigger": "below_lower_band",
                    },
                )

            # Bearish: close crosses above upper band with RSI > 70
            elif price >= curr_upper and curr_rsi > 70:
                stop_loss = price + (current_atr * self.atr_sl_multiplier)
                target = price - (current_atr * self.atr_sl_multiplier * self.risk_reward_ratio)
                strength = self._assess_strength(curr_rsi, price, curr_lower, curr_upper)

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
                        "upper_band": round(curr_upper, 2),
                        "lower_band": round(curr_lower, 2),
                        "middle_band": round(float(middle_band.iloc[i]), 2) if not pd.isna(middle_band.iloc[i]) else 0.0,
                        "atr": round(float(current_atr), 2),
                        "trigger": "above_upper_band",
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
        self, rsi: float, price: float, lower: float, upper: float
    ) -> SignalStrength:
        """Assess signal strength based on band penetration depth and RSI extremity."""
        band_width = upper - lower
        if band_width == 0:
            return SignalStrength.WEAK

        if price <= lower:
            penetration = (lower - price) / band_width
        else:
            penetration = (price - upper) / band_width

        rsi_extremity = max(abs(rsi - 50) - 20, 0) / 30  # 0 to 1 scale

        combined = penetration + rsi_extremity * 0.5
        if combined > 0.3:
            return SignalStrength.STRONG
        elif combined > 0.1:
            return SignalStrength.MODERATE
        return SignalStrength.WEAK

    def __repr__(self) -> str:
        return (
            f"<BollingerBandStrategy(period={self.bb_period}, "
            f"std={self.bb_std}, atr_mult={self.atr_sl_multiplier})>"
        )
