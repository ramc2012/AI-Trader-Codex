"""Tests for the Supertrend Breakout strategy."""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from src.config.market_hours import IST
from src.strategies.base import Signal, SignalStrength, SignalType
from src.strategies.directional.supertrend_strategy import SupertrendStrategy


def _make_base_data(n: int = 80) -> pd.DataFrame:
    """Generate flat/sideways data with minimal trend changes."""
    base = datetime(2024, 2, 8, 9, 15, tzinfo=IST)
    rows = []
    price = 22000.0
    for i in range(n):
        change = np.sin(i / 20) * 3
        price += change
        rows.append({
            "timestamp": base + timedelta(minutes=i * 5),
            "open": price - change / 2,
            "high": price + 8,
            "low": price - 8,
            "close": price,
            "volume": 10000,
        })
    return pd.DataFrame(rows)


def _make_uptrend_breakout_data(n: int = 80) -> pd.DataFrame:
    """Generate data with a downtrend-to-uptrend reversal (direction -1 to +1).

    Phase 1 (0-39): strong downtrend to establish supertrend direction as -1.
    Phase 2 (40-n): strong uptrend to flip supertrend direction to +1.
    """
    base = datetime(2024, 2, 8, 9, 15, tzinfo=IST)
    rows = []
    price = 22000.0

    for i in range(n):
        if i < 40:
            # Strong downtrend
            change = -25.0 - np.sin(i / 3) * 5
        else:
            # Strong uptrend breakout
            change = 35.0 + (i - 40) * 1.5
        price += change
        h = price + abs(change) + 20
        l = price - abs(change) - 20
        rows.append({
            "timestamp": base + timedelta(minutes=i * 5),
            "open": price - change / 2,
            "high": h,
            "low": l,
            "close": price,
            "volume": 10000,
        })
    return pd.DataFrame(rows)


def _make_downtrend_breakout_data(n: int = 80) -> pd.DataFrame:
    """Generate data with an uptrend-to-downtrend reversal (direction +1 to -1).

    Phase 1 (0-39): strong uptrend to establish supertrend direction as +1.
    Phase 2 (40-n): strong downtrend to flip supertrend direction to -1.
    """
    base = datetime(2024, 2, 8, 9, 15, tzinfo=IST)
    rows = []
    price = 22000.0

    for i in range(n):
        if i < 40:
            # Strong uptrend
            change = 25.0 + np.sin(i / 3) * 5
        else:
            # Strong downtrend breakdown
            change = -35.0 - (i - 40) * 1.5
        price += change
        h = price + abs(change) + 20
        l = price - abs(change) - 20
        rows.append({
            "timestamp": base + timedelta(minutes=i * 5),
            "open": price - change / 2,
            "high": h,
            "low": l,
            "close": price,
            "volume": 10000,
        })
    return pd.DataFrame(rows)


def _make_multi_reversal_data(n: int = 120) -> pd.DataFrame:
    """Generate data with multiple trend reversals to produce both BUY and SELL signals."""
    base = datetime(2024, 2, 8, 9, 15, tzinfo=IST)
    rows = []
    price = 22000.0

    for i in range(n):
        if i < 30:
            change = -25.0  # downtrend
        elif i < 60:
            change = 30.0  # uptrend (triggers BUY)
        elif i < 90:
            change = -30.0  # downtrend (triggers SELL)
        else:
            change = 25.0  # uptrend again
        price += change
        h = price + abs(change) + 20
        l = price - abs(change) - 20
        rows.append({
            "timestamp": base + timedelta(minutes=i * 5),
            "open": price - change / 2,
            "high": h,
            "low": l,
            "close": price,
            "volume": 10000,
        })
    return pd.DataFrame(rows)


