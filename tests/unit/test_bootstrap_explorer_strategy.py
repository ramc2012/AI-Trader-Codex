from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from src.strategies.base import SignalType
from src.strategies.directional.bootstrap_explorer import BootstrapExplorerStrategy


def _frame(closes: list[float], symbol: str = "TEST:ABC") -> pd.DataFrame:
    start = datetime(2026, 1, 1)
    rows = []
    for idx, close in enumerate(closes):
        ts = start + timedelta(days=idx)
        rows.append(
            {
                "timestamp": ts,
                "open": close * 0.99,
                "high": close * 1.01,
                "low": close * 0.98,
                "close": close,
                "volume": 1000 + idx,
                "symbol": symbol,
            }
        )
    return pd.DataFrame(rows)


def test_bootstrap_explorer_emits_buy_signal_in_uptrend() -> None:
    strategy = BootstrapExplorerStrategy()
    data = _frame([100, 101, 102, 103, 104, 105, 106, 107, 108])

    signals = strategy.generate_signals(data)

    assert signals
    assert signals[-1].signal_type == SignalType.BUY
    assert signals[-1].strategy_name == "Bootstrap_Explorer"
    assert signals[-1].metadata["bootstrap_exploration"] is True


def test_bootstrap_explorer_emits_sell_signal_in_downtrend() -> None:
    strategy = BootstrapExplorerStrategy()
    data = _frame([108, 107, 106, 105, 104, 103, 102, 101, 100])

    signals = strategy.generate_signals(data)

    assert signals
    assert signals[-1].signal_type == SignalType.SELL
    assert signals[-1].stop_loss is not None
    assert signals[-1].target is not None
