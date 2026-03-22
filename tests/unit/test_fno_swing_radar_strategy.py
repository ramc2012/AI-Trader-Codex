"""Tests for the FnO swing radar strategy."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from src.config.market_hours import IST
from src.strategies.base import SignalType
from src.strategies.directional.fno_swing_radar import FnOSwingRadarStrategy


def _make_intraday_frame() -> pd.DataFrame:
    base = datetime(2026, 3, 19, 9, 15, tzinfo=IST)
    rows = []
    price = 2480.0
    for idx in range(60):
        price += 1.5
        rows.append(
            {
                "timestamp": base + timedelta(minutes=idx * 15),
                "open": price - 2,
                "high": price + 4,
                "low": price - 4,
                "close": price,
                "volume": 100000 + idx * 1000,
                "symbol": "NSE:RELIANCE-EQ",
            }
        )
    return pd.DataFrame(rows)


def _make_daily_frame(symbol: str) -> pd.DataFrame:
    base = datetime(2025, 10, 1, 15, 30, tzinfo=IST)
    rows = []
    price = 2200.0 if symbol != "NSE:NIFTY50-INDEX" else 23500.0
    for idx in range(120):
        price += 6.0 if symbol != "NSE:NIFTY50-INDEX" else 25.0
        rows.append(
            {
                "timestamp": base + timedelta(days=idx),
                "open": price - 12,
                "high": price + 18,
                "low": price - 18,
                "close": price,
                "volume": 1_000_000 + (idx * 5000),
                "symbol": symbol,
            }
        )
    return pd.DataFrame(rows)


class _StubScorer:
    def score_latest(self, **_: object) -> dict[str, object]:
        return {
            "score": 82.0,
            "direction": "up",
            "direction_probability": 0.58,
            "neutral_probability": 0.26,
            "direction_edge": 0.32,
            "price": 2480.0,
            "stop_loss": 2390.0,
            "target": 2685.0,
            "horizon": "10_15D",
            "planned_holding_days": 15,
            "allow_overnight": True,
            "expected_move_pct": 8.25,
            "atr_pct": 2.1,
            "market_regime": "bull",
            "baseline_hit_rate": 24.38,
            "source": "live_market_data",
            "strength": "strong",
            "matched_conditions": [{"condition": "atr_compression & volume_surge", "lift": 1.9, "support": 420, "hit_rate": 0.29}],
            "matched_short_conditions": [],
            "matched_long_conditions": [],
            "short_probabilities": {"up": 0.41, "neutral": 0.34, "down": 0.25},
            "long_probabilities": {"up": 0.58, "neutral": 0.26, "down": 0.16},
        }


def test_fno_swing_strategy_requires_runtime_context() -> None:
    strategy = FnOSwingRadarStrategy()
    strategy._scorer = _StubScorer()

    signals = strategy.generate_signals(_make_intraday_frame())

    assert signals == []


def test_fno_swing_strategy_generates_buy_signal_from_scored_candidate() -> None:
    strategy = FnOSwingRadarStrategy(min_signal_score=70.0, min_direction_probability=0.4, min_direction_edge=0.05)
    strategy._scorer = _StubScorer()
    strategy.set_runtime_context(
        {
            "symbol": "NSE:RELIANCE-EQ",
            "execution_timeframe": "15",
            "daily_frame": _make_daily_frame("NSE:RELIANCE-EQ"),
            "benchmark_daily_frame": _make_daily_frame("NSE:NIFTY50-INDEX"),
        }
    )

    signals = strategy.generate_signals(_make_intraday_frame())

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal_type == SignalType.BUY
    assert signal.strategy_name == "FnO_Swing_Radar"
    assert signal.metadata["planned_holding_days"] == 15
    assert signal.metadata["allow_overnight"] is True
    assert signal.metadata["horizon"] == "10_15D"
    assert signal.target is not None and signal.stop_loss is not None
    assert signal.target > signal.price > signal.stop_loss