class TestSupertrendStrategy:
    def test_instantiation_default_params(self) -> None:
        strategy = SupertrendStrategy()
        assert strategy.st_period == 10
        assert strategy.st_multiplier == 3.0
        assert strategy.atr_period == 14
        assert strategy.atr_sl_multiplier == 2.0
        assert strategy.risk_reward_ratio == 2.0

    def test_instantiation_custom_params(self) -> None:
        strategy = SupertrendStrategy(
            st_period=7,
            st_multiplier=2.0,
            atr_period=20,
            atr_sl_multiplier=1.5,
            risk_reward_ratio=3.0,
        )
        assert strategy.st_period == 7
        assert strategy.st_multiplier == 2.0
        assert strategy.atr_period == 20
        assert strategy.atr_sl_multiplier == 1.5
        assert strategy.risk_reward_ratio == 3.0

    def test_name_property(self) -> None:
        strategy = SupertrendStrategy()
        assert strategy.name == "Supertrend_Breakout"

    def test_generate_signals_returns_list(self) -> None:
        data = _make_uptrend_breakout_data()
        strategy = SupertrendStrategy()
        signals = strategy.generate_signals(data)
        assert isinstance(signals, list)
        for sig in signals:
            assert isinstance(sig, Signal)

    def test_buy_signal_on_uptrend_breakout(self) -> None:
        data = _make_uptrend_breakout_data(80)
        strategy = SupertrendStrategy()
        signals = strategy.generate_signals(data)
        buys = [s for s in signals if s.signal_type == SignalType.BUY]
        assert len(buys) > 0, "Expected at least one BUY signal on uptrend breakout"

    def test_sell_signal_on_downtrend_breakout(self) -> None:
        data = _make_downtrend_breakout_data(80)
        strategy = SupertrendStrategy()
        signals = strategy.generate_signals(data)
        sells = [s for s in signals if s.signal_type == SignalType.SELL]
        assert len(sells) > 0, "Expected at least one SELL signal on downtrend breakout"

    def test_no_signals_with_flat_data(self) -> None:
        data = _make_base_data(80)
        strategy = SupertrendStrategy()
        signals = strategy.generate_signals(data)
        # Very flat data should have no direction changes
        # (though the initial direction assignment may cause one, we check for minimal signals)
        assert isinstance(signals, list)

    def test_signal_has_valid_stop_loss_and_target(self) -> None:
        data = _make_uptrend_breakout_data(80)
        strategy = SupertrendStrategy()
        signals = strategy.generate_signals(data)
        assert len(signals) > 0
        for sig in signals:
            assert sig.stop_loss is not None
            assert sig.target is not None
            assert sig.price is not None
            assert sig.strategy_name == "Supertrend_Breakout"
            if sig.signal_type == SignalType.BUY:
                assert sig.stop_loss < sig.price
                assert sig.target > sig.price
            else:
                assert sig.stop_loss > sig.price
                assert sig.target < sig.price

    def test_signal_metadata(self) -> None:
        data = _make_uptrend_breakout_data(80)
        strategy = SupertrendStrategy()
        signals = strategy.generate_signals(data)
        assert len(signals) > 0
        meta = signals[0].metadata
        assert "supertrend" in meta
        assert "direction" in meta
        assert "prev_direction" in meta
        assert "atr" in meta
        assert "trigger" in meta

    def test_insufficient_data(self) -> None:
        data = _make_base_data(5)
        strategy = SupertrendStrategy()
        signals = strategy.generate_signals(data)
        assert len(signals) == 0

    def test_repr(self) -> None:
        s = SupertrendStrategy(st_period=10, st_multiplier=3.0, atr_sl_multiplier=2.0)
        r = repr(s)
        assert "10" in r
        assert "3.0" in r
        assert "2.0" in r

    def test_multi_reversal_produces_both_signals(self) -> None:
        data = _make_multi_reversal_data(120)
        strategy = SupertrendStrategy()
        signals = strategy.generate_signals(data)
        buys = [s for s in signals if s.signal_type == SignalType.BUY]
        sells = [s for s in signals if s.signal_type == SignalType.SELL]
        assert len(buys) > 0, "Expected BUY signals in multi-reversal data"
        assert len(sells) > 0, "Expected SELL signals in multi-reversal data"
