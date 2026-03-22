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
        rsi_filter: RSI threshold for trend confirmation (default 52).
        atr_period: ATR period for stop-loss (default 14).
        atr_sl_multiplier: ATR multiplier for stop-loss distance (default 1.5).
        risk_reward_ratio: Target distance as multiple of stop distance (default 2.2).
    """

    name = "MACD_RSI"

    def __init__(
        self,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        rsi_period: int = 14,
        rsi_filter: float = 52.0,
        atr_period: int = 14,
        atr_sl_multiplier: float = 1.5,
        risk_reward_ratio: float = 2.2,
        zero_line_mode: str | None = None,
        buy_zero_line_mode: str | None = None,
        sell_zero_line_mode: str | None = None,
        max_zero_line_distance_atr: float = 0.25,
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
        legacy_zero_line_mode = self._normalize_zero_line_mode(zero_line_mode, "zero_line_mode")
        self.buy_zero_line_mode = self._normalize_zero_line_mode(
            buy_zero_line_mode if buy_zero_line_mode is not None else legacy_zero_line_mode or "near_or_aligned",
            "buy_zero_line_mode",
        )
        self.sell_zero_line_mode = self._normalize_zero_line_mode(
            sell_zero_line_mode if sell_zero_line_mode is not None else legacy_zero_line_mode or "aligned",
            "sell_zero_line_mode",
        )
        if self.buy_zero_line_mode == self.sell_zero_line_mode:
            self.zero_line_mode = self.buy_zero_line_mode
        else:
            self.zero_line_mode = "asymmetric"
        self.max_zero_line_distance_atr = max(float(max_zero_line_distance_atr), 0.0)

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
            if current_atr <= 0:
                continue
            price = float(close.iloc[i])
            ts = data["timestamp"].iloc[i]
            curr_macd = float(macd_line.iloc[i])

            # Bullish: MACD crosses above signal AND RSI > rsi_filter
            if (
                prev_diff <= 0
                and curr_diff > 0
                and curr_rsi > self.rsi_filter
                and self._zero_line_allows_entry(curr_macd, current_atr, SignalType.BUY)
            ):
                stop_loss = price - (current_atr * self.atr_sl_multiplier)
                target = price + (current_atr * self.atr_sl_multiplier * self.risk_reward_ratio)
                strength = self._assess_strength(curr_diff, current_atr, curr_rsi, curr_macd, SignalType.BUY)

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
                        "macd": round(curr_macd, 2),
                        "macd_signal": round(float(signal_line.iloc[i]), 2),
                        "histogram": round(float(curr_diff), 2),
                        "rsi": round(curr_rsi, 2),
                        "atr": round(float(current_atr), 2),
                        "zero_line_mode": self.zero_line_mode,
                        "buy_zero_line_mode": self.buy_zero_line_mode,
                        "sell_zero_line_mode": self.sell_zero_line_mode,
                        "active_zero_line_mode": self.buy_zero_line_mode,
                        "zero_line_aligned": curr_macd >= 0,
                        "zero_line_distance_atr": round(abs(curr_macd) / current_atr, 4),
                    },
                )

            # Bearish: MACD crosses below signal AND RSI < rsi_filter
            elif (
                prev_diff >= 0
                and curr_diff < 0
                and curr_rsi < self.rsi_filter
                and self._zero_line_allows_entry(curr_macd, current_atr, SignalType.SELL)
            ):
                stop_loss = price + (current_atr * self.atr_sl_multiplier)
                target = price - (current_atr * self.atr_sl_multiplier * self.risk_reward_ratio)
                strength = self._assess_strength(abs(curr_diff), current_atr, curr_rsi, curr_macd, SignalType.SELL)

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
                        "macd": round(curr_macd, 2),
                        "macd_signal": round(float(signal_line.iloc[i]), 2),
                        "histogram": round(float(curr_diff), 2),
                        "rsi": round(curr_rsi, 2),
                        "atr": round(float(current_atr), 2),
                        "zero_line_mode": self.zero_line_mode,
                        "buy_zero_line_mode": self.buy_zero_line_mode,
                        "sell_zero_line_mode": self.sell_zero_line_mode,
                        "active_zero_line_mode": self.sell_zero_line_mode,
                        "zero_line_aligned": curr_macd <= 0,
                        "zero_line_distance_atr": round(abs(curr_macd) / current_atr, 4),
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
        self,
        crossover_diff: float,
        atr: float,
        rsi: float,
        macd_value: float,
        side: SignalType,
    ) -> SignalStrength:
        """Assess signal strength based on MACD crossover magnitude and RSI extremity."""
        if atr == 0:
            return SignalStrength.WEAK
        ratio = crossover_diff / atr
        # Stronger RSI confirmation increases strength
        rsi_bonus = abs(rsi - 50) / 50  # 0 to 1 scale
        zero_line_bonus = 0.0
        if side == SignalType.BUY:
            if macd_value >= 0:
                zero_line_bonus = 0.2
            elif abs(macd_value) / atr <= self.max_zero_line_distance_atr:
                zero_line_bonus = 0.08
        else:
            if macd_value <= 0:
                zero_line_bonus = 0.2
            elif abs(macd_value) / atr <= self.max_zero_line_distance_atr:
                zero_line_bonus = 0.08
        combined = ratio + rsi_bonus * 0.3 + zero_line_bonus
        if combined > 0.5:
            return SignalStrength.STRONG
        elif combined > 0.2:
            return SignalStrength.MODERATE
        return SignalStrength.WEAK

    @staticmethod
    def _normalize_zero_line_mode(mode: str | None, field_name: str) -> str | None:
        if mode is None:
            return None
        normalized = str(mode).strip().lower()
        if normalized not in {"off", "aligned", "near_or_aligned"}:
            raise ValueError(
                f"{field_name} must be one of: off, aligned, near_or_aligned"
            )
        return normalized

    def _zero_line_allows_entry(self, macd_value: float, atr: float, side: SignalType) -> bool:
        zero_line_mode = (
            self.buy_zero_line_mode if side == SignalType.BUY else self.sell_zero_line_mode
        )
        if zero_line_mode == "off":
            return True
        if atr <= 0:
            return False

        if side == SignalType.BUY:
            aligned = macd_value >= 0
        else:
            aligned = macd_value <= 0
        if aligned:
            return True
        if zero_line_mode == "aligned":
            return False
        return (abs(macd_value) / atr) <= self.max_zero_line_distance_atr

    def __repr__(self) -> str:
        return (
            f"<MACDStrategy(fast={self.macd_fast}, slow={self.macd_slow}, "
            f"signal={self.macd_signal}, rsi_filter={self.rsi_filter}, "
            f"buy_zero_line_mode={self.buy_zero_line_mode}, "
            f"sell_zero_line_mode={self.sell_zero_line_mode})>"
        )
