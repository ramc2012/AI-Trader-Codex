"""Tests for the EMA Crossover strategy."""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from src.config.market_hours import IST
from src.strategies.backtester import Backtester
from src.strategies.base import SignalType
from src.strategies.directional.ema_crossover import EMACrossoverStrategy


def _make_trending_data(direction: str = "up", n: int = 100) -> pd.DataFrame:
    """Generate synthetic trending data that produces crossovers."""
    base = datetime(2024, 2, 8, 9, 15, tzinfo=IST)
    rows = []
    price = 22000.0

    for i in range(n):
        if direction == "up":
            change = 5.0 + np.sin(i / 5) * 20  # upward with oscillation
        elif direction == "down":
            change = -5.0 + np.sin(i / 5) * 20
        else:
            change = np.sin(i / 8) * 50  # sideways oscillation

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


class TestEMACrossoverStrategy:
    def test_invalid_periods(self) -> None:
        with pytest.raises(ValueError, match="fast_period"):
            EMACrossoverStrategy(fast_period=21, slow_period=9)

    def test_generate_signals_uptrend(self) -> None:
        data = _make_trending_data("up", 100)
        strategy = EMACrossoverStrategy(fast_period=5, slow_period=15)
        signals = strategy.generate_signals(data)
        # Should have at least one BUY signal in an uptrend
        buys = [s for s in signals if s.signal_type == SignalType.BUY]
        assert len(buys) > 0

    def test_generate_signals_downtrend(self) -> None:
        data = _make_trending_data("down", 100)
        strategy = EMACrossoverStrategy(fast_period=5, slow_period=15)
        signals = strategy.generate_signals(data)
        sells = [s for s in signals if s.signal_type == SignalType.SELL]
        assert len(sells) > 0

    def test_signal_has_stop_loss_and_target(self) -> None:
        data = _make_trending_data("sideways", 100)
        strategy = EMACrossoverStrategy(fast_period=5, slow_period=15)
        signals = strategy.generate_signals(data)
        if signals:
            for sig in signals:
                assert sig.stop_loss is not None
                assert sig.target is not None
                assert sig.strategy_name == "EMA_Crossover"

    def test_signal_metadata(self) -> None:
        data = _make_trending_data("up", 100)
        strategy = EMACrossoverStrategy(fast_period=5, slow_period=15)
        signals = strategy.generate_signals(data)
        if signals:
            meta = signals[0].metadata
            assert "fast_ema" in meta
            assert "slow_ema" in meta
            assert "atr" in meta

    def test_insufficient_data(self) -> None:
        data = _make_trending_data("up", 5)  # too few bars
        strategy = EMACrossoverStrategy(fast_period=9, slow_period=21)
        signals = strategy.generate_signals(data)
        assert len(signals) == 0

    def test_repr(self) -> None:
        s = EMACrossoverStrategy(fast_period=9, slow_period=21, atr_multiplier=1.5)
        r = repr(s)
        assert "9" in r
        assert "21" in r
        assert "1.5" in r


class TestEMACrossoverBacktest:
    def test_full_backtest(self) -> None:
        data = _make_trending_data("sideways", 200)
        strategy = EMACrossoverStrategy(fast_period=5, slow_period=15)
        bt = Backtester(strategy=strategy, initial_capital=100000)
        result = bt.run(data, symbol="NSE:NIFTY50-INDEX")

        assert result.total_trades > 0
        assert result.strategy_name == "EMA_Crossover"
        summary = result.summary()
        assert "win_rate" in summary
        assert "max_drawdown_pct" in summary

    def test_backtest_with_slippage(self) -> None:
        data = _make_trending_data("up", 200)
        strategy = EMACrossoverStrategy(fast_period=5, slow_period=15)
        bt = Backtester(strategy=strategy, slippage_pct=0.05)
        result = bt.run(data, symbol="TEST")
        assert result.total_trades > 0
