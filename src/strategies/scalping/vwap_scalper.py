"""VWAP Scalping Strategy.

Ultra-short-term strategy using Volume Weighted Average Price (VWAP)
deviation and volume spikes for 1-3 minute scalping trades.

Entry: Price crosses above/below VWAP bands with elevated volume.
Exit: Quick profit target (0.2-0.5%) or time-based exit (5-15 min).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
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


class VWAPScalper(BaseStrategy):
    """VWAP deviation scalping strategy for 1-3 minute timeframes.

    Generates BUY signals when price pulls back to VWAP from below with
    volume confirmation, and SELL signals for the inverse.

    Args:
        vwap_band_multiplier: Standard deviation multiplier for VWAP bands.
        volume_spike_threshold: Minimum volume/average ratio for signal.
        profit_target_pct: Target profit percentage for exit.
        stop_loss_pct: Stop loss percentage.
        max_hold_minutes: Maximum holding time before forced exit.
    """

    name = "vwap_scalper"
    trading_style = TradingStyle.SCALPING

    def __init__(
        self,
        vwap_band_multiplier: float = 1.5,
        volume_spike_threshold: float = 1.5,
        profit_target_pct: float = 0.3,
        stop_loss_pct: float = 0.15,
        max_hold_minutes: int = 10,
    ) -> None:
        self.vwap_band_multiplier = vwap_band_multiplier
        self.volume_spike_threshold = volume_spike_threshold
        self.profit_target_pct = profit_target_pct
        self.stop_loss_pct = stop_loss_pct
        self.max_hold_minutes = max_hold_minutes

    def generate_signals(self, data: pd.DataFrame) -> list[Signal]:
        """Generate scalping signals from intraday data with VWAP analysis."""
        if data is None or len(data) < 20:
            return []

        signals: list[Signal] = []

        # Compute VWAP
        df = data.copy()
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        cumulative_tp_vol = (typical_price * df["volume"]).cumsum()
        cumulative_vol = df["volume"].cumsum()
        df["vwap"] = cumulative_tp_vol / cumulative_vol.replace(0, np.nan)

        # VWAP standard deviation bands
        df["vwap_std"] = ((df["close"] - df["vwap"]) ** 2).expanding().mean().apply(np.sqrt)
        df["vwap_upper"] = df["vwap"] + self.vwap_band_multiplier * df["vwap_std"]
        df["vwap_lower"] = df["vwap"] - self.vwap_band_multiplier * df["vwap_std"]

        # Volume ratio (current vs rolling average)
        vol_ma = df["volume"].rolling(window=20, min_periods=5).mean()
        df["vol_ratio"] = df["volume"] / vol_ma.replace(0, np.nan)

        # Analyze last few candles for signal
        lookback = min(5, len(df))
        recent = df.iloc[-lookback:]

        for i, (idx, row) in enumerate(recent.iterrows()):
            if pd.isna(row.get("vwap")) or pd.isna(row.get("vol_ratio")):
                continue

            close = float(row["close"])
            vwap = float(row["vwap"])
            vol_ratio = float(row["vol_ratio"])
            vwap_lower = float(row["vwap_lower"]) if not pd.isna(row["vwap_lower"]) else vwap * 0.998
            vwap_upper = float(row["vwap_upper"]) if not pd.isna(row["vwap_upper"]) else vwap * 1.002

            # Determine signal strength from volume
            if vol_ratio >= 2.0:
                strength = SignalStrength.STRONG
            elif vol_ratio >= self.volume_spike_threshold:
                strength = SignalStrength.MODERATE
            else:
                continue  # Not enough volume for scalping

            timestamp = row.get("timestamp", datetime.now())
            if isinstance(timestamp, str):
                try:
                    timestamp = datetime.fromisoformat(timestamp)
                except ValueError:
                    timestamp = datetime.now()
            symbol = row.get("symbol", data.attrs.get("symbol", ""))

            # BUY: Price bounces off lower VWAP band
            if close <= vwap_lower and i < lookback - 1:
                # Check if next candle bounces
                next_row = recent.iloc[i + 1] if i + 1 < len(recent) else None
                if next_row is not None and float(next_row["close"]) > close:
                    target = close * (1 + self.profit_target_pct / 100)
                    stop = close * (1 - self.stop_loss_pct / 100)
                    signals.append(Signal(
                        timestamp=timestamp,
                        symbol=str(symbol),
                        signal_type=SignalType.BUY,
                        strength=strength,
                        trading_style=TradingStyle.SCALPING,
                        price=close,
                        stop_loss=stop,
                        target=target,
                        strategy_name=self.name,
                        holding_period_minutes=self.max_hold_minutes,
                        metadata={
                            "vwap": vwap,
                            "vol_ratio": round(vol_ratio, 2),
                            "band": "lower",
                        },
                    ))

            # SELL: Price rejected at upper VWAP band
            elif close >= vwap_upper and i < lookback - 1:
                next_row = recent.iloc[i + 1] if i + 1 < len(recent) else None
                if next_row is not None and float(next_row["close"]) < close:
                    target = close * (1 - self.profit_target_pct / 100)
                    stop = close * (1 + self.stop_loss_pct / 100)
                    signals.append(Signal(
                        timestamp=timestamp,
                        symbol=str(symbol),
                        signal_type=SignalType.SELL,
                        strength=strength,
                        trading_style=TradingStyle.SCALPING,
                        price=close,
                        stop_loss=stop,
                        target=target,
                        strategy_name=self.name,
                        holding_period_minutes=self.max_hold_minutes,
                        metadata={
                            "vwap": vwap,
                            "vol_ratio": round(vol_ratio, 2),
                            "band": "upper",
                        },
                    ))

        return signals
