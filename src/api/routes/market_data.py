"""Market data API endpoints.

Provides REST access to OHLC candles, recent ticks, health checks,
and symbol listings.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db
from src.config.constants import ALL_TIMEFRAMES, INDEX_SYMBOLS
from src.config.market_hours import IST
from src.database.connection import check_db_health
from src.database.operations import (
    count_ohlc_candles,
    get_latest_ohlc_timestamp,
    get_ohlc_candles,
    get_recent_ticks,
)

router = APIRouter(tags=["Market Data"])


# =========================================================================
# Response Models
# =========================================================================


class HealthResponse(BaseModel):
    status: str
    database: bool
    version: str = "0.1.0"


class CandleResponse(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class OHLCResponse(BaseModel):
    symbol: str
    timeframe: str
    count: int
    candles: list[CandleResponse]


class TickResponse(BaseModel):
    symbol: str
    timestamp: datetime
    ltp: float
    bid: float | None = None
    ask: float | None = None
    volume: int = 0


class SymbolInfo(BaseModel):
    symbol: str
    timeframes: list[str]


class SymbolsResponse(BaseModel):
    symbols: list[SymbolInfo]


class DataSummary(BaseModel):
    symbol: str
    timeframe: str
    count: int
    latest_timestamp: datetime | None


# =========================================================================
# Endpoints
# =========================================================================


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """System health check including database connectivity."""
    db_ok = await check_db_health()
    status = "healthy" if db_ok else "degraded"
    return HealthResponse(status=status, database=db_ok)


@router.get("/symbols", response_model=SymbolsResponse)
async def list_symbols() -> SymbolsResponse:
    """List all supported symbols and their available timeframes."""
    return SymbolsResponse(
        symbols=[
            SymbolInfo(symbol=s, timeframes=list(ALL_TIMEFRAMES))
            for s in INDEX_SYMBOLS
        ]
    )


@router.get("/ohlc/{symbol:path}", response_model=OHLCResponse)
async def get_ohlc(
    symbol: str,
    timeframe: str = Query(default="D", description="Candle timeframe (1, 5, 15, 60, D, W, M)"),
    start: datetime | None = Query(default=None, description="Start timestamp (ISO 8601)"),
    end: datetime | None = Query(default=None, description="End timestamp (ISO 8601)"),
    limit: int = Query(default=500, ge=1, le=10000, description="Max candles to return"),
    db: AsyncSession = Depends(get_db),
) -> OHLCResponse:
    """Fetch OHLC candle data for a symbol.

    Example: GET /api/v1/ohlc/NSE:NIFTY50-INDEX?timeframe=D&limit=100
    """
    if timeframe not in ALL_TIMEFRAMES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid timeframe '{timeframe}'. Valid: {ALL_TIMEFRAMES}",
        )

    now = datetime.now(tz=IST)
    if end is None:
        end = now
    if start is None:
        start = end - timedelta(days=30)

    candles = await get_ohlc_candles(db, symbol, timeframe, start, end, limit)

    return OHLCResponse(
        symbol=symbol,
        timeframe=timeframe,
        count=len(candles),
        candles=[
            CandleResponse(
                timestamp=c.timestamp,
                open=float(c.open),
                high=float(c.high),
                low=float(c.low),
                close=float(c.close),
                volume=c.volume,
            )
            for c in candles
        ],
    )


@router.get("/ticks/{symbol:path}", response_model=list[TickResponse])
async def get_ticks(
    symbol: str,
    limit: int = Query(default=100, ge=1, le=1000, description="Max ticks to return"),
    db: AsyncSession = Depends(get_db),
) -> list[TickResponse]:
    """Fetch the most recent ticks for a symbol.

    Example: GET /api/v1/ticks/NSE:NIFTY50-INDEX?limit=50
    """
    ticks = await get_recent_ticks(db, symbol, limit)
    return [
        TickResponse(
            symbol=t.symbol,
            timestamp=t.timestamp,
            ltp=float(t.ltp),
            bid=float(t.bid) if t.bid else None,
            ask=float(t.ask) if t.ask else None,
            volume=t.volume,
        )
        for t in ticks
    ]


@router.get("/summary/{symbol:path}", response_model=list[DataSummary])
async def get_data_summary(
    symbol: str,
    db: AsyncSession = Depends(get_db),
) -> list[DataSummary]:
    """Get a summary of stored data for each timeframe.

    Shows row counts and latest timestamps — useful for monitoring
    data collection status.
    """
    summaries = []
    for tf in ALL_TIMEFRAMES:
        count = await count_ohlc_candles(db, symbol, tf)
        latest = await get_latest_ohlc_timestamp(db, symbol, tf)
        summaries.append(
            DataSummary(
                symbol=symbol,
                timeframe=tf,
                count=count,
                latest_timestamp=latest,
            )
        )
    return summaries
