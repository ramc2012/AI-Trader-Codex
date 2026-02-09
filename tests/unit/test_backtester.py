"""Tests for the backtesting engine and strategy base classes."""

from datetime import datetime, timedelta

import pandas as pd
import pytest

from src.config.market_hours import IST
from src.strategies.backtester import Backtester
from src.strategies.base import (
    BacktestResult,
    BacktestTrade,
    BaseStrategy,
    Signal,
    SignalStrength,
    SignalType,
)


# =========================================================================
# Test strategy: simple alternating BUY/SELL
# =========================================================================


class AlternatingStrategy(BaseStrategy):
    """Test strategy that alternates BUY/SELL every N bars."""

    name = "Alternating"

    def __init__(self, interval: int = 5, sl_pct: float = 1.0, tp_pct: float = 2.0) -> None:
        self.interval = interval
        self.sl_pct = sl_pct
        self.tp_pct = tp_pct

    def generate_signals(self, data: pd.DataFrame) -> list[Signal]:
        signals = []
        buy = True
        for i in range(0, len(data), self.interval):
            price = float(data["close"].iloc[i])
            sig_type = SignalType.BUY if buy else SignalType.SELL
            sl = price * (1 - self.sl_pct / 100) if buy else price * (1 + self.sl_pct / 100)
            tp = price * (1 + self.tp_pct / 100) if buy else price * (1 - self.tp_pct / 100)
            signals.append(Signal(
                timestamp=data["timestamp"].iloc[i],
                symbol="TEST",
                signal_type=sig_type,
                price=price,
                stop_loss=round(sl, 2),
                target=round(tp, 2),
                strategy_name=self.name,
            ))
            buy = not buy
        return signals


@pytest.fixture
def sample_data() -> pd.DataFrame:
    """Generate 100 bars of synthetic OHLCV data."""
    base = datetime(2024, 2, 8, 9, 15, tzinfo=IST)
    rows = []
    price = 22000.0
    for i in range(100):
        # Simulated random walk
        change = (i % 7 - 3) * 10  # oscillates
        o = price
        h = price + abs(change) + 20
        l = price - abs(change) - 10
        c = price + change
        rows.append({
            "timestamp": base + timedelta(minutes=i * 5),
            "open": o, "high": h, "low": l, "close": c,
            "volume": 10000 + i * 100,
        })
        price = c
    return pd.DataFrame(rows)


# =========================================================================
# Signal Tests
# =========================================================================


class TestSignal:
    def test_actionable(self) -> None:
        s = Signal(datetime.now(), "S", SignalType.BUY)
        assert s.is_actionable is True

    def test_hold_not_actionable(self) -> None:
        s = Signal(datetime.now(), "S", SignalType.HOLD)
        assert s.is_actionable is False

    def test_to_dict(self) -> None:
        s = Signal(datetime.now(), "S", SignalType.SELL, price=100.0)
        d = s.to_dict()
        assert d["signal_type"] == "SELL"
        assert d["price"] == 100.0


# =========================================================================
# BacktestTrade Tests
# =========================================================================


class TestBacktestTrade:
    def test_is_winner(self) -> None:
        t = BacktestTrade(entry_time=datetime.now(), pnl=100.0)
        assert t.is_winner is True

    def test_is_loser(self) -> None:
        t = BacktestTrade(entry_time=datetime.now(), pnl=-50.0)
        assert t.is_winner is False

    def test_is_open(self) -> None:
        t = BacktestTrade(entry_time=datetime.now())
        assert t.is_open is True
        t.exit_time = datetime.now()
        assert t.is_open is False


# =========================================================================
# BacktestResult Tests
# =========================================================================


class TestBacktestResult:
    def _make_result(self, pnls: list[float]) -> BacktestResult:
        trades = [
            BacktestTrade(
                entry_time=datetime.now(),
                exit_time=datetime.now(),
                pnl=pnl,
            )
            for pnl in pnls
        ]
        return BacktestResult(
            strategy_name="Test",
            symbol="S",
            start_date=datetime.now(),
            end_date=datetime.now(),
            initial_capital=100000,
            final_capital=100000 + sum(pnls),
            trades=trades,
        )

    def test_win_rate(self) -> None:
        r = self._make_result([100, -50, 200, -30, 150])
        assert r.win_rate == 60.0  # 3 wins out of 5

    def test_total_pnl(self) -> None:
        r = self._make_result([100, -50, 200])
        assert r.total_pnl == 250.0

    def test_profit_factor(self) -> None:
        r = self._make_result([100, -50, 200])
        assert r.profit_factor == pytest.approx(300 / 50)

    def test_max_drawdown(self) -> None:
        r = self._make_result([100, -200, -100, 500])
        assert r.max_drawdown > 0

    def test_empty_trades(self) -> None:
        r = self._make_result([])
        assert r.win_rate == 0.0
        assert r.total_pnl == 0.0
        assert r.profit_factor == 0.0

    def test_summary(self) -> None:
        r = self._make_result([100, -50])
        s = r.summary()
        assert "strategy" in s
        assert "win_rate" in s
        assert "max_drawdown_pct" in s


# =========================================================================
# Backtester Engine Tests
# =========================================================================


class TestBacktester:
    def test_basic_backtest(self, sample_data: pd.DataFrame) -> None:
        strategy = AlternatingStrategy(interval=10)
        bt = Backtester(strategy=strategy, initial_capital=100000)
        result = bt.run(sample_data, symbol="TEST")

        assert result.total_trades > 0
        assert result.strategy_name == "Alternating"
        assert result.symbol == "TEST"

    def test_empty_data(self) -> None:
        strategy = AlternatingStrategy()
        bt = Backtester(strategy=strategy)
        result = bt.run(pd.DataFrame(), symbol="TEST")
        assert result.total_trades == 0
        assert result.final_capital == result.initial_capital

    def test_slippage_applied(self, sample_data: pd.DataFrame) -> None:
        strategy = AlternatingStrategy(interval=20)
        bt_no_slip = Backtester(strategy=strategy, slippage_pct=0.0)
        bt_with_slip = Backtester(strategy=strategy, slippage_pct=0.1)

        r1 = bt_no_slip.run(sample_data, "TEST")
        r2 = bt_with_slip.run(sample_data, "TEST")

        # With slippage, PnL should be worse
        assert r2.total_pnl <= r1.total_pnl

    def test_stop_loss_triggers(self, sample_data: pd.DataFrame) -> None:
        # Very tight stop loss — should trigger frequently
        strategy = AlternatingStrategy(interval=10, sl_pct=0.01)
        bt = Backtester(strategy=strategy)
        result = bt.run(sample_data, "TEST")
        sl_exits = [t for t in result.trades if t.exit_reason == "stop_loss"]
        assert len(sl_exits) > 0

    def test_commission_deducted(self, sample_data: pd.DataFrame) -> None:
        strategy = AlternatingStrategy(interval=20)
        bt_free = Backtester(strategy=strategy, commission=0.0)
        bt_comm = Backtester(strategy=strategy, commission=50.0)

        r1 = bt_free.run(sample_data, "TEST")
        r2 = bt_comm.run(sample_data, "TEST")

        assert r2.final_capital < r1.final_capital
