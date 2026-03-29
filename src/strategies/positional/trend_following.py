"""Positional Trading Strategies.

Long-term strategies using daily/weekly charts for multi-week positions.
Includes trend following (EMA crossover) and sector rotation (relative strength).
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


class TrendFollowingStrategy(BaseStrategy):
    """EMA crossover trend-following strategy for positional trades.

    Uses dual EMA crossover (50/200) on daily charts with weekly trend
    confirmation. Generates signals when fast EMA crosses slow EMA with
    trend alignment.

    Args:
        fast_ema: Fast EMA period (e.g., 50).
        slow_ema: Slow EMA period (e.g., 200).
        confirm_ema: Weekly confirmation EMA period.
        profit_target_pct: Target profit percentage.
        stop_loss_pct: Stop loss percentage.
        max_hold_weeks: Maximum holding period in weeks.
    """

    name = "trend_following"
    trading_style = TradingStyle.POSITIONAL

    def __init__(
        self,
        fast_ema: int = 50,
        slow_ema: int = 200,
        confirm_ema: int = 20,
        profit_target_pct: float = 8.0,
        stop_loss_pct: float = 4.0,
        max_hold_weeks: int = 8,
    ) -> None:
        self.fast_ema = fast_ema
        self.slow_ema = slow_ema
        self.confirm_ema = confirm_ema
        self.profit_target_pct = profit_target_pct
        self.stop_loss_pct = stop_loss_pct
        self.max_hold_weeks = max_hold_weeks

    def generate_signals(self, data: pd.DataFrame) -> list[Signal]:
        """Generate positional signals from EMA crossover."""
        if data is None or len(data) < self.slow_ema + 5:
            return []

        signals: list[Signal] = []
        df = data.copy()

        # Calculate EMAs
        df["ema_fast"] = df["close"].ewm(span=self.fast_ema, adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=self.slow_ema, adjust=False).mean()
        df["ema_confirm"] = df["close"].ewm(span=self.confirm_ema, adjust=False).mean()

        # Detect crossovers in recent bars
        if len(df) < 3:
            return signals

        curr = df.iloc[-1]
        prev = df.iloc[-2]

        ema_fast_curr = float(curr["ema_fast"])
        ema_slow_curr = float(curr["ema_slow"])
        ema_fast_prev = float(prev["ema_fast"])
        ema_slow_prev = float(prev["ema_slow"])
        ema_confirm = float(curr["ema_confirm"])
        close = float(curr["close"])
        symbol = df.attrs.get("symbol", "")

        # Golden cross: fast EMA crosses above slow EMA
        if ema_fast_prev <= ema_slow_prev and ema_fast_curr > ema_slow_curr:
            # Confirm with shorter EMA trend
            if close > ema_confirm:
                strength = SignalStrength.STRONG if (ema_fast_curr - ema_slow_curr) / ema_slow_curr > 0.005 else SignalStrength.MODERATE
                signals.append(Signal(
                    timestamp=datetime.now(),
                    symbol=str(symbol),
                    signal_type=SignalType.BUY,
                    strength=strength,
                    trading_style=TradingStyle.POSITIONAL,
                    price=close,
                    stop_loss=close * (1 - self.stop_loss_pct / 100),
                    target=close * (1 + self.profit_target_pct / 100),
                    strategy_name=self.name,
                    holding_period_minutes=self.max_hold_weeks * 5 * 390,
                    metadata={
                        "crossover": "golden",
                        "ema_fast": round(ema_fast_curr, 2),
                        "ema_slow": round(ema_slow_curr, 2),
                        "ema_confirm": round(ema_confirm, 2),
                    },
                ))

        # Death cross: fast EMA crosses below slow EMA
        elif ema_fast_prev >= ema_slow_prev and ema_fast_curr < ema_slow_curr:
            if close < ema_confirm:
                strength = SignalStrength.STRONG if (ema_slow_curr - ema_fast_curr) / ema_slow_curr > 0.005 else SignalStrength.MODERATE
                signals.append(Signal(
                    timestamp=datetime.now(),
                    symbol=str(symbol),
                    signal_type=SignalType.SELL,
                    strength=strength,
                    trading_style=TradingStyle.POSITIONAL,
                    price=close,
                    stop_loss=close * (1 + self.stop_loss_pct / 100),
                    target=close * (1 - self.profit_target_pct / 100),
                    strategy_name=self.name,
                    holding_period_minutes=self.max_hold_weeks * 5 * 390,
                    metadata={
                        "crossover": "death",
                        "ema_fast": round(ema_fast_curr, 2),
                        "ema_slow": round(ema_slow_curr, 2),
                        "ema_confirm": round(ema_confirm, 2),
                    },
                ))

        return signals


class SectorRotationStrategy(BaseStrategy):
    """Relative Rotation Graph (RRG) inspired sector rotation strategy.

    Compares each symbol's relative strength (RS) and RS momentum
    against a benchmark to identify leading/lagging sectors.

    Buys symbols rotating into the 'Leading' quadrant (strong RS + improving),
    sells symbols rotating into the 'Lagging' quadrant (weak RS + weakening).

    Args:
        rs_period: Period for relative strength calculation.
        momentum_period: Period for RS momentum.
        benchmark_column: Column name for benchmark price.
        profit_target_pct: Target profit percentage.
        stop_loss_pct: Stop loss percentage.
    """

    name = "sector_rotation"
    trading_style = TradingStyle.POSITIONAL

    def __init__(
        self,
        rs_period: int = 14,
        momentum_period: int = 5,
        benchmark_column: str = "benchmark_close",
        profit_target_pct: float = 6.0,
        stop_loss_pct: float = 3.0,
    ) -> None:
        self.rs_period = rs_period
        self.momentum_period = momentum_period
        self.benchmark_column = benchmark_column
        self.profit_target_pct = profit_target_pct
        self.stop_loss_pct = stop_loss_pct

    def generate_signals(self, data: pd.DataFrame) -> list[Signal]:
        """Generate signals based on relative strength rotation."""
        if data is None or len(data) < self.rs_period + self.momentum_period + 5:
            return []

        if self.benchmark_column not in data.columns:
            return []

        signals: list[Signal] = []
        df = data.copy()

        # Calculate Relative Strength
        df["rs_ratio"] = (df["close"] / df[self.benchmark_column]) * 100
        df["rs_ratio_ma"] = df["rs_ratio"].rolling(window=self.rs_period).mean()

        # Normalize RS to 100 baseline
        if df["rs_ratio_ma"].iloc[0] > 0:
            df["rs_normalized"] = (df["rs_ratio"] / df["rs_ratio_ma"]) * 100
        else:
            return signals

        # RS Momentum (rate of change of RS)
        df["rs_momentum"] = df["rs_normalized"].diff(self.momentum_period)

        if pd.isna(df["rs_normalized"].iloc[-1]) or pd.isna(df["rs_momentum"].iloc[-1]):
            return signals

        rs = float(df["rs_normalized"].iloc[-1])
        momentum = float(df["rs_momentum"].iloc[-1])
        close = float(df["close"].iloc[-1])
        symbol = df.attrs.get("symbol", "")

        # Leading quadrant: RS > 100 and momentum > 0
        if rs > 100 and momentum > 0:
            prev_rs = float(df["rs_normalized"].iloc[-2]) if len(df) > 1 else 0
            prev_mom = float(df["rs_momentum"].iloc[-2]) if len(df) > 1 and not pd.isna(df["rs_momentum"].iloc[-2]) else 0

            # Just entered leading quadrant
            if prev_rs <= 100 or prev_mom <= 0:
                signals.append(Signal(
                    timestamp=datetime.now(),
                    symbol=str(symbol),
                    signal_type=SignalType.BUY,
                    strength=SignalStrength.STRONG if momentum > 1.0 else SignalStrength.MODERATE,
                    trading_style=TradingStyle.POSITIONAL,
                    price=close,
                    stop_loss=close * (1 - self.stop_loss_pct / 100),
                    target=close * (1 + self.profit_target_pct / 100),
                    strategy_name=self.name,
                    holding_period_minutes=4 * 5 * 390,  # ~4 weeks
                    metadata={
                        "rrg_quadrant": "leading",
                        "rs": round(rs, 2),
                        "momentum": round(momentum, 2),
                    },
                ))

        # Lagging quadrant: RS < 100 and momentum < 0
        elif rs < 100 and momentum < 0:
            prev_rs = float(df["rs_normalized"].iloc[-2]) if len(df) > 1 else 100
            prev_mom = float(df["rs_momentum"].iloc[-2]) if len(df) > 1 and not pd.isna(df["rs_momentum"].iloc[-2]) else 0

            # Just entered lagging quadrant
            if prev_rs >= 100 or prev_mom >= 0:
                signals.append(Signal(
                    timestamp=datetime.now(),
                    symbol=str(symbol),
                    signal_type=SignalType.SELL,
                    strength=SignalStrength.STRONG if abs(momentum) > 1.0 else SignalStrength.MODERATE,
                    trading_style=TradingStyle.POSITIONAL,
                    price=close,
                    stop_loss=close * (1 + self.stop_loss_pct / 100),
                    target=close * (1 - self.profit_target_pct / 100),
                    strategy_name=self.name,
                    holding_period_minutes=4 * 5 * 390,
                    metadata={
                        "rrg_quadrant": "lagging",
                        "rs": round(rs, 2),
                        "momentum": round(momentum, 2),
                    },
                ))

        return signals
