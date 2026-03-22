"""FnO swing strategy driven by the offline research artifacts."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.research.fno_swing_live import DEFAULT_FNO_SWING_REPORT_DIR, FnOSwingLiveScorer
from src.strategies.base import BaseStrategy, Signal, SignalStrength, SignalType
from src.strategies.directional.swing_thresholds import resolve_learning_thresholds


class FnOSwingRadarStrategy(BaseStrategy):
    """Trade multi-day FnO swings discovered by the research pipeline."""

    name = "FnO_Swing_Radar"

    def __init__(
        self,
        report_dir: str = str(DEFAULT_FNO_SWING_REPORT_DIR),
        preferred_execution_timeframe: str = "15",
        min_signal_score: float = 72.0,
        min_direction_probability: float = 0.44,
        min_direction_edge: float = 0.08,
        min_daily_bars: int = 90,
    ) -> None:
        self.report_dir = str(Path(report_dir))
        self.preferred_execution_timeframe = str(preferred_execution_timeframe).strip().upper()
        self.min_signal_score = float(min_signal_score)
        self.min_direction_probability = float(min_direction_probability)
        self.min_direction_edge = float(min_direction_edge)
        self.min_daily_bars = int(min_daily_bars)
        self._scorer = FnOSwingLiveScorer(report_dir=self.report_dir)

    def generate_signals(self, data: pd.DataFrame) -> list[Signal]:
        if data is None or data.empty:
            return []

        context = getattr(self, "_runtime_context", {}) or {}
        execution_timeframe = str(context.get("execution_timeframe") or "").strip().upper()
        if execution_timeframe and execution_timeframe != self.preferred_execution_timeframe:
            return []

        daily_frame = context.get("daily_frame")
        benchmark_daily_frame = context.get("benchmark_daily_frame")
        if not isinstance(daily_frame, pd.DataFrame) or not isinstance(benchmark_daily_frame, pd.DataFrame):
            return []
        if len(daily_frame) < self.min_daily_bars or len(benchmark_daily_frame) < self.min_daily_bars:
            return []

        symbol = str(
            context.get("symbol")
            or (data["symbol"].iloc[-1] if "symbol" in data.columns and not data.empty else "")
            or ""
        ).strip()
        if not symbol:
            return []

        candidate = self._scorer.score_latest(
            symbol=symbol,
            daily_frame=daily_frame,
            benchmark_daily_frame=benchmark_daily_frame,
            allow_dataset_fallback=False,
        )
        if candidate is None:
            return []
        effective_thresholds = resolve_learning_thresholds(
            base_score=self.min_signal_score,
            base_probability=self.min_direction_probability,
            base_edge=self.min_direction_edge,
            learning_profile=context.get("learning_profile"),
        )
        if float(candidate.get("score", 0.0) or 0.0) < effective_thresholds["min_score"]:
            return []
        if (
            float(candidate.get("direction_probability", 0.0) or 0.0)
            < effective_thresholds["min_direction_probability"]
        ):
            return []
        if float(candidate.get("direction_edge", 0.0) or 0.0) < effective_thresholds["min_direction_edge"]:
            return []

        current_price = float(pd.to_numeric(data["close"], errors="coerce").iloc[-1])
        if current_price <= 0:
            return []

        base_price = max(float(candidate.get("price", current_price) or current_price), 1e-6)
        stop_move_pct = abs(float(candidate.get("stop_loss", base_price)) - base_price) / base_price
        target_move_pct = abs(float(candidate.get("target", base_price)) - base_price) / base_price

        direction = str(candidate.get("direction") or "up").lower()
        if direction == "up":
            signal_type = SignalType.BUY
            stop_loss = current_price * (1.0 - stop_move_pct)
            target = current_price * (1.0 + target_move_pct)
        else:
            signal_type = SignalType.SELL
            stop_loss = current_price * (1.0 + stop_move_pct)
            target = current_price * (1.0 - target_move_pct)

        timestamp_value = data["timestamp"].iloc[-1] if "timestamp" in data.columns else data.index[-1]
        timestamp = pd.to_datetime(timestamp_value).to_pydatetime()
        if not isinstance(timestamp, datetime):
            return []

        strength_label = str(candidate.get("strength") or "moderate").lower()
        strength = {
            "strong": SignalStrength.STRONG,
            "moderate": SignalStrength.MODERATE,
            "weak": SignalStrength.WEAK,
        }.get(strength_label, SignalStrength.MODERATE)

        metadata: dict[str, Any] = {
            "execution_timeframe": execution_timeframe or self.preferred_execution_timeframe,
            "signal_source": "fno_swing_research",
            "research_report_dir": self.report_dir,
            "research_source": candidate.get("source"),
            "swing_candidate_score": candidate.get("score"),
            "direction_probability": candidate.get("direction_probability"),
            "neutral_probability": candidate.get("neutral_probability"),
            "direction_edge": candidate.get("direction_edge"),
            "horizon": candidate.get("horizon"),
            "planned_holding_days": int(candidate.get("planned_holding_days", 0) or 0),
            "allow_overnight": bool(candidate.get("allow_overnight")),
            "expected_move_pct": candidate.get("expected_move_pct"),
            "atr_pct": candidate.get("atr_pct"),
            "market_regime": {
                "regime": candidate.get("market_regime"),
                "source": "fno_swing_research",
            },
            "research_market_regime": candidate.get("market_regime"),
            "baseline_hit_rate": candidate.get("baseline_hit_rate"),
            "learning_profile": context.get("learning_profile", {}),
            "effective_thresholds": effective_thresholds,
            "matched_conditions": candidate.get("matched_conditions", []),
            "matched_short_conditions": candidate.get("matched_short_conditions", []),
            "matched_long_conditions": candidate.get("matched_long_conditions", []),
            "short_probabilities": candidate.get("short_probabilities", {}),
            "long_probabilities": candidate.get("long_probabilities", {}),
        }

        return [
            Signal(
                timestamp=timestamp,
                symbol=symbol,
                signal_type=signal_type,
                strength=strength,
                price=round(current_price, 2),
                stop_loss=round(stop_loss, 2),
                target=round(target, 2),
                strategy_name=self.name,
                metadata=metadata,
            )
        ]

    def __repr__(self) -> str:
        return (
            f"<FnOSwingRadarStrategy(tf={self.preferred_execution_timeframe}, "
            f"min_score={self.min_signal_score}, min_prob={self.min_direction_probability})>"
        )
