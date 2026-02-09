"""Tests for the Bollinger Band Mean Reversion strategy."""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from src.config.market_hours import IST
from src.strategies.base import Signal, SignalStrength, SignalType
from src.strategies.directional.bollinger_strategy import BollingerBandStrategy


def _make_base_data(n: int = 80) -> pd.DataFrame:
    """Generate flat/sideways data within normal range.

    Alternates tiny up/down moves so price stays within BB and RSI near 50.
    """
    base = datetime(2024, 2, 8, 9, 15, tzinfo=IST)
    rows = []
    price = 22000.0
    for i in range(n):
        # Alternate up/down by a tiny amount — stays within BB, RSI ~50
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


def _make_lower_band_touch_data(n: int = 80) -> pd.DataFrame:
    """Generate data where price drops sharply below lower Bollinger Band with RSI < 30.

    Phase 1 (0-29): stable prices to establish BB baseline.
    Phase 2 (30-49): sharp drop to breach lower band and push RSI below 30.
    Phase 3 (50-n): recovery.
    """
    base = datetime(2024, 2, 8, 9, 15, tzinfo=IST)
    rows = []
    price = 22000.0

    for i in range(n):
        if i < 30:
            # Stable phase — small oscillation
            change = np.sin(i / 5) * 5
        elif i < 50:
            # Sharp drop to breach lower band and drive RSI < 30
            change = -50.0 - (i - 30) * 2.0
        else:
            # Recovery
            change = 20.0 + (i - 50) * 0.5

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


def _make_upper_band_touch_data(n: int = 80) -> pd.DataFrame:
    """Generate data where price rallies sharply above upper Bollinger Band with RSI > 70.

    Phase 1 (0-29): stable prices to establish BB baseline.
    Phase 2 (30-49): sharp rally to breach upper band and push RSI above 70.
    Phase 3 (50-n): pullback.
    """
    base = datetime(2024, 2, 8, 9, 15, tzinfo=IST)
    rows = []
    price = 22000.0

    for i in range(n):
        if i < 30:
            # Stable phase
            change = np.sin(i / 5) * 5
        elif i < 50:
            # Sharp rally to breach upper band and drive RSI > 70
            change = 50.0 + (i - 30) * 2.0
        else:
            # Pullback
            change = -20.0 - (i - 50) * 0.5

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


class TestBollingerBandStrategy:
    def test_instantiation_default_params(self) -> None:
        strategy = BollingerBandStrategy()
        assert strategy.bb_period == 20
        assert strategy.bb_std == 2.0
        assert strategy.rsi_period == 14
        assert strategy.atr_period == 14
        assert strategy.atr_sl_multiplier == 1.5
        assert strategy.risk_reward_ratio == 2.0

    def test_instantiation_custom_params(self) -> None:
        strategy = BollingerBandStrategy(
            bb_period=15,
            bb_std=1.5,
            rsi_period=10,
            atr_period=20,
            atr_sl_multiplier=2.0,
            risk_reward_ratio=3.0,
        )
        assert strategy.bb_period == 15
        assert strategy.bb_std == 1.5
        assert strategy.rsi_period == 10
        assert strategy.atr_period == 20
        assert strategy.atr_sl_multiplier == 2.0
        assert strategy.risk_reward_ratio == 3.0

    def test_name_property(self) -> None:
        strategy = BollingerBandStrategy()
        assert strategy.name == "Bollinger_MeanReversion"

    def test_generate_signals_returns_list(self) -> None:
        data = _make_lower_band_touch_data()
        strategy = BollingerBandStrategy()
        signals = strategy.generate_signals(data)
        assert isinstance(signals, list)
        for sig in signals:
            assert isinstance(sig, Signal)

    def test_buy_signal_below_lower_band(self) -> None:
        data = _make_lower_band_touch_data(80)
        strategy = BollingerBandStrategy()
        signals = strategy.generate_signals(data)
        buys = [s for s in signals if s.signal_type == SignalType.BUY]
        assert len(buys) > 0, "Expected at least one BUY signal when price drops below lower band"

    def test_sell_signal_above_upper_band(self) -> None:
        data = _make_upper_band_touch_data(80)
        strategy = BollingerBandStrategy()
        signals = strategy.generate_signals(data)
        sells = [s for s in signals if s.signal_type == SignalType.SELL]
        assert len(sells) > 0, "Expected at least one SELL signal when price rises above upper band"

    def test_no_signals_with_flat_data(self) -> None:
        data = _make_base_data(80)
        strategy = BollingerBandStrategy()
        signals = strategy.generate_signals(data)
        # Flat data stays within bands, RSI near 50 — no extreme signals expected
        assert len(signals) == 0, f"Expected no signals on flat data, got {len(signals)}"

    def test_signal_has_valid_stop_loss_and_target(self) -> None:
        data = _make_lower_band_touch_data(80)
        strategy = BollingerBandStrategy()
        signals = strategy.generate_signals(data)
        assert len(signals) > 0
        for sig in signals:
            assert sig.stop_loss is not None
            assert sig.target is not None
            assert sig.price is not None
            assert sig.strategy_name == "Bollinger_MeanReversion"
            if sig.signal_type == SignalType.BUY:
                assert sig.stop_loss < sig.price
                assert sig.target > sig.price
            else:
                assert sig.stop_loss > sig.price
                assert sig.target < sig.price

    def test_signal_metadata(self) -> None:
        data = _make_lower_band_touch_data(80)
        strategy = BollingerBandStrategy()
        signals = strategy.generate_signals(data)
        assert len(signals) > 0
        meta = signals[0].metadata
        assert "rsi" in meta
        assert "upper_band" in meta
        assert "lower_band" in meta
        assert "middle_band" in meta
        assert "atr" in meta
        assert "trigger" in meta

    def test_insufficient_data(self) -> None:
        data = _make_base_data(5)
        strategy = BollingerBandStrategy()
        signals = strategy.generate_signals(data)
        assert len(signals) == 0

    def test_repr(self) -> None:
        s = BollingerBandStrategy(bb_period=20, bb_std=2.0, atr_sl_multiplier=1.5)
        r = repr(s)
        assert "20" in r
        assert "2.0" in r
        assert "1.5" in r
