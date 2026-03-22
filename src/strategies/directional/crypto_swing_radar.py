"""Crypto swing strategy using 4h execution and daily trend context."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from src.analysis.indicators import ATR
from src.strategies.base import BaseStrategy, Signal, SignalStrength, SignalType
from src.strategies.directional.swing_thresholds import resolve_learning_thresholds


class CryptoSwingRadarStrategy(BaseStrategy):
    """Trade multi-session crypto swings using daily trend and 4h execution."""

    name = "Crypto_Swing_Radar"

    def __init__(
        self,
        preferred_execution_timeframe: str = "240",
        min_signal_score: float = 67.0,
        min_direction_probability: float = 0.44,
        min_direction_edge: float = 0.045,
        min_daily_bars: int = 90,
        min_execution_bars: int = 90,
    ) -> None:
        self.preferred_execution_timeframe = str(preferred_execution_timeframe).strip().upper()
        self.min_signal_score = float(min_signal_score)
        self.min_direction_probability = float(min_direction_probability)
        self.min_direction_edge = float(min_direction_edge)
        self.min_daily_bars = int(min_daily_bars)
        self.min_execution_bars = int(min_execution_bars)
        self._daily_atr = ATR(period=14)
        self._execution_atr = ATR(period=14)

    def generate_signals(self, data: pd.DataFrame) -> list[Signal]:
        if data is None or data.empty:
            return []

        context = getattr(self, "_runtime_context", {}) or {}
        execution_timeframe = str(context.get("execution_timeframe") or "").strip().upper()
        if execution_timeframe and execution_timeframe != self.preferred_execution_timeframe:
            return []

        execution_frame = self._normalize_frame(data)
        daily_frame = self._normalize_frame(context.get("daily_frame"))
        benchmark_daily_frame = self._normalize_frame(context.get("benchmark_daily_frame"))
        if execution_frame is None or daily_frame is None or benchmark_daily_frame is None:
            return []
        if len(execution_frame) < self.min_execution_bars:
            return []
        if len(daily_frame) < self.min_daily_bars or len(benchmark_daily_frame) < self.min_daily_bars:
            return []

        symbol = str(
            context.get("symbol")
            or (execution_frame["symbol"].iloc[-1] if "symbol" in execution_frame.columns and not execution_frame.empty else "")
            or ""
        ).strip()
        if not symbol or not symbol.startswith("CRYPTO:"):
            return []

        daily_closes = pd.to_numeric(daily_frame["close"], errors="coerce")
        daily_highs = pd.to_numeric(daily_frame["high"], errors="coerce")
        daily_lows = pd.to_numeric(daily_frame["low"], errors="coerce")
        benchmark_closes = pd.to_numeric(benchmark_daily_frame["close"], errors="coerce")
        execution_closes = pd.to_numeric(execution_frame["close"], errors="coerce")
        execution_highs = pd.to_numeric(execution_frame["high"], errors="coerce")
        execution_lows = pd.to_numeric(execution_frame["low"], errors="coerce")
        execution_volumes = pd.to_numeric(execution_frame["volume"], errors="coerce").fillna(0.0)
        if any(series.isna().all() for series in (daily_closes, benchmark_closes, execution_closes)):
            return []

        current_price = float(execution_closes.iloc[-1])
        if current_price <= 0:
            return []

        daily_ema_fast = float(daily_closes.ewm(span=21, adjust=False).mean().iloc[-1])
        daily_ema_slow = float(daily_closes.ewm(span=55, adjust=False).mean().iloc[-1])
        benchmark_ema_fast = float(benchmark_closes.ewm(span=21, adjust=False).mean().iloc[-1])
        benchmark_ema_slow = float(benchmark_closes.ewm(span=55, adjust=False).mean().iloc[-1])
        execution_ema_fast = float(execution_closes.ewm(span=20, adjust=False).mean().iloc[-1])
        execution_ema_slow = float(execution_closes.ewm(span=50, adjust=False).mean().iloc[-1])

        daily_trend_up = daily_closes.iloc[-1] > daily_ema_fast > daily_ema_slow
        daily_trend_down = daily_closes.iloc[-1] < daily_ema_fast < daily_ema_slow
        benchmark_up = benchmark_closes.iloc[-1] > benchmark_ema_fast > benchmark_ema_slow
        benchmark_down = benchmark_closes.iloc[-1] < benchmark_ema_fast < benchmark_ema_slow
        execution_up = execution_closes.iloc[-1] > execution_ema_fast > execution_ema_slow
        execution_down = execution_closes.iloc[-1] < execution_ema_fast < execution_ema_slow

        lookback_daily = min(20, len(daily_closes) - 1, len(benchmark_closes) - 1)
        if lookback_daily < 5:
            return []
        symbol_return = float((daily_closes.iloc[-1] / max(float(daily_closes.iloc[-1 - lookback_daily]), 1e-6)) - 1.0)
        benchmark_return = float(
            (benchmark_closes.iloc[-1] / max(float(benchmark_closes.iloc[-1 - lookback_daily]), 1e-6)) - 1.0
        )
        relative_strength = symbol_return - benchmark_return

        breakout_lookback = min(18, len(execution_frame) - 2)
        if breakout_lookback < 8:
            return []
        prior_high = float(execution_highs.iloc[-1 - breakout_lookback:-1].max())
        prior_low = float(execution_lows.iloc[-1 - breakout_lookback:-1].min())
        breakout_up = current_price >= prior_high
        breakout_down = current_price <= prior_low

        avg_volume = float(execution_volumes.tail(20).mean() or 0.0)
        volume_ratio = float(execution_volumes.iloc[-1] / max(avg_volume, 1.0))

        daily_atr_series = self._daily_atr.calculate(daily_closes, high=daily_highs, low=daily_lows)
        execution_atr_series = self._execution_atr.calculate(execution_closes, high=execution_highs, low=execution_lows)
        daily_atr = float(daily_atr_series.iloc[-1]) if not pd.isna(daily_atr_series.iloc[-1]) else current_price * 0.03
        execution_atr = (
            float(execution_atr_series.iloc[-1]) if not pd.isna(execution_atr_series.iloc[-1]) else current_price * 0.015
        )
        daily_atr_pct = daily_atr / max(float(daily_closes.iloc[-1]), 1e-6)

        bullish_score = 0.0
        bearish_score = 0.0
        if daily_trend_up:
            bullish_score += 22.0
        if daily_trend_down:
            bearish_score += 22.0
        if benchmark_up:
            bullish_score += 8.0
        if benchmark_down:
            bearish_score += 8.0
        if execution_up:
            bullish_score += 18.0
        if execution_down:
            bearish_score += 18.0
        if breakout_up:
            bullish_score += 14.0
        if breakout_down:
            bearish_score += 14.0

        rs_component = max(min(relative_strength * 220.0, 16.0), -16.0)
        bullish_score += max(rs_component, 0.0)
        bearish_score += max(-rs_component, 0.0)

        volume_component = max(min((volume_ratio - 1.0) * 24.0, 10.0), 0.0)
        bullish_score += volume_component
        bearish_score += volume_component

        if daily_atr_pct >= 0.06:
            bullish_score += 4.0 if bullish_score >= bearish_score else 0.0
            bearish_score += 4.0 if bearish_score > bullish_score else 0.0

        direction = "up" if bullish_score >= bearish_score else "down"
        signal_score = max(bullish_score, bearish_score)
        direction_probability = 0.50 + min(max(abs(bullish_score - bearish_score) / 120.0, 0.0), 0.18)
        direction_edge = max(
            abs(relative_strength),
            abs(current_price - (prior_high if direction == "up" else prior_low)) / max(current_price, 1e-6),
        )

        effective_thresholds = resolve_learning_thresholds(
            base_score=self.min_signal_score,
            base_probability=self.min_direction_probability,
            base_edge=self.min_direction_edge,
            learning_profile=context.get("learning_profile"),
        )
        if signal_score < effective_thresholds["min_score"]:
            return []
        if direction_probability < effective_thresholds["min_direction_probability"]:
            return []
        if direction_edge < effective_thresholds["min_direction_edge"]:
            return []

        if direction == "up":
            if not (daily_trend_up and execution_up):
                return []
            signal_type = SignalType.BUY
            stop_loss = max(current_price - max(execution_atr * 1.35, daily_atr * 0.35), current_price * 0.88)
            target = current_price + max(current_price - stop_loss, execution_atr * 0.85) * 2.1
        else:
            if not (daily_trend_down and execution_down):
                return []
            signal_type = SignalType.SELL
            stop_loss = min(current_price + max(execution_atr * 1.35, daily_atr * 0.35), current_price * 1.12)
            target = current_price - max(stop_loss - current_price, execution_atr * 0.85) * 2.1

        timestamp_value = execution_frame["timestamp"].iloc[-1] if "timestamp" in execution_frame.columns else execution_frame.index[-1]
        timestamp = pd.to_datetime(timestamp_value).to_pydatetime()
        if not isinstance(timestamp, datetime):
            return []

        if signal_score >= 82.0:
            strength = SignalStrength.STRONG
        elif signal_score >= 70.0:
            strength = SignalStrength.MODERATE
        else:
            strength = SignalStrength.WEAK

        planned_holding_days = 5 if signal_score >= 80.0 else 4 if signal_score >= 72.0 else 3
        metadata: dict[str, Any] = {
            "execution_timeframe": execution_timeframe or self.preferred_execution_timeframe,
            "signal_source": "crypto_swing_radar",
            "market": "CRYPTO",
            "horizon": "swing",
            "planned_holding_days": planned_holding_days,
            "allow_overnight": True,
            "swing_candidate_score": round(signal_score, 2),
            "direction_probability": round(direction_probability, 4),
            "direction_edge": round(direction_edge, 4),
            "relative_strength_20d": round(relative_strength, 4),
            "symbol_return_20d": round(symbol_return, 4),
            "benchmark_return_20d": round(benchmark_return, 4),
            "daily_trend": "up" if daily_trend_up else "down" if daily_trend_down else "mixed",
            "benchmark_trend": "up" if benchmark_up else "down" if benchmark_down else "mixed",
            "execution_trend": "up" if execution_up else "down" if execution_down else "mixed",
            "breakout_up": bool(breakout_up),
            "breakout_down": bool(breakout_down),
            "volume_ratio": round(volume_ratio, 3),
            "daily_atr_pct": round(daily_atr_pct, 4),
            "learning_profile": context.get("learning_profile", {}),
            "effective_thresholds": effective_thresholds,
        }

        return [
            Signal(
                timestamp=timestamp,
                symbol=symbol,
                signal_type=signal_type,
                strength=strength,
                price=round(current_price, 2),
                stop_loss=round(float(stop_loss), 2),
                target=round(float(target), 2),
                strategy_name=self.name,
                metadata=metadata,
            )
        ]

    @staticmethod
    def _normalize_frame(data: Any) -> pd.DataFrame | None:
        if not isinstance(data, pd.DataFrame) or data.empty:
            return None
        frame = data.copy()
        if "timestamp" in frame.columns:
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
        for column in ("open", "high", "low", "close", "volume"):
            if column in frame.columns:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
        required = ["open", "high", "low", "close"]
        frame = frame.dropna(subset=[column for column in required if column in frame.columns])
        if frame.empty:
            return None
        if "volume" not in frame.columns:
            frame["volume"] = 0.0
        return frame.sort_values("timestamp" if "timestamp" in frame.columns else frame.index.name or "close").reset_index(drop=True)
