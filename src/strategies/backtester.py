"""Backtesting engine for evaluating trading strategies.

Runs a strategy against historical data, tracks trades, and computes
performance metrics. Supports stop-loss, targets, and end-of-day exits.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from src.strategies.base import (
    BacktestResult,
    BacktestTrade,
    BaseStrategy,
    Signal,
    SignalType,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


class Backtester:
    """Backtesting engine that runs a strategy on historical data.

    Args:
        strategy: Strategy to backtest.
        initial_capital: Starting capital.
        quantity: Default trade quantity per signal.
        commission: Per-trade commission/fees.
        slippage_pct: Assumed slippage as % of price.
        exit_on_eod: Force-close open positions at end of day.
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        initial_capital: float = 100000.0,
        quantity: int = 1,
        commission: float = 0.0,
        slippage_pct: float = 0.0,
        exit_on_eod: bool = True,
    ) -> None:
        self.strategy = strategy
        self.initial_capital = initial_capital
        self.quantity = quantity
        self.commission = commission
        self.slippage_pct = slippage_pct
        self.exit_on_eod = exit_on_eod

    def run(
        self,
        data: pd.DataFrame,
        symbol: str = "",
    ) -> BacktestResult:
        """Run the backtest on historical data.

        Args:
            data: DataFrame with columns: timestamp, open, high, low, close, volume.
                  Must be sorted by timestamp ascending.
            symbol: Symbol being tested.

        Returns:
            BacktestResult with trades and performance metrics.
        """
        if data.empty:
            return BacktestResult(
                strategy_name=self.strategy.name,
                symbol=symbol,
                start_date=datetime.now(),
                end_date=datetime.now(),
                initial_capital=self.initial_capital,
                final_capital=self.initial_capital,
            )

        signals = self.strategy.generate_signals(data)
        signal_map: dict[int, Signal] = {}
        for sig in signals:
            # Map signal to the data row index by timestamp
            matching = data.index[data["timestamp"] == sig.timestamp].tolist()
            if matching:
                signal_map[matching[0]] = sig

        trades: list[BacktestTrade] = []
        capital = self.initial_capital
        current_trade: BacktestTrade | None = None

        for idx in range(len(data)):
            row = data.iloc[idx]
            ts = row["timestamp"]
            high = float(row["high"])
            low = float(row["low"])
            close = float(row["close"])

            # Check stop-loss and target on open trade
            if current_trade is not None:
                exit_price: float | None = None
                exit_reason = ""

                if current_trade.side == "BUY":
                    if current_trade.stop_loss and low <= current_trade.stop_loss:
                        exit_price = current_trade.stop_loss
                        exit_reason = "stop_loss"
                    elif current_trade.target and high >= current_trade.target:
                        exit_price = current_trade.target
                        exit_reason = "target"
                else:  # SELL
                    if current_trade.stop_loss and high >= current_trade.stop_loss:
                        exit_price = current_trade.stop_loss
                        exit_reason = "stop_loss"
                    elif current_trade.target and low <= current_trade.target:
                        exit_price = current_trade.target
                        exit_reason = "target"

                if exit_price is not None:
                    current_trade = self._close_trade(
                        current_trade, exit_price, ts, exit_reason
                    )
                    capital += current_trade.pnl
                    trades.append(current_trade)
                    current_trade = None

            # Check for new signal
            if idx in signal_map:
                sig = signal_map[idx]

                # Close opposing trade if exists
                if current_trade is not None:
                    if (sig.signal_type == SignalType.BUY and current_trade.side == "SELL") or \
                       (sig.signal_type == SignalType.SELL and current_trade.side == "BUY"):
                        current_trade = self._close_trade(
                            current_trade, close, ts, "signal"
                        )
                        capital += current_trade.pnl
                        trades.append(current_trade)
                        current_trade = None

                # Open new trade
                if current_trade is None and sig.is_actionable:
                    entry_price = sig.price or close
                    entry_price = self._apply_slippage(entry_price, sig.signal_type)

                    current_trade = BacktestTrade(
                        entry_time=ts,
                        symbol=symbol,
                        side=sig.signal_type.value,
                        entry_price=entry_price,
                        quantity=self.quantity,
                        stop_loss=sig.stop_loss,
                        target=sig.target,
                    )
                    capital -= self.commission

        # Close any remaining open trade at the last close
        if current_trade is not None:
            last_row = data.iloc[-1]
            current_trade = self._close_trade(
                current_trade,
                float(last_row["close"]),
                last_row["timestamp"],
                "eod",
            )
            capital += current_trade.pnl
            trades.append(current_trade)

        final_capital = capital - self.commission * len(trades)

        result = BacktestResult(
            strategy_name=self.strategy.name,
            symbol=symbol,
            start_date=data["timestamp"].iloc[0],
            end_date=data["timestamp"].iloc[-1],
            initial_capital=self.initial_capital,
            final_capital=final_capital,
            trades=trades,
        )

        logger.info(
            "backtest_complete",
            strategy=self.strategy.name,
            trades=result.total_trades,
            win_rate=f"{result.win_rate:.1f}%",
            total_pnl=f"{result.total_pnl:.2f}",
        )
        return result

    def _close_trade(
        self,
        trade: BacktestTrade,
        exit_price: float,
        exit_time: datetime,
        reason: str,
    ) -> BacktestTrade:
        """Close a trade and compute PnL."""
        exit_price = self._apply_slippage(
            exit_price,
            SignalType.SELL if trade.side == "BUY" else SignalType.BUY,
        )
        trade.exit_price = exit_price
        trade.exit_time = exit_time
        trade.exit_reason = reason

        if trade.side == "BUY":
            trade.pnl = (exit_price - trade.entry_price) * trade.quantity
        else:
            trade.pnl = (trade.entry_price - exit_price) * trade.quantity

        if trade.entry_price > 0:
            trade.pnl_pct = trade.pnl / (trade.entry_price * trade.quantity) * 100

        trade.pnl -= self.commission
        return trade

    def _apply_slippage(self, price: float, side: SignalType) -> float:
        """Apply slippage to price based on trade direction."""
        slippage = price * (self.slippage_pct / 100)
        if side == SignalType.BUY:
            return price + slippage  # buy higher
        return price - slippage  # sell lower
