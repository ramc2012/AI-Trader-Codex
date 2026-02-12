"""Market data API endpoints.

Provides REST access to OHLC candles, recent ticks, health checks,
and symbol listings.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_fyers_client
from src.api.schemas import (
    CollectionRequest,
    CollectionStatusResponse,
    DataSummaryItem,
    WatchlistSymbolResponse,
)
from src.config.constants import ALL_TIMEFRAMES, INDEX_SYMBOLS
from src.config.market_hours import IST
from src.database.connection import check_db_health
from src.database.operations import (
    count_ohlc_candles,
    get_latest_ohlc_timestamp,
    get_ohlc_candles,
    get_recent_ticks,
)
from src.integrations.fyers_client import FyersClient
from src.utils.logger import get_logger

router = APIRouter(tags=["Market Data"])
logger = get_logger(__name__)

# =========================================================================
# Collection Job Tracking
# =========================================================================

_collection_jobs: dict[str, CollectionStatusResponse] = {}
_collection_lock = threading.Lock()


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


# =========================================================================
# Watchlist Endpoints
# =========================================================================

# Display name mapping for clean UI
_DISPLAY_NAMES: dict[str, str] = {
    "NSE:NIFTY50-INDEX": "Nifty 50",
    "NSE:NIFTYBANK-INDEX": "Bank Nifty",
    "BSE:SENSEX-INDEX": "Sensex",
}


@router.get("/watchlist/symbols", response_model=list[WatchlistSymbolResponse])
async def get_watchlist_symbols(
    db: AsyncSession = Depends(get_db),
) -> list[WatchlistSymbolResponse]:
    """Get all tracked symbols with their data collection summary.

    Returns candle counts and latest timestamps for each symbol across
    all timeframes, plus the latest closing price.
    """
    results = []
    for symbol in INDEX_SYMBOLS:
        summaries = []
        for tf in ALL_TIMEFRAMES:
            count = await count_ohlc_candles(db, symbol, tf)
            latest = await get_latest_ohlc_timestamp(db, symbol, tf)
            summaries.append(
                DataSummaryItem(
                    timeframe=tf,
                    count=count,
                    latest_timestamp=latest.isoformat() if latest else None,
                )
            )

        # Get latest price from the most recent daily candle
        latest_price = None
        price_change_pct = None
        now = datetime.now(tz=IST)
        try:
            candles = await get_ohlc_candles(
                db, symbol, "D",
                start=now - timedelta(days=7),
                end=now,
                limit=2,
            )
            if candles:
                latest_price = float(candles[-1].close)
                if len(candles) >= 2:
                    prev_close = float(candles[-2].close)
                    if prev_close > 0:
                        price_change_pct = ((latest_price - prev_close) / prev_close) * 100
        except Exception:
            pass

        results.append(
            WatchlistSymbolResponse(
                symbol=symbol,
                display_name=_DISPLAY_NAMES.get(symbol, symbol.split(":")[-1]),
                data_summary=summaries,
                latest_price=latest_price,
                price_change_pct=price_change_pct,
            )
        )
    return results


@router.post("/watchlist/collect", response_model=CollectionStatusResponse)
async def start_collection(
    request: CollectionRequest,
    client: FyersClient = Depends(get_fyers_client),
) -> CollectionStatusResponse:
    """Trigger background OHLC data collection for a symbol.

    Requires Fyers authentication. The collection runs in a background
    thread and progress can be tracked via GET /watchlist/collect/status.
    """
    # Check authentication
    is_auth = await asyncio.to_thread(lambda: client.is_authenticated)
    if not is_auth:
        raise HTTPException(
            status_code=401,
            detail="Fyers authentication required. Connect via Settings page.",
        )

    if request.timeframe not in ALL_TIMEFRAMES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid timeframe '{request.timeframe}'. Valid: {ALL_TIMEFRAMES}",
        )

    job_key = f"{request.symbol}:{request.timeframe}"

    # Check if already collecting
    with _collection_lock:
        existing = _collection_jobs.get(job_key)
        if existing and existing.status == "collecting":
            return existing

    # Create initial status
    status = CollectionStatusResponse(
        symbol=request.symbol,
        timeframe=request.timeframe,
        status="collecting",
        progress=0.0,
        candles_collected=0,
    )
    with _collection_lock:
        _collection_jobs[job_key] = status

    # Start background collection
    asyncio.create_task(
        _run_collection(client, request.symbol, request.timeframe, request.days_back, job_key)
    )

    return status


async def _run_collection(
    client: FyersClient,
    symbol: str,
    timeframe: str,
    days_back: int,
    job_key: str,
) -> None:
    """Run OHLC collection in a background thread."""
    from datetime import date as date_type
    from src.data.collectors.ohlc_collector import OHLCCollector, CollectionProgress

    def on_progress(progress: CollectionProgress) -> None:
        """Thread-safe progress callback."""
        with _collection_lock:
            job = _collection_jobs.get(job_key)
            if job:
                job.progress = progress.progress_pct
                job.candles_collected = progress.total_candles

    try:
        collector = OHLCCollector(
            client=client,
            symbols=[symbol],
            on_progress=on_progress,
        )

        end_date = date_type.today()
        start_date = end_date - timedelta(days=days_back)

        result = await asyncio.to_thread(
            collector.collect_symbol,
            symbol,
            timeframe,
            start_date,
            end_date,
        )

        with _collection_lock:
            job = _collection_jobs.get(job_key)
            if job:
                job.status = "completed" if result.success else "failed"
                job.progress = 100.0
                job.candles_collected = len(result.candles)
                if not result.success and result.progress.errors:
                    job.error = "; ".join(result.progress.errors[:3])

        logger.info(
            "collection_completed",
            symbol=symbol,
            timeframe=timeframe,
            candles=len(result.candles),
        )

    except Exception as exc:
        with _collection_lock:
            job = _collection_jobs.get(job_key)
            if job:
                job.status = "failed"
                job.error = str(exc)
        logger.error(
            "collection_failed",
            symbol=symbol,
            timeframe=timeframe,
            error=str(exc),
        )


@router.get("/watchlist/collect/status", response_model=list[CollectionStatusResponse])
async def get_collection_status() -> list[CollectionStatusResponse]:
    """Get status of all data collection jobs."""
    with _collection_lock:
        return list(_collection_jobs.values())
