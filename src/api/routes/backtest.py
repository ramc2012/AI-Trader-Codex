"""Backtesting API endpoints.

Provides REST endpoints to run strategy backtests, and retrieve
cached results by ID.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import math
import random
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db
from src.api.schemas import (
    BacktestResultResponse,
    BacktestRunRequest,
    BacktestTradeResponse,
)
from src.config.settings import Environment, get_settings
from src.database.operations import get_ohlc_candles
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
# Helpers
# =========================================================================


def _timeframe_to_minutes(timeframe: str) -> int:
    """Convert API timeframe strings to minute resolution."""
    tf = timeframe.strip().upper()
    mapping = {
        "1": 1,
        "3": 3,
        "5": 5,
        "15": 15,
        "30": 30,
        "60": 60,
        "D": 1440,
        "1D": 1440,
        "W": 10080,
        "1W": 10080,
        "M": 43200,  # 30-day approximation
        "1M": 43200,
    }
    if tf in mapping:
        return mapping[tf]
    try:
        return max(1, int(tf))
    except ValueError:
        return 15


def _safe_round(value: float, digits: int = 2) -> float:
    """Round floats while ensuring JSON-safe finite values."""
    numeric = float(value)
    if not math.isfinite(numeric):
        return 0.0
    return round(numeric, digits)


def _build_synthetic_backtest_data(
    start_date: datetime,
    end_date: datetime,
    timeframe: str,
) -> pd.DataFrame:
    """Generate deterministic OHLCV fallback data for local/test usage."""
    step_minutes = _timeframe_to_minutes(timeframe)
    min_bars = 120
    max_bars = 600

    if end_date <= start_date:
        end_date = start_date + timedelta(minutes=step_minutes * (min_bars - 1))

    span_minutes = int((end_date - start_date).total_seconds() // 60)
    bar_count = max(min_bars, min(max_bars, (span_minutes // step_minutes) + 1))
    start_ts = end_date - timedelta(minutes=step_minutes * (bar_count - 1))

    rng = random.Random(20)  # stable output across runs
    price = 22000.0
    rows: list[dict[str, Any]] = []

    for i in range(bar_count):
        ts = start_ts + timedelta(minutes=i * step_minutes)
        regime = (i // 40) % 5
        if regime == 0:
            drift, vol = 0.0, 8.0
        elif regime == 1:
            drift, vol = -22.0, 10.0
        elif regime == 2:
            drift, vol = 28.0, 12.0
        elif regime == 3:
            drift, vol = -15.0, 18.0
        else:
            drift, vol = 18.0, 20.0

        change = drift + rng.gauss(0.0, vol)
        close_price = max(1000.0, price + change)
        open_price = max(1000.0, close_price - (change / 2))
        wick = abs(change) + abs(rng.gauss(8.0, 3.0)) + 10.0
        high_price = max(open_price, close_price) + wick
        low_price = max(1.0, min(open_price, close_price) - wick)

        rows.append(
            {
                "timestamp": ts,
                "open": round(open_price, 2),
                "high": round(high_price, 2),
                "low": round(low_price, 2),
                "close": round(close_price, 2),
                "volume": int(10000 + rng.random() * 5000),
            }
        )
        price = close_price

    return pd.DataFrame(rows)


# =========================================================================
# Endpoints
# =========================================================================


@router.post("/backtest/run", response_model=BacktestResultResponse)
async def run_backtest(
    request: BacktestRunRequest,
    db: AsyncSession = Depends(get_db),
) -> BacktestResultResponse:
    """Run a strategy backtest and return the results.

    Instantiates the strategy from the registry, fetches historical OHLC
    data from DB, runs the Backtester, and caches the result.

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

    # Prefer persisted historical candles from DB.
    start_naive = start_date.replace(tzinfo=None) if start_date.tzinfo else start_date
    end_naive = end_date.replace(tzinfo=None) if end_date.tzinfo else end_date
    candles = []
    try:
        candles = await get_ohlc_candles(
            db,
            request.symbol,
            request.timeframe,
            start_naive,
            end_naive,
            limit=20000,
        )
    except Exception as exc:
        logger.warning(
            "backtest_db_fetch_failed",
            symbol=request.symbol,
            timeframe=request.timeframe,
            error=str(exc),
        )
        try:
            await db.rollback()
        except Exception:
            pass

    data_source = "database"
    if candles:
        data = pd.DataFrame(
            [
                {
                    "timestamp": c.timestamp,
                    "open": float(c.open),
                    "high": float(c.high),
                    "low": float(c.low),
                    "close": float(c.close),
                    "volume": int(c.volume),
                }
                for c in candles
            ]
        ).sort_values("timestamp")
    else:
        settings = get_settings()
        if settings.app_env == Environment.PRODUCTION:
            raise HTTPException(
                status_code=422,
                detail=(
                    "No historical OHLC data available for requested symbol/timeframe/date range. "
                    "Backtest requires persisted real market data."
                ),
            )

        logger.warning(
            "backtest_synthetic_fallback",
            symbol=request.symbol,
            timeframe=request.timeframe,
            start=str(start_naive),
            end=str(end_naive),
        )
        data = _build_synthetic_backtest_data(
            start_date=start_naive,
            end_date=end_naive,
            timeframe=request.timeframe,
        )
        data_source = "synthetic"

    if data.empty:
        raise HTTPException(
            status_code=422,
            detail=(
                "No historical OHLC data available for requested symbol/timeframe/date range. "
                "Backtest requires persisted real market data."
            ),
        )

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
        final_capital=_safe_round(result.final_capital, 2),
        total_trades=result.total_trades,
        winning_trades=result.winning_trades,
        losing_trades=result.losing_trades,
        win_rate=_safe_round(result.win_rate, 1),
        total_pnl=_safe_round(result.total_pnl, 2),
        total_return_pct=_safe_round(result.total_return_pct, 2),
        max_drawdown=_safe_round(result.max_drawdown, 2),
        profit_factor=_safe_round(result.profit_factor, 2),
        avg_win=_safe_round(result.avg_win, 2),
        avg_loss=_safe_round(result.avg_loss, 2),
        data_source=data_source,
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
