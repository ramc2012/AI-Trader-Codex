"""ATR (Average True Range) API routes."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db
from src.database.operations import get_ohlc_candles
from src.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/atr", tags=["atr"])


def _compute_atr(candles: list, period: int = 14) -> list[dict]:
    """Compute ATR series from OHLC candles."""
    if len(candles) < 2:
        return []

    # True Range
    trs: list[float] = [float(candles[0].high) - float(candles[0].low)]
    for i in range(1, len(candles)):
        hl = float(candles[i].high) - float(candles[i].low)
        hc = abs(float(candles[i].high) - float(candles[i - 1].close))
        lc = abs(float(candles[i].low) - float(candles[i - 1].close))
        trs.append(max(hl, hc, lc))

    # ATR (Wilder's smoothing)
    atrs: list[float | None] = []
    for i in range(len(trs)):
        if i < period - 1:
            atrs.append(None)
        elif i == period - 1:
            atrs.append(sum(trs[:period]) / period)
        else:
            prev = atrs[-1]
            if prev is not None:
                atrs.append((prev * (period - 1) + trs[i]) / period)
            else:
                atrs.append(None)

    results = []
    for i, c in enumerate(candles):
        if atrs[i] is not None:
            atr_val = atrs[i]
            close_val = float(c.close)
            results.append({
                "timestamp": c.timestamp.isoformat(),
                "close": close_val,
                "atr": round(atr_val, 2),
                "upper_band": round(close_val + atr_val, 2),
                "lower_band": round(close_val - atr_val, 2),
                "atr_pct": round((atr_val / close_val) * 100, 3) if close_val > 0 else 0,
            })

    return results


@router.get("/{symbol}")
async def get_atr(
    symbol: str,
    timeframe: str = Query("1D", description="Candle timeframe"),
    period: int = Query(14, ge=2, le=50),
    days: int = Query(90, ge=10, le=365),
    db: AsyncSession = Depends(get_db),
):
    """Compute ATR-N for a symbol."""
    end = datetime.utcnow()
    start = end - timedelta(days=days)

    candles = await get_ohlc_candles(db, symbol, timeframe, start, end, limit=days * 10)
    if len(candles) < period + 1:
        return {"error": "Insufficient data", "symbol": symbol, "candles": len(candles)}

    atr_data = _compute_atr(list(candles), period)
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "period": period,
        "data": atr_data,
        "latest": atr_data[-1] if atr_data else None,
    }


@router.get("/batch")
async def get_batch_atr(
    symbols: str = Query(..., description="Comma-separated symbols"),
    timeframe: str = Query("1D"),
    period: int = Query(14, ge=2, le=50),
    days: int = Query(30, ge=5, le=365),
    db: AsyncSession = Depends(get_db),
):
    """Compute latest ATR for multiple symbols."""
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    end = datetime.utcnow()
    start = end - timedelta(days=days)

    results = []
    for sym in symbol_list:
        candles = await get_ohlc_candles(db, sym, timeframe, start, end, limit=days * 10)
        if len(candles) > period:
            atr_data = _compute_atr(list(candles), period)
            if atr_data:
                latest = atr_data[-1]
                latest["symbol"] = sym
                results.append(latest)

    return {"symbols": results}
