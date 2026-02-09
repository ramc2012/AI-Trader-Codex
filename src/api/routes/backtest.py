"""Backtesting API endpoints.

Provides REST endpoints to run strategy backtests, and retrieve
cached results by ID.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException

from src.api.schemas import (
    BacktestResultResponse,
    BacktestRunRequest,
    BacktestTradeResponse,
)
from src.strategies.backtester import Backtester
from src.strategies.base import BaseStrategy
from src.strategies.directional.bollinger_strategy import BollingerBandStrategy
from src.strategies.directional.ema_crossover import EMACrossoverStrategy
from src.strategies.directional.macd_strategy import MACDStrategy
from src.strategies.directional.rsi_reversal import RSIReversalStrategy
from src.strategies.directional.supertrend_strategy import SupertrendStrategy
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["Backtest"])

# Strategy registry mapping names to classes
_STRATEGY_REGISTRY: Dict[str, type[BaseStrategy]] = {
    "ema_crossover": EMACrossoverStrategy,
    "rsi_reversal": RSIReversalStrategy,
    "macd": MACDStrategy,
    "bollinger": BollingerBandStrategy,
    "supertrend": SupertrendStrategy,
}

# In-memory result cache (id -> response)
_result_cache: Dict[int, BacktestResultResponse] = {}
_next_id: int = 1


# =========================================================================
# Endpoints
# =========================================================================


@router.post("/backtest/run", response_model=BacktestResultResponse)
def run_backtest(request: BacktestRunRequest) -> BacktestResultResponse:
    """Run a strategy backtest and return the results.

    Instantiates the strategy from the registry, fetches or generates
    sample OHLC data, runs the Backtester, and caches the result.

    Args:
        request: Backtest configuration including strategy name,
            symbol, date range, capital, and trade parameters.

    Returns:
        BacktestResultResponse with trade-level and summary metrics.

    Raises:
        HTTPException: If the strategy name is not in the registry.
    """
    global _next_id

    strategy_name = request.strategy.lower().strip()
    if strategy_name not in _STRATEGY_REGISTRY:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown strategy '{request.strategy}'. "
                f"Available: {list(_STRATEGY_REGISTRY.keys())}"
            ),
        )

    # Instantiate strategy
    strategy_cls = _STRATEGY_REGISTRY[strategy_name]
    strategy = strategy_cls()

    # Determine date range
    end_date = request.end_date or datetime.now()
    start_date = request.start_date or (end_date - timedelta(days=90))

    # Generate sample OHLC data (fallback when DB is not available)
    data = _generate_sample_data(request.symbol, start_date, end_date)

    # Create and run backtester
    backtester = Backtester(
        strategy=strategy,
        initial_capital=request.initial_capital,
        quantity=request.quantity,
        commission=request.commission,
        slippage_pct=request.slippage_pct,
    )

    result = backtester.run(data, symbol=request.symbol)

    # Build response
    trades = [
        BacktestTradeResponse(
            entry_time=t.entry_time,
            exit_time=t.exit_time,
            symbol=t.symbol,
            side=t.side,
            entry_price=t.entry_price,
            exit_price=t.exit_price,
            quantity=t.quantity,
            pnl=round(t.pnl, 2),
            pnl_pct=round(t.pnl_pct, 2),
            stop_loss=t.stop_loss,
            target=t.target,
            exit_reason=t.exit_reason,
        )
        for t in result.trades
    ]

    response = BacktestResultResponse(
        id=_next_id,
        strategy_name=result.strategy_name,
        symbol=result.symbol,
        start_date=result.start_date,
        end_date=result.end_date,
        initial_capital=result.initial_capital,
        final_capital=round(result.final_capital, 2),
        total_trades=result.total_trades,
        winning_trades=result.winning_trades,
        losing_trades=result.losing_trades,
        win_rate=round(result.win_rate, 1),
        total_pnl=round(result.total_pnl, 2),
        total_return_pct=round(result.total_return_pct, 2),
        max_drawdown=round(result.max_drawdown, 2),
        profit_factor=round(result.profit_factor, 2),
        avg_win=round(result.avg_win, 2),
        avg_loss=round(result.avg_loss, 2),
        trades=trades,
    )

    # Cache result
    _result_cache[_next_id] = response
    _next_id += 1

    logger.info(
        "backtest_api_complete",
        strategy=strategy_name,
        id=response.id,
        trades=response.total_trades,
    )

    return response


@router.get("/backtest/results", response_model=List[BacktestResultResponse])
def list_backtest_results() -> List[BacktestResultResponse]:
    """List all cached backtest results.

    Returns:
        List of BacktestResultResponse in insertion order.
    """
    return list(_result_cache.values())


@router.get("/backtest/results/{result_id}", response_model=BacktestResultResponse)
def get_backtest_result(result_id: int) -> BacktestResultResponse:
    """Get a single cached backtest result by ID.

    Args:
        result_id: The numeric result identifier.

    Returns:
        The cached BacktestResultResponse.

    Raises:
        HTTPException: If the result is not found.
    """
    if result_id not in _result_cache:
        raise HTTPException(
            status_code=404,
            detail=f"Backtest result {result_id} not found.",
        )
    return _result_cache[result_id]


# =========================================================================
# Sample Data Generation
# =========================================================================


def _generate_sample_data(
    symbol: str,
    start_date: datetime,
    end_date: datetime,
) -> pd.DataFrame:
    """Generate synthetic OHLC data for backtesting when DB is unavailable.

    Creates realistic-looking price data using a geometric random walk
    seeded from the symbol name for reproducibility.

    Args:
        symbol: Trading symbol (used for seed).
        start_date: Start of the data range.
        end_date: End of the data range.

    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume.
    """
    # Generate business-day timestamps
    dates = pd.bdate_range(start=start_date, end=end_date, freq="B")
    if len(dates) == 0:
        dates = pd.bdate_range(
            start=start_date, periods=60, freq="B"
        )

    n = len(dates)

    # Seed from symbol for reproducibility
    seed = sum(ord(c) for c in symbol) % (2**31)
    rng = np.random.default_rng(seed)

    # Random walk
    base_price = 20000.0 if "NIFTY" in symbol.upper() else 45000.0
    returns = rng.normal(0.0003, 0.012, n)
    prices = base_price * np.cumprod(1 + returns)

    # Construct OHLC
    daily_vol = prices * 0.015
    high = prices + rng.uniform(0, 1, n) * daily_vol
    low = prices - rng.uniform(0, 1, n) * daily_vol
    open_prices = low + rng.uniform(0, 1, n) * (high - low)
    close_prices = low + rng.uniform(0, 1, n) * (high - low)
    volume = rng.integers(100_000, 500_000, n)

    data = pd.DataFrame(
        {
            "timestamp": dates[:n],
            "open": open_prices,
            "high": high,
            "low": low,
            "close": close_prices,
            "volume": volume,
        }
    )

    return data
