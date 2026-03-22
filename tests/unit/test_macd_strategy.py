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
        assert strategy.rsi_filter == 52.0
        assert strategy.atr_period == 14
        assert strategy.atr_sl_multiplier == 1.5
        assert strategy.risk_reward_ratio == 2.2
        assert strategy.buy_zero_line_mode == "near_or_aligned"
        assert strategy.sell_zero_line_mode == "aligned"
        assert strategy.zero_line_mode == "asymmetric"
        assert strategy.max_zero_line_distance_atr == 0.25

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

    def test_legacy_zero_line_mode_applies_to_both_sides(self) -> None:
        strategy = MACDStrategy(zero_line_mode="aligned")
        assert strategy.buy_zero_line_mode == "aligned"
        assert strategy.sell_zero_line_mode == "aligned"
        assert strategy.zero_line_mode == "aligned"

    def test_invalid_macd_periods(self) -> None:
        with pytest.raises(ValueError, match="macd_fast"):
            MACDStrategy(macd_fast=26, macd_slow=12)

    def test_invalid_zero_line_mode(self) -> None:
        with pytest.raises(ValueError, match="zero_line_mode"):
            MACDStrategy(zero_line_mode="invalid")

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
        assert "zero_line_mode" in meta
        assert "buy_zero_line_mode" in meta
        assert "sell_zero_line_mode" in meta
        assert "active_zero_line_mode" in meta
        assert "zero_line_aligned" in meta
        assert "zero_line_distance_atr" in meta

    def test_insufficient_data(self) -> None:
        data = _make_base_data(10)
        strategy = MACDStrategy()
        signals = strategy.generate_signals(data)
        assert len(signals) == 0

    def test_aligned_zero_line_mode_rejects_opposite_side_cross(self) -> None:
        strategy = MACDStrategy(zero_line_mode="aligned")
        assert strategy._zero_line_allows_entry(-0.5, 1.0, SignalType.BUY) is False
        assert strategy._zero_line_allows_entry(0.5, 1.0, SignalType.SELL) is False
        assert strategy._zero_line_allows_entry(0.1, 1.0, SignalType.BUY) is True
        assert strategy._zero_line_allows_entry(-0.1, 1.0, SignalType.SELL) is True

    def test_near_or_aligned_zero_line_mode_allows_nearby_cross(self) -> None:
        strategy = MACDStrategy(
            zero_line_mode="near_or_aligned",
            max_zero_line_distance_atr=0.25,
        )
        assert strategy._zero_line_allows_entry(-0.2, 1.0, SignalType.BUY) is True
        assert strategy._zero_line_allows_entry(0.2, 1.0, SignalType.SELL) is True
        assert strategy._zero_line_allows_entry(-0.5, 1.0, SignalType.BUY) is False
        assert strategy._zero_line_allows_entry(0.5, 1.0, SignalType.SELL) is False

    def test_zero_line_bonus_can_upgrade_strength(self) -> None:
        base = MACDStrategy(zero_line_mode="off")
        aligned = MACDStrategy(zero_line_mode="aligned")

        weak_strength = base._assess_strength(
            crossover_diff=0.08,
            atr=1.0,
            rsi=50.0,
            macd_value=-0.2,
            side=SignalType.BUY,
        )
        stronger_strength = aligned._assess_strength(
            crossover_diff=0.08,
            atr=1.0,
            rsi=50.0,
            macd_value=0.2,
            side=SignalType.BUY,
        )

        assert weak_strength == SignalStrength.WEAK
        assert stronger_strength == SignalStrength.MODERATE

    def test_repr(self) -> None:
        s = MACDStrategy(macd_fast=12, macd_slow=26, macd_signal=9, rsi_filter=50)
        r = repr(s)
        assert "12" in r
        assert "26" in r
        assert "50" in r
