"""
Positional options strategy based on MACD zero-line crossovers.

Rules:
- Entry: MACD line crosses above the MACD zero line.
- Exit: RSI > 80 (overbought) or trailing stop-loss.
- Re-entry: Allowed if MACD remains above zero and dips/re-crosses signal line (or simple re-entry above zero).
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
import pandas as pd
import pandas_ta as ta

from src.strategies.base import Signal, SignalType, SignalStrength
from src.strategies.base import BaseStrategy


class OptionsMomentumBuy(BaseStrategy):
    """
    Buys ATM Options (CE or PE) when contract MACD crosses above zero.
    Trails stop-loss and exits on RSI > 80.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.macd_fast = self.config.get("macd_fast", 12)
        self.macd_slow = self.config.get("macd_slow", 26)
        self.macd_signal = self.config.get("macd_signal", 9)
        self.rsi_period = self.config.get("rsi_period", 14)
        self.rsi_overbought = self.config.get("rsi_overbought", 80)
        
        self.trailing_sl_pct = self.config.get("trailing_sl_pct", 0.15)
        self.initial_sl_pct = self.config.get("initial_sl_pct", 0.20)
        self.target_pct = self.config.get("target_pct", 0.50)

    @property
    def min_bars_required(self) -> int:
        return max(self.macd_slow + self.macd_signal, self.rsi_period) + 5

    def generate_signals(
        self,
        data: pd.DataFrame,
        symbol: str = "",
        timeframe: str = "",
        **kwargs,
    ) -> List[Signal]:
        """Generate positional buy signals for options contracts on MACD 0-line cross."""
        if len(data) < self.min_bars_required:
            return []

        df = data.copy()
        
        # Calculate MACD
        macd_df = ta.macd(
            df["close"],
            fast=self.macd_fast,
            slow=self.macd_slow,
            signal=self.macd_signal,
        )
        if macd_df is None or macd_df.empty:
            return []
            
        macd_line = macd_df[f"MACD_{self.macd_fast}_{self.macd_slow}_{self.macd_signal}"]
        
        # Calculate RSI
        rsi = ta.rsi(df["close"], length=self.rsi_period)
        if rsi is None or rsi.empty:
            return []

        df["macd"] = macd_line
        df["rsi"] = rsi

        signals: List[Signal] = []
        
        for i in range(1, len(df)):
            current_macd = df["macd"].iloc[i]
            prev_macd = df["macd"].iloc[i - 1]
            current_rsi = df["rsi"].iloc[i]
            
            # Entry: MACD crosses above zero line
            crossover_zero = prev_macd <= 0 and current_macd > 0
            
            # Re-entry: If already above zero, and momentum kicks in
            # (We keep it strictly to crossing 0 as requested, but can be relaxed)
            is_entry = crossover_zero and current_rsi < self.rsi_overbought
            
            if is_entry:
                price = float(df["close"].iloc[i])
                stop_loss = price * (1.0 - self.initial_sl_pct)
                target = price * (1.0 + self.target_pct)
                
                timestamp = df["timestamp"].iloc[i] if "timestamp" in df.columns else datetime.now()
                
                signals.append(
                    Signal(
                        timestamp=timestamp,
                        symbol=symbol,
                        signal_type=SignalType.BUY,
                        strength=SignalStrength.STRONG,
                        price=price,
                        stop_loss=round(stop_loss, 2),
                        target=round(target, 2),
                        strategy_name=self.__class__.__name__,
                        metadata={
                            "macd_value": round(current_macd, 4),
                            "rsi_value": round(current_rsi, 2),
                            "trailing_sl_pct": self.trailing_sl_pct,
                            "exit_rule": f"RSI > {self.rsi_overbought}",
                        },
                    )
                )

        return signals
