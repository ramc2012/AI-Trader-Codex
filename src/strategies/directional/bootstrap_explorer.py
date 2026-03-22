"""Research-friendly implementation of the Bootstrap_Explorer heuristic."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from src.strategies.base import BaseStrategy, Signal, SignalStrength, SignalType


class BootstrapExplorerStrategy(BaseStrategy):
    """Replay the bootstrap fallback logic as a normal strategy.

    This mirrors the heuristic used by the live trading agent's
    internal Bootstrap_Explorer path, but keeps it available for
    offline research and backtesting without changing live behavior.
    """

    name = "Bootstrap_Explorer"

    def __init__(
        self,
        min_bars: int = 8,
        ema_fast_period: int = 5,
        ema_slow_period: int = 13,
        momentum_lookback: int = 3,
        volatility_window: int = 20,
        volatility_multiplier: float = 1.8,
        min_risk_pct: float = 0.004,
        max_risk_pct: float = 0.02,
    ) -> None:
        self.min_bars = max(int(min_bars), 4)
        self.ema_fast_period = max(int(ema_fast_period), 2)
        self.ema_slow_period = max(int(ema_slow_period), self.ema_fast_period + 1)
        self.momentum_lookback = max(int(momentum_lookback), 1)
        self.volatility_window = max(int(volatility_window), 2)
        self.volatility_multiplier = max(float(volatility_multiplier), 0.1)
        self.min_risk_pct = max(float(min_risk_pct), 0.0001)
        self.max_risk_pct = max(float(max_risk_pct), self.min_risk_pct)

    def generate_signals(self, data: pd.DataFrame) -> list[Signal]:
        if data is None or data.empty or len(data) < self.min_bars:
            return []

        working = data.copy(deep=False)
        working["close"] = pd.to_numeric(working.get("close"), errors="coerce")
        working = working.dropna(subset=["close"]).reset_index(drop=True)
        if len(working) < self.min_bars:
            return []

        closes = working["close"].astype(float)
        ema_fast = closes.ewm(span=self.ema_fast_period, adjust=False).mean()
        ema_slow = closes.ewm(span=self.ema_slow_period, adjust=False).mean()
        momentum = closes - closes.shift(self.momentum_lookback)
        volatility = closes.pct_change().abs().rolling(self.volatility_window, min_periods=1).mean()
        risk_pct = (volatility * self.volatility_multiplier).clip(lower=self.min_risk_pct, upper=self.max_risk_pct)

        symbol = ""
        if "symbol" in working.columns and not working.empty:
            symbol = str(working["symbol"].iloc[-1] or "").strip()

        signals: list[Signal] = []
        for index in range(self.min_bars - 1, len(working)):
            now_price = float(closes.iloc[index])
            if now_price <= 0:
                continue

            fast_value = float(ema_fast.iloc[index])
            slow_value = float(ema_slow.iloc[index])
            momentum_value = float(momentum.iloc[index]) if not pd.isna(momentum.iloc[index]) else 0.0
            volatility_value = float(volatility.iloc[index]) if not pd.isna(volatility.iloc[index]) else 0.0
            risk_value = float(risk_pct.iloc[index]) if not pd.isna(risk_pct.iloc[index]) else self.min_risk_pct

            signal_type = SignalType.BUY
            if now_price < fast_value or (fast_value < slow_value and momentum_value < 0):
                signal_type = SignalType.SELL

            if signal_type == SignalType.BUY:
                stop_loss = now_price * (1.0 - risk_value)
                target = now_price * (1.0 + (risk_value * 1.6))
            else:
                stop_loss = now_price * (1.0 + risk_value)
                target = now_price * (1.0 - (risk_value * 1.6))

            timestamp_value = working["timestamp"].iloc[index] if "timestamp" in working.columns else working.index[index]
            timestamp = pd.to_datetime(timestamp_value).to_pydatetime()
            if not isinstance(timestamp, datetime):
                continue

            signals.append(
                Signal(
                    timestamp=timestamp,
                    symbol=symbol,
                    signal_type=signal_type,
                    strength=SignalStrength.WEAK,
                    price=round(now_price, 2),
                    stop_loss=round(float(stop_loss), 2),
                    target=round(float(target), 2),
                    strategy_name=self.name,
                    metadata={
                        "bootstrap_exploration": True,
                        "ema_fast": round(fast_value, 4),
                        "ema_slow": round(slow_value, 4),
                        "momentum": round(momentum_value, 4),
                        "volatility_pct": round(volatility_value * 100.0, 4),
                    },
                )
            )
        return signals

    def __repr__(self) -> str:
        return (
            f"<BootstrapExplorerStrategy(fast={self.ema_fast_period}, "
            f"slow={self.ema_slow_period}, momentum={self.momentum_lookback})>"
        )
