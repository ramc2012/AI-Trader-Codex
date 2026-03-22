"""Adaptive threshold helpers for multi-day swing strategies."""

from __future__ import annotations

from typing import Any


def resolve_learning_thresholds(
    *,
    base_score: float,
    base_probability: float,
    base_edge: float,
    learning_profile: dict[str, Any] | None,
) -> dict[str, float]:
    profile = learning_profile if isinstance(learning_profile, dict) else {}
    trade_count = max(int(profile.get("trade_count", 0) or 0), 0)
    reward_ema = float(profile.get("reward_ema", 0.0) or 0.0)
    rolling_sharpe = float(profile.get("rolling_sharpe", 0.0) or 0.0)
    win_rate = float(profile.get("win_rate", 0.0) or 0.0)

    score_adjustment = 0.0
    probability_adjustment = 0.0
    edge_adjustment = 0.0

    if trade_count >= 8:
        if reward_ema <= -2.5 or rolling_sharpe <= -0.4:
            score_adjustment += 5.0
            probability_adjustment += 0.03
            edge_adjustment += 0.02
        elif reward_ema <= -1.0 or win_rate <= 0.42:
            score_adjustment += 2.5
            probability_adjustment += 0.015
            edge_adjustment += 0.01
        elif reward_ema >= 2.5 and rolling_sharpe >= 0.6 and win_rate >= 0.56:
            score_adjustment -= 3.0
            probability_adjustment -= 0.015
            edge_adjustment -= 0.01
        elif reward_ema >= 1.0 and win_rate >= 0.52:
            score_adjustment -= 1.0
            probability_adjustment -= 0.01
            edge_adjustment -= 0.005

    return {
        "min_score": max(45.0, min(90.0, float(base_score) + score_adjustment)),
        "min_direction_probability": max(0.35, min(0.70, float(base_probability) + probability_adjustment)),
        "min_direction_edge": max(0.02, min(0.20, float(base_edge) + edge_adjustment)),
    }

