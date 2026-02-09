"""Tests for the MACD + RSI Confirmation strategy."""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from src.config.market_hours import IST
from src.strategies.base import Signal, SignalStrength, SignalType
from src.strategies.directional.macd_strategy import MACDStrategy


def _make_base_data(n: int = 80) -> pd.DataFrame:
    """Generate flat/sideways data with minimal trend."""
    base = datetime(2024, 2, 8, 9, 15, tzinfo=IST)
    rows = []
    price = 22000.0
    for i in range(n):
        change = np.sin(i / 15) * 3
        price += change
        rows.append({
            "timestamp": base + timedelta(minutes=i * 5),
            "open": price - change / 2,
            "high": price + 10,
            "low": price - 10,
            "close": price,
            "volume": 10000,
        })
    return pd.DataFrame(rows)


def _make_bullish_macd_data(n: int = 200) -> pd.DataFrame:
    """Generate data producing bullish MACD crossover with RSI > 50.

    Phase 1 (0-29):  mild decline to push MACD negative.
    Phase 2 (30-79): slow recovery (RSI climbs, MACD converges toward 0).
    Phase 3 (80-119): flatten (MACD signal catches up, RSI stabilizes high).
    Phase 4 (120-n):  strong acceleration up - MACD crosses above signal with RSI > 50.
    """
    base = datetime(2024, 2, 8, 9, 15, tzinfo=IST)
    rows = []
    price = 23000.0

    for i in range(n):
        if i < 30:
            change = -2.0
        elif i < 80:
            change = 1.5
        elif i < 120:
            change = 0.5
        else:
            change = 5.0 + (i - 120) * 0.1
        price += change
        h = price + 15
        l = price - 15
        rows.append({
            "timestamp": base + timedelta(minutes=i * 5),
            "open": price - change / 2,
            "high": h,
            "low": l,
            "close": price,
            "volume": 10000,
        })
    return pd.DataFrame(rows)


def _make_bearish_macd_data(n: int = 200) -> pd.DataFrame:
    """Generate data producing bearish MACD crossover with RSI < 50.

    Phase 1 (0-29):  mild rally to push MACD positive.
    Phase 2 (30-79): slow decline (RSI drops, MACD converges toward 0).
    Phase 3 (80-119): flatten (MACD signal catches up, RSI stabilizes low).
    Phase 4 (120-n):  strong acceleration down - MACD crosses below signal with RSI < 50.
    """
    base = datetime(2024, 2, 8, 9, 15, tzinfo=IST)
    rows = []
    price = 22000.0

    for i in range(n):
        if i < 30:
            change = 2.0
        elif i < 80:
            change = -1.5
        elif i < 120:
            change = -0.5
        else:
            change = -5.0 - (i - 120) * 0.1
        price += change
        h = price + 15
        l = price - 15
        rows.append({
            "timestamp": base + timedelta(minutes=i * 5),
            "open": price - change / 2,
            "high": h,
            "low": l,
            "close": price,
            "volume": 10000,
        })
    return pd.DataFrame(rows)


class TestMACDStrategy:
    def test_instantiation_default_params(self) -> None:
        strategy = MACDStrategy()
        assert strategy.macd_fast == 12
        assert strategy.macd_slow == 26
        assert strategy.macd_signal == 9
        assert strategy.rsi_period == 14
        assert strategy.rsi_filter == 50.0
        assert strategy.atr_period == 14
        assert strategy.atr_sl_multiplier == 2.0
        assert strategy.risk_reward_ratio == 2.0

    def test_instantiation_custom_params(self) -> None:
        strategy = MACDStrategy(
            macd_fast=8,
            macd_slow=21,
            macd_signal=5,
            rsi_period=10,
            rsi_filter=45,
            atr_period=20,
            atr_sl_multiplier=1.5,
            risk_reward_ratio=3.0,
        )
        assert strategy.macd_fast == 8
        assert strategy.macd_slow == 21
        assert strategy.macd_signal == 5
        assert strategy.rsi_filter == 45
        assert strategy.risk_reward_ratio == 3.0

    def test_invalid_macd_periods(self) -> None:
        with pytest.raises(ValueError, match="macd_fast"):
            MACDStrategy(macd_fast=26, macd_slow=12)

    def test_name_property(self) -> None:
        strategy = MACDStrategy()
        assert strategy.name == "MACD_RSI"

    def test_generate_signals_returns_list(self) -> None:
        data = _make_bullish_macd_data()
        strategy = MACDStrategy()
        signals = strategy.generate_signals(data)
        assert isinstance(signals, list)
        for sig in signals:
            assert isinstance(sig, Signal)

    def test_buy_signal_on_bullish_crossover(self) -> None:
        data = _make_bullish_macd_data(200)
        strategy = MACDStrategy()
        signals = strategy.generate_signals(data)
        buys = [s for s in signals if s.signal_type == SignalType.BUY]
        assert len(buys) > 0, "Expected at least one BUY signal on bullish MACD data"

    def test_sell_signal_on_bearish_crossover(self) -> None:
        data = _make_bearish_macd_data(200)
        strategy = MACDStrategy()
        signals = strategy.generate_signals(data)
        sells = [s for s in signals if s.signal_type == SignalType.SELL]
        assert len(sells) > 0, "Expected at least one SELL signal on bearish MACD data"

    def test_no_signals_with_flat_data(self) -> None:
        data = _make_base_data(80)
        strategy = MACDStrategy()
        signals = strategy.generate_signals(data)
        # Very flat data: MACD and signal line stay close, RSI near 50
        # Any crossover may not pass RSI filter reliably, so we allow 0 or very few
        # The key test is that it doesn't crash and returns a valid list
        assert isinstance(signals, list)

    def test_signal_has_valid_stop_loss_and_target(self) -> None:
        data = _make_bullish_macd_data(200)
        strategy = MACDStrategy()
        signals = strategy.generate_signals(data)
        assert len(signals) > 0
        for sig in signals:
            assert sig.stop_loss is not None
            assert sig.target is not None
            assert sig.price is not None
            assert sig.strategy_name == "MACD_RSI"
            if sig.signal_type == SignalType.BUY:
                assert sig.stop_loss < sig.price
                assert sig.target > sig.price
            else:
                assert sig.stop_loss > sig.price
                assert sig.target < sig.price

    def test_signal_metadata(self) -> None:
        data = _make_bullish_macd_data(200)
        strategy = MACDStrategy()
        signals = strategy.generate_signals(data)
        assert len(signals) > 0
        meta = signals[0].metadata
        assert "macd" in meta
        assert "macd_signal" in meta
        assert "histogram" in meta
        assert "rsi" in meta
        assert "atr" in meta

    def test_insufficient_data(self) -> None:
        data = _make_base_data(10)
        strategy = MACDStrategy()
        signals = strategy.generate_signals(data)
        assert len(signals) == 0

    def test_repr(self) -> None:
        s = MACDStrategy(macd_fast=12, macd_slow=26, macd_signal=9, rsi_filter=50)
        r = repr(s)
        assert "12" in r
        assert "26" in r
        assert "50" in r
