"""Tests for the fractal profile breakout strategy."""

from datetime import datetime, timedelta

import pandas as pd

from src.config.market_hours import IST
from src.strategies.base import SignalType
from src.strategies.directional.fractal_profile_strategy import FractalProfileBreakoutStrategy


def _make_fractal_data(direction: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    prev_base = datetime(2026, 3, 5, 9, 15, tzinfo=IST)
    current_base = datetime(2026, 3, 6, 9, 15, tzinfo=IST)
    price = 100.0 if direction == "bullish" else 120.0

    for index in range(125):
        ts = prev_base + timedelta(minutes=index * 3)
        if direction == "bullish":
            drift = 0.03 if index < 60 else -0.005
            bias = 0.01 if index % 4 == 0 else -0.004
        else:
            drift = -0.02 if index < 70 else 0.005
            bias = -0.01 if index % 4 == 0 else 0.003
        open_price = price
        close_price = price + drift + bias
        high = max(open_price, close_price) + 0.04
        low = min(open_price, close_price) - 0.03
        rows.append(
            {
                "timestamp": ts,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close_price,
                "volume": 1000 + index * 3,
                "symbol": "NSE:TEST",
            }
        )
        price = close_price

    for index in range(100):
        ts = current_base + timedelta(minutes=index * 3)
        if direction == "bullish":
            if index < 20:
                drift = 0.06
            elif index < 40:
                drift = 0.08
            elif index < 60:
                drift = 0.10
            elif index < 80:
                drift = 0.05
            else:
                drift = 0.07
            open_price = price
            close_price = price + drift + (0.03 if index % 3 != 0 else -0.005)
        else:
            if index < 20:
                drift = -0.05
            elif index < 40:
                drift = -0.07
            elif index < 60:
                drift = -0.09
            elif index < 80:
                drift = -0.06
            else:
                drift = -0.08
            open_price = price
            close_price = price + drift + (-0.025 if index % 3 != 0 else 0.005)
        high = max(open_price, close_price) + 0.03
        low = min(open_price, close_price) - 0.02
        rows.append(
            {
                "timestamp": ts,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close_price,
                "volume": 1200 + index * 5,
                "symbol": "NSE:TEST",
            }
        )
        price = close_price

    return pd.DataFrame(rows)


def _make_crypto_fractal_data(direction: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    prev_base = datetime(2026, 3, 5, 0, 0, tzinfo=IST)
    current_base = datetime(2026, 3, 6, 0, 0, tzinfo=IST)
    price = 42000.0 if direction == "bullish" else 45000.0

    for index in range(180):
        ts = prev_base + timedelta(minutes=index * 3)
        drift = 9.0 if direction == "bullish" else -9.0
        noise = 2.5 if index % 4 != 0 else -1.0
        open_price = price
        close_price = price + drift + noise if direction == "bullish" else price + drift - noise
        high = max(open_price, close_price) + 6.0
        low = min(open_price, close_price) - 5.0
        rows.append(
            {
                "timestamp": ts,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close_price,
                "volume": 1_500 + index * 6,
                "symbol": "CRYPTO:BTCUSDT",
            }
        )
        price = close_price

    for index in range(160):
        ts = current_base + timedelta(minutes=index * 3)
        if direction == "bullish":
            if index < 100:
                drift = 14.0
                noise = 4.0 if index % 3 != 0 else -1.5
            elif index < 140:
                drift = 10.0
                noise = 3.0 if index % 3 != 0 else -1.0
            else:
                drift = 24.0
                noise = 6.0 if index % 4 != 0 else 1.5
        else:
            if index < 100:
                drift = -14.0
                noise = -4.0 if index % 3 != 0 else 1.5
            elif index < 140:
                drift = -10.0
                noise = -3.0 if index % 3 != 0 else 1.0
            else:
                drift = -24.0
                noise = -6.0 if index % 4 != 0 else -1.5
        open_price = price
        close_price = price + drift + noise
        high = max(open_price, close_price) + 6.0
        low = min(open_price, close_price) - 5.0
        rows.append(
            {
                "timestamp": ts,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close_price,
                "volume": 2_000 + index * 8,
                "symbol": "CRYPTO:BTCUSDT",
            }
        )
        price = close_price

    return pd.DataFrame(rows)


def _make_us_fractal_data(direction: str) -> pd.DataFrame:
    frame = _make_fractal_data(direction).copy()
    frame["symbol"] = "US:SPY"
    shifted: list[datetime] = []
    prev_base = datetime(2026, 3, 5, 20, 0, tzinfo=IST)
    current_base = datetime(2026, 3, 6, 20, 0, tzinfo=IST)
    for index in range(len(frame)):
        base = prev_base if index < 125 else current_base
        offset = index if index < 125 else index - 125
        shifted.append(base + timedelta(minutes=offset * 3))
    frame["timestamp"] = shifted
    return frame


def test_generates_buy_signal_on_bullish_profile_stack() -> None:
    strategy = FractalProfileBreakoutStrategy()
    signals = strategy.generate_signals(_make_fractal_data("bullish"))

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal_type == SignalType.BUY
    assert signal.stop_loss is not None and signal.price is not None and signal.stop_loss < signal.price
    assert signal.target is not None and signal.target > signal.price
    assert signal.strategy_name == "Fractal_Profile_Breakout"
    assert signal.metadata["daily_alignment"] is True
    assert signal.metadata["hourly_shape"] == "elongated_up"
    assert signal.metadata["position_size_multiplier"] >= 0.6
    assert signal.metadata["adaptive_risk_reward"] >= 1.2
    assert signal.metadata["setup_type"] in {"acceptance_trend", "gap_and_go", "breakout_drive"}


def test_generates_sell_signal_on_bearish_profile_stack() -> None:
    strategy = FractalProfileBreakoutStrategy()
    signals = strategy.generate_signals(_make_fractal_data("bearish"))

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal_type == SignalType.SELL
    assert signal.stop_loss is not None and signal.price is not None and signal.stop_loss > signal.price
    assert signal.target is not None and signal.target < signal.price
    assert signal.metadata["daily_alignment"] is True
    assert signal.metadata["hourly_shape"] == "elongated_down"
    assert signal.metadata["position_size_multiplier"] >= 0.6
    assert signal.metadata["adaptive_risk_reward"] >= 1.2


def test_ignores_non_three_minute_structure() -> None:
    data = _make_fractal_data("bullish").copy()
    data["timestamp"] = [datetime(2026, 3, 6, 9, 15, tzinfo=IST) + timedelta(minutes=index * 15) for index in range(len(data))]

    strategy = FractalProfileBreakoutStrategy()
    signals = strategy.generate_signals(data)

    assert signals == []


def test_generates_crypto_signal_on_supported_fractal_stack() -> None:
    strategy = FractalProfileBreakoutStrategy()
    signals = strategy.generate_signals(_make_crypto_fractal_data("bullish"))

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal_type == SignalType.BUY
    assert signal.metadata["market"] == "CRYPTO"
    assert signal.metadata["hourly_shape"] == "elongated_up"
    assert signal.metadata["value_acceptance"] in {"accepted", "fast", "mixed", "balanced"}


def test_us_fractal_rules_are_more_permissive_than_default_baseline() -> None:
    strategy = FractalProfileBreakoutStrategy()
    signals = strategy.generate_signals(_make_us_fractal_data("bullish"))

    assert len(signals) == 1
    profile = signals[0].metadata["market_rule_profile"]
    assert profile["market"] == "US"
    assert profile["min_conviction"] <= 66
    assert profile["min_consecutive_hours"] == 1


def test_crypto_fractal_rules_remain_tighter_than_us_profile() -> None:
    strategy = FractalProfileBreakoutStrategy()
    signals = strategy.generate_signals(_make_crypto_fractal_data("bullish"))

    assert len(signals) == 1
    profile = signals[0].metadata["market_rule_profile"]
    assert profile["market"] == "CRYPTO"
    assert profile["min_conviction"] >= 68
    assert profile["max_stop_pct"] <= 1.8
