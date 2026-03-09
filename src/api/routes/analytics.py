"""Volume Profile and analytics API routes."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db
from src.database.operations import get_ohlc_candles
from src.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/analytics", tags=["analytics"])


def _compute_volume_profile(candles: list, num_bins: int = 30) -> dict:
    """Compute volume profile from OHLC candles.

    Groups volume by price bins and finds POC, high/low volume nodes.
    """
    if not candles:
        return {"bins": [], "poc": 0}

    all_highs = [float(c.high) for c in candles]
    all_lows = [float(c.low) for c in candles]
    price_high = max(all_highs)
    price_low = min(all_lows)

    if price_high == price_low:
        return {"bins": [], "poc": price_low}

    bin_size = (price_high - price_low) / num_bins
    bins: dict[int, dict] = {}

    for i in range(num_bins):
        bin_low = price_low + i * bin_size
        bin_high = bin_low + bin_size
        bins[i] = {
            "price_low": round(bin_low, 2),
            "price_high": round(bin_high, 2),
            "price_mid": round((bin_low + bin_high) / 2, 2),
            "volume": 0,
            "buy_volume": 0,
            "sell_volume": 0,
            "candle_count": 0,
        }

    # Distribute volume across bins
    for c in candles:
        c_high = float(c.high)
        c_low = float(c.low)
        c_close = float(c.close)
        c_open = float(c.open)
        c_vol = int(c.volume)

        is_bullish = c_close >= c_open

        # Find bins that this candle spans
        low_bin = max(0, int((c_low - price_low) / bin_size))
        high_bin = min(num_bins - 1, int((c_high - price_low) / bin_size))

        # Distribute volume proportionally
        span = high_bin - low_bin + 1
        vol_per_bin = c_vol // max(span, 1)

        for b in range(low_bin, high_bin + 1):
            if b in bins:
                bins[b]["volume"] += vol_per_bin
                bins[b]["candle_count"] += 1
                if is_bullish:
                    bins[b]["buy_volume"] += vol_per_bin
                else:
                    bins[b]["sell_volume"] += vol_per_bin

    bin_list = list(bins.values())
    poc_bin = max(bin_list, key=lambda b: b["volume"]) if bin_list else {"price_mid": 0}
    total_volume = sum(b["volume"] for b in bin_list)

    # High/low volume nodes
    avg_volume = total_volume / max(num_bins, 1)
    for b in bin_list:
        b["is_hvn"] = b["volume"] > avg_volume * 1.5  # High Volume Node
        b["is_lvn"] = b["volume"] < avg_volume * 0.5   # Low Volume Node
        b["pct"] = round(b["volume"] / total_volume * 100, 2) if total_volume > 0 else 0

    return {
        "bins": bin_list,
        "poc": poc_bin["price_mid"],
        "total_volume": total_volume,
        "price_high": price_high,
        "price_low": price_low,
        "num_bins": num_bins,
    }


@router.get("/volume-profile/{symbol}")
async def get_volume_profile(
    symbol: str,
    timeframe: str = Query("1D", description="Candle timeframe"),
    days: int = Query(30, ge=1, le=365),
    bins: int = Query(30, ge=10, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Compute volume profile for a symbol."""
    end = datetime.utcnow()
    start = end - timedelta(days=days)

    candles = await get_ohlc_candles(db, symbol, timeframe, start, end, limit=days * 500)
    if not candles:
        return {"error": "No data", "symbol": symbol}

    profile = _compute_volume_profile(list(candles), bins)
    return {"symbol": symbol, "timeframe": timeframe, "days": days, **profile}


@router.get("/volume-profile")
async def get_volume_profile_query(
    symbol: str = Query(..., description="Symbol"),
    timeframe: str = Query("1D"),
    days: int = Query(30, ge=1, le=365),
    bins: int = Query(30, ge=10, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Compute volume profile (query param version)."""
    end = datetime.utcnow()
    start = end - timedelta(days=days)

    candles = await get_ohlc_candles(db, symbol, timeframe, start, end, limit=days * 500)
    if not candles:
        return {"error": "No data", "symbol": symbol}

    profile = _compute_volume_profile(list(candles), bins)
    return {"symbol": symbol, "timeframe": timeframe, "days": days, **profile}
