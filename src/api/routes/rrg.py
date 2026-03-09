"""Relative Rotation Graph API routes."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.analysis.rrg_engine import UNIVERSE_GROUPS, compute_rrg
from src.api.dependencies import get_db
from src.database.operations import get_ohlc_candles
from src.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/rrg", tags=["rrg"])


@router.get("/groups")
async def list_groups():
    """Return available RRG universe groups."""
    return {
        key: {"label": val["label"], "benchmark": val["benchmark"], "count": len(val["symbols"])}
        for key, val in UNIVERSE_GROUPS.items()
    }


@router.get("/data")
async def get_rrg_data(
    group: str = Query("NIFTY50", description="Universe group key"),
    timeframe: str = Query("1D", description="Candle timeframe"),
    days: int = Query(90, ge=10, le=365),
    tail: int = Query(8, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
):
    """Compute RRG data for a universe group.

    Returns RS-Ratio and RS-Momentum for each symbol with trailing tail.
    """
    universe = UNIVERSE_GROUPS.get(group)
    if not universe:
        return {"error": f"Unknown group: {group}", "available": list(UNIVERSE_GROUPS.keys())}

    end = datetime.utcnow()
    start = end - timedelta(days=days)

    # Fetch benchmark candles
    benchmark_candles = await get_ohlc_candles(
        db, universe["benchmark"], timeframe, start, end, limit=days * 2
    )
    if len(benchmark_candles) < 20:
        return {"error": "Insufficient benchmark data", "group": group}

    # Fetch symbol candles
    symbol_candles = {}
    for sym in universe["symbols"]:
        candles = await get_ohlc_candles(db, sym, timeframe, start, end, limit=days * 2)
        if len(candles) >= 20:
            symbol_candles[sym] = candles

    # Compute RRG
    rrg_data = compute_rrg(symbol_candles, benchmark_candles, tail_length=tail)

    return {
        "group": group,
        "label": universe["label"],
        "benchmark": universe["benchmark"],
        "timeframe": timeframe,
        "symbols": rrg_data,
    }
