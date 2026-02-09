"""Tests for the RSI Reversal strategy."""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from src.config.market_hours import IST
from src.strategies.base import Signal, SignalStrength, SignalType
from src.strategies.directional.rsi_reversal import RSIReversalStrategy


def _make_base_data(n: int = 80) -> pd.DataFrame:
    """Generate flat/sideways data that should NOT trigger RSI extremes.

    Alternates tiny up/down moves so RSI oscillates around 50.
    """
    base = datetime(2024, 2, 8, 9, 15, tzinfo=IST)
    rows = []
    price = 22000.0
    for i in range(n):
        # Alternate up/down with equal magnitude -> RSI stays near 50
        change = 1.0 if i % 2 == 0 else -1.0
        price += change
        rows.append({
            "timestamp": base + timedelta(minutes=i * 5),
            "open": price - change / 2,
            "high": price + 5,
            "low": price - 5,
            "close": price,
            "volume": 10000,
        })
    return pd.DataFrame(rows)


def _make_oversold_reversal_data(n: int = 80) -> pd.DataFrame:
    """Generate data that dips hard (RSI < 30) then reverses upward.

    Phase 1 (0-39): steady decline to push RSI well below 30.
    Phase 2 (40-n): sharp bounce to push RSI above 30.
    """
    base = datetime(2024, 2, 8, 9, 15, tzinfo=IST)
    rows = []
    price = 22000.0

    for i in range(n):
        if i < 40:
            # Strong decline — each bar drops significantly
            change = -30.0 - (i * 0.5)
        else:
            # Sharp reversal upward
            change = 40.0 + ((i - 40) * 1.0)

        price += change
        h = price + abs(change) + 10
        l = price - abs(change) - 10
        rows.append({
            "timestamp": base + timedelta(minutes=i * 5),
            "open": price - change / 2,
            "high": h,
            "low": l,
            "close": price,
            "volume": 10000,
        })
    return pd.DataFrame(rows)


def _make_overbought_reversal_data(n: int = 80) -> pd.DataFrame:
    """Generate data that rallies (RSI > 70) then reverses downward.

    Phase 1 (0-39): steady rally to push RSI well above 70.
    Phase 2 (40-n): sharp drop to push RSI below 70.
    """
    base = datetime(2024, 2, 8, 9, 15, tzinfo=IST)
    rows = []
    price = 22000.0

    for i in range(n):
        if i < 40:
            # Strong rally
            change = 30.0 + (i * 0.5)
        else:
            # Sharp reversal downward
            change = -40.0 - ((i - 40) * 1.0)

        price += change
        h = price + abs(change) + 10
        l = price - abs(change) - 10
        rows.append({
            "timestamp": base + timedelta(minutes=i * 5),
            "open": price - change / 2,
            "high": h,
            "low": l,
            "close": price,
            "volume": 10000,
        })
    return pd.DataFrame(rows)


class TestRSIReversalStrategy:
    def test_instantiation_default_params(self) -> None:
        strategy = RSIReversalStrategy()
        assert strategy.rsi_period == 14
        assert strategy.oversold == 30.0
        assert strategy.overbought == 70.0
        assert strategy.atr_period == 14
        assert strategy.atr_sl_multiplier == 1.5
        assert strategy.risk_reward_ratio == 2.0

    def test_instantiation_custom_params(self) -> None:
        strategy = RSIReversalStrategy(
            rsi_period=10,
            oversold=25,
            overbought=75,
            atr_period=20,
            atr_sl_multiplier=2.0,
            risk_reward_ratio=3.0,
        )
        assert strategy.rsi_period == 10
        assert strategy.oversold == 25
        assert strategy.overbought == 75
        assert strategy.atr_period == 20
        assert strategy.atr_sl_multiplier == 2.0
        assert strategy.risk_reward_ratio == 3.0

    def test_invalid_thresholds(self) -> None:
        with pytest.raises(ValueError, match="oversold"):
            RSIReversalStrategy(oversold=70, overbought=30)

    def test_name_property(self) -> None:
        strategy = RSIReversalStrategy()
        assert strategy.name == "RSI_Reversal"

    def test_generate_signals_returns_list(self) -> None:
        data = _make_oversold_reversal_data()
        strategy = RSIReversalStrategy()
        signals = strategy.generate_signals(data)
        assert isinstance(signals, list)
        for sig in signals:
            assert isinstance(sig, Signal)

    def test_buy_signal_on_oversold_reversal(self) -> None:
        data = _make_oversold_reversal_data(80)
        strategy = RSIReversalStrategy()
        signals = strategy.generate_signals(data)
        buys = [s for s in signals if s.signal_type == SignalType.BUY]
        assert len(buys) > 0, "Expected at least one BUY signal on oversold reversal"

    def test_sell_signal_on_overbought_reversal(self) -> None:
        data = _make_overbought_reversal_data(80)
        strategy = RSIReversalStrategy()
        signals = strategy.generate_signals(data)
        sells = [s for s in signals if s.signal_type == SignalType.SELL]
        assert len(sells) > 0, "Expected at least one SELL signal on overbought reversal"

    def test_no_signals_with_flat_data(self) -> None:
        data = _make_base_data(80)
        strategy = RSIReversalStrategy()
        signals = strategy.generate_signals(data)
        # Flat data RSI stays around 50 — no extreme crossovers expected
        assert len(signals) == 0, f"Expected no signals on flat data, got {len(signals)}"

    def test_signal_has_valid_stop_loss_and_target(self) -> None:
        data = _make_oversold_reversal_data(80)
        strategy = RSIReversalStrategy()
        signals = strategy.generate_signals(data)
        assert len(signals) > 0
        for sig in signals:
            assert sig.stop_loss is not None
            assert sig.target is not None
            assert sig.price is not None
            assert sig.strategy_name == "RSI_Reversal"
            if sig.signal_type == SignalType.BUY:
                assert sig.stop_loss < sig.price
                assert sig.target > sig.price
            else:
                assert sig.stop_loss > sig.price
                assert sig.target < sig.price

    def test_signal_metadata(self) -> None:
        data = _make_oversold_reversal_data(80)
        strategy = RSIReversalStrategy()
        signals = strategy.generate_signals(data)
        assert len(signals) > 0
        meta = signals[0].metadata
        assert "rsi" in meta
        assert "prev_rsi" in meta
        assert "atr" in meta
        assert "trigger" in meta

    def test_insufficient_data(self) -> None:
        data = _make_base_data(5)
        strategy = RSIReversalStrategy()
        signals = strategy.generate_signals(data)
        assert len(signals) == 0

    def test_repr(self) -> None:
        s = RSIReversalStrategy(rsi_period=14, oversold=30, overbought=70, atr_sl_multiplier=1.5)
        r = repr(s)
        assert "14" in r
        assert "30" in r
        assert "70" in r
        assert "1.5" in r
