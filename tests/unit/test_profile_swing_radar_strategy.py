"""Tests for the profile swing radar strategies."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from src.config.market_hours import IST
from src.strategies.base import SignalType
from src.strategies.directional.profile_swing_radar import (
    ProfileAISwingRadarStrategy,
    ProfileSwingRadarStrategy,
)


def _make_intraday_frame() -> pd.DataFrame:
    base = datetime(2026, 3, 19, 9, 15, tzinfo=IST)
    rows = []
    price = 2480.0
    for idx in range(60):
        price += 1.25
        rows.append(
            {
                "timestamp": base + timedelta(minutes=idx * 15),
                "open": price - 2,
                "high": price + 4,
                "low": price - 3,
                "close": price,
                "volume": 100000 + idx * 1200,
                "symbol": "NSE:RELIANCE-EQ",
            }
        )
    return pd.DataFrame(rows)


def _make_hourly_frame(symbol: str) -> pd.DataFrame:
    base = datetime(2026, 1, 2, 9, 15, tzinfo=IST)
    rows = []
    price = 2350.0
    for idx in range(160):
        price += 3.0
        rows.append(
            {
                "timestamp": base + timedelta(hours=idx),
                "open": price - 5,
                "high": price + 8,
                "low": price - 7,
                "close": price,
                "volume": 250000 + idx * 1500,
                "symbol": symbol,
            }
        )
    return pd.DataFrame(rows)


class _StubScorer:
    def __init__(self, variant: str) -> None:
        self.variant = variant

    def score_latest(self, **_: object) -> dict[str, object]:
        return {
            "score": 79.0 if self.variant == "classic" else 83.0,
            "direction": "up",
            "direction_probability": 0.59,
            "neutral_probability": 0.23,
            "direction_edge": 0.36,
            "price": 2480.0,
            "stop_loss": 2400.0,
            "target": 2625.0,
            "planned_holding_days": 2,
            "allow_overnight": True,
            "expected_move_pct": 5.8,
            "atr_pct": 2.0,
            "market_regime": "bull",
            "baseline_hit_rate": 18.7,
            "target_name": "5pct",
            "variant": self.variant,
            "model_available": self.variant == "ai",
            "ai_adjustment": 4.0 if self.variant == "ai" else 0.0,
            "source": "live_market_data",
            "strength": "strong",
            "matched_conditions": [{"condition": "value_stack_bullish & open_drive_up", "lift": 2.1, "support": 122, "hit_rate": 0.31}],
            "active_conditions": ["value_stack_bullish", "open_drive_up"],
        }


def test_profile_swing_strategy_requires_runtime_context() -> None:
    strategy = ProfileSwingRadarStrategy()
    strategy._scorer = _StubScorer("classic")

    signals = strategy.generate_signals(_make_intraday_frame())

    assert signals == []


def test_profile_swing_strategy_generates_buy_signal() -> None:
    strategy = ProfileSwingRadarStrategy(min_signal_score=60.0, min_direction_probability=0.4, min_direction_edge=0.04)
    strategy._scorer = _StubScorer("classic")
    strategy.set_runtime_context(
        {
            "symbol": "NSE:RELIANCE-EQ",
            "market": "NSE",
            "execution_timeframe": "15",
            "hourly_frame": _make_hourly_frame("NSE:RELIANCE-EQ"),
            "learning_profile": {"trade_count": 0},
        }
    )

    signals = strategy.generate_signals(_make_intraday_frame())

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal_type == SignalType.BUY
    assert signal.strategy_name == "Profile_Swing_Radar"
    assert signal.metadata["profile_target_name"] == "5pct"
    assert signal.metadata["profile_variant"] == "classic"
    assert signal.target is not None and signal.stop_loss is not None
    assert signal.target > signal.price > signal.stop_loss


def test_profile_ai_swing_strategy_generates_buy_signal() -> None:
    strategy = ProfileAISwingRadarStrategy(min_signal_score=58.0, min_direction_probability=0.4, min_direction_edge=0.03)
    strategy._scorer = _StubScorer("ai")
    strategy.set_runtime_context(
        {
            "symbol": "US:AAPL",
            "market": "US",
            "execution_timeframe": "15",
            "hourly_frame": _make_hourly_frame("US:AAPL"),
            "learning_profile": {"trade_count": 12, "reward_ema": 1.2, "rolling_sharpe": 0.7, "win_rate": 0.58},
        }
    )

    signals = strategy.generate_signals(_make_intraday_frame())

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal_type == SignalType.BUY
    assert signal.strategy_name == "Profile_AI_Swing_Radar"
    assert signal.metadata["profile_variant"] == "ai"
    assert signal.metadata["model_available"] is True
