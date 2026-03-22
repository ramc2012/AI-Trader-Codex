"""Tests for the US swing radar strategy."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from src.strategies.base import SignalType
from src.strategies.directional.us_swing_radar import USSwingRadarStrategy


def _make_intraday_frame() -> pd.DataFrame:
    base = datetime(2026, 3, 19, 14, 30, tzinfo=timezone.utc)
    rows = []
    price = 182.0
    for idx in range(60):
        price += 0.35
        rows.append(
            {
                "timestamp": base + timedelta(minutes=idx * 15),
                "open": price - 0.7,
                "high": price + 1.1,
                "low": price - 1.0,
                "close": price,
                "volume": 2_000_000 + idx * 20_000,
                "symbol": "US:AAPL",
            }
        )
    return pd.DataFrame(rows)


def _make_daily_frame(symbol: str) -> pd.DataFrame:
    base = datetime(2025, 10, 1, 20, 0, tzinfo=timezone.utc)
    rows = []
    price = 165.0 if symbol != "US:SPY" else 575.0
    for idx in range(120):
        price += 0.9 if symbol != "US:SPY" else 1.4
        rows.append(
            {
                "timestamp": base + timedelta(days=idx),
                "open": price - 1.6,
                "high": price + 2.2,
                "low": price - 2.0,
                "close": price,
                "volume": 5_000_000 + (idx * 25_000),
                "symbol": symbol,
            }
        )
    return pd.DataFrame(rows)


class _StubScorer:
    def score_latest(self, **_: object) -> dict[str, object]:
        return {
            "score": 79.0,
            "direction": "up",
            "direction_probability": 0.56,
            "neutral_probability": 0.24,
            "direction_edge": 0.32,
            "price": 182.0,
            "stop_loss": 175.0,
            "target": 194.0,
            "horizon": "10_15D",
            "planned_holding_days": 15,
            "allow_overnight": True,
            "expected_move_pct": 6.6,
            "atr_pct": 2.2,
            "market_regime": "bull",
            "baseline_hit_rate": 21.4,
            "source": "live_market_data",
            "strength": "strong",
            "matched_conditions": [{"condition": "atr_compression & volume_surge", "lift": 1.8, "support": 510, "hit_rate": 0.27}],
            "matched_short_conditions": [],
            "matched_long_conditions": [],
            "short_probabilities": {"up": 0.44, "neutral": 0.33, "down": 0.23},
            "long_probabilities": {"up": 0.56, "neutral": 0.24, "down": 0.20},
        }


def test_us_swing_strategy_requires_runtime_context() -> None:
    strategy = USSwingRadarStrategy()
    strategy._scorer = _StubScorer()

    signals = strategy.generate_signals(_make_intraday_frame())

    assert signals == []


def test_us_swing_strategy_generates_buy_signal_from_scored_candidate() -> None:
    strategy = USSwingRadarStrategy(min_signal_score=65.0, min_direction_probability=0.4, min_direction_edge=0.05)
    strategy._scorer = _StubScorer()
    strategy.set_runtime_context(
        {
            "symbol": "US:AAPL",
            "execution_timeframe": "15",
            "daily_frame": _make_daily_frame("US:AAPL"),
            "benchmark_daily_frame": _make_daily_frame("US:SPY"),
            "learning_profile": {"trade_count": 12, "reward_ema": 1.5, "rolling_sharpe": 0.8, "win_rate": 0.58},
        }
    )

    signals = strategy.generate_signals(_make_intraday_frame())

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal_type == SignalType.BUY
    assert signal.strategy_name == "US_Swing_Radar"
    assert signal.metadata["planned_holding_days"] == 15
    assert signal.metadata["allow_overnight"] is True
    assert signal.metadata["horizon"] == "10_15D"
    assert signal.metadata["effective_thresholds"]["min_score"] < 68.0
    assert signal.target is not None and signal.stop_loss is not None
    assert signal.target > signal.price > signal.stop_loss

