"""Real-time market scanner API routes.

Scans watchlist symbols for actionable setups using live Fyers quote data.
Detects: momentum breakouts, volume spikes, OI changes, and price reversals.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_fyers_client
from src.config.agent_universe import NIFTY50_WATCHLIST_SYMBOLS
from src.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/scanner", tags=["scanner"])


# ─── Scan target symbols ──────────────────────────────────────────────────────

_NIFTY50_STOCKS = list(NIFTY50_WATCHLIST_SYMBOLS)

_INDICES = [
    "NSE:NIFTY50-INDEX",
    "NSE:NIFTYBANK-INDEX",
    "NSE:FINNIFTY-INDEX",
    "NSE:NIFTYMIDCAP50-INDEX",
    "BSE:SENSEX-INDEX",
]


# ─── Scan filters ─────────────────────────────────────────────────────────────

def _classify_signal(change_pct: float, volume_ratio: float, oi_change_pct: float) -> str:
    """Return a signal label based on price change, volume, and OI."""
    if change_pct >= 1.5 and volume_ratio >= 1.5:
        return "strong_breakout"
    if change_pct >= 0.5 and volume_ratio >= 1.2:
        return "breakout"
    if change_pct <= -1.5 and volume_ratio >= 1.5:
        return "strong_breakdown"
    if change_pct <= -0.5 and volume_ratio >= 1.2:
        return "breakdown"
    if abs(change_pct) < 0.2 and volume_ratio >= 2.0:
        return "volume_spike"
    if oi_change_pct >= 10 and change_pct >= 0:
        return "long_buildup"
    if oi_change_pct >= 10 and change_pct < 0:
        return "short_buildup"
    if change_pct >= 0.3:
        return "bullish"
    if change_pct <= -0.3:
        return "bearish"
    return "neutral"


_SIGNAL_PRIORITY = {
    "strong_breakout": 1,
    "strong_breakdown": 2,
    "breakout": 3,
    "breakdown": 4,
    "long_buildup": 5,
    "short_buildup": 6,
    "volume_spike": 7,
    "bullish": 8,
    "bearish": 9,
    "neutral": 10,
}

_SIGNAL_COLORS = {
    "strong_breakout": "emerald",
    "breakout": "green",
    "strong_breakdown": "red",
    "breakdown": "orange",
    "long_buildup": "blue",
    "short_buildup": "purple",
    "volume_spike": "yellow",
    "bullish": "teal",
    "bearish": "rose",
    "neutral": "slate",
}


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/scan")
async def run_scanner(
    filter_type: str = Query(
        "all",
        description="Filter: all | breakout | breakdown | volume | oi | indices",
    ),
    min_change_pct: float = Query(0.0, description="Min absolute % change to include"),
    min_volume_ratio: float = Query(0.0, description="Min volume/avg ratio to include"),
) -> dict[str, Any]:
    """Scan Nifty 50 stocks and indices for actionable setups.

    Fetches live quotes from Fyers and classifies each symbol into
    signal categories: breakout, breakdown, volume spike, OI buildup, etc.
    """
    logger.info("scanner_scan_request", filter_type=filter_type)

    try:
        fyers = get_fyers_client()
        if not fyers.is_authenticated:
            return {
                "results": [],
                "total": 0,
                "filter": filter_type,
                "note": "Not authenticated with Fyers — login to enable live scanner",
                "timestamp": datetime.utcnow().isoformat(),
            }

        # Choose symbols based on filter
        if filter_type == "indices":
            symbols = _INDICES
        else:
            symbols = _NIFTY50_STOCKS

        # Fyers quote API accepts comma-separated symbols
        # Fetch in batches of 50 (API limit)
        BATCH = 50
        all_quotes: list[dict[str, Any]] = []

        for i in range(0, len(symbols), BATCH):
            batch = symbols[i : i + BATCH]
            raw = await asyncio.to_thread(
                lambda b=batch: fyers.get_quotes(b)
            )
            if raw and "d" in raw:
                all_quotes.extend(raw["d"])

        results: list[dict[str, Any]] = []

        for q in all_quotes:
            v = q.get("v", {})
            symbol = v.get("symbol", q.get("n", ""))
            ltp = float(v.get("lp", 0) or 0)
            prev_close = float(v.get("prev_close_price", ltp) or ltp)
            volume = int(v.get("volume", 0) or 0)
            avg_volume = int(v.get("avg_trade_val", 0) or 0)
            oi = int(v.get("oi", 0) or 0)
            oi_prev = int(v.get("prev_oi", oi) or oi)

            change = ltp - prev_close
            change_pct = round((change / prev_close * 100) if prev_close > 0 else 0, 2)
            # avg_trade_val is turnover; approximate avg_volume = avg_trade_val / ltp
            avg_vol_approx = int(avg_volume / ltp) if ltp > 0 and avg_volume > 0 else volume
            volume_ratio = round(volume / avg_vol_approx if avg_vol_approx > 0 else 1.0, 2)
            oi_change = oi - oi_prev
            oi_change_pct = round(oi_change / oi_prev * 100 if oi_prev > 0 else 0, 2)

            # Apply filters
            if abs(change_pct) < min_change_pct:
                continue
            if volume_ratio < min_volume_ratio:
                continue

            signal = _classify_signal(change_pct, volume_ratio, oi_change_pct)

            # Apply category filter
            if filter_type == "breakout" and "breakout" not in signal:
                continue
            if filter_type == "breakdown" and "breakdown" not in signal:
                continue
            if filter_type == "volume" and signal not in ("volume_spike", "strong_breakout", "strong_breakdown"):
                continue
            if filter_type == "oi" and signal not in ("long_buildup", "short_buildup"):
                continue

            # Extract display name (strip exchange prefix and suffix)
            display = symbol
            if ":" in display:
                display = display.split(":")[1]
            display = display.replace("-EQ", "").replace("-INDEX", "")

            results.append({
                "symbol": symbol,
                "display_name": display,
                "ltp": ltp,
                "change": round(change, 2),
                "change_pct": change_pct,
                "volume": volume,
                "volume_ratio": volume_ratio,
                "oi": oi,
                "oi_change": oi_change,
                "oi_change_pct": oi_change_pct,
                "signal": signal,
                "signal_color": _SIGNAL_COLORS.get(signal, "slate"),
                "signal_priority": _SIGNAL_PRIORITY.get(signal, 10),
            })

        # Sort by priority then by absolute change %
        results.sort(key=lambda x: (x["signal_priority"], -abs(x["change_pct"])))

        return {
            "results": results,
            "total": len(results),
            "filter": filter_type,
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as exc:
        logger.warning("scanner_failed", error=str(exc))
        return {
            "results": [],
            "total": 0,
            "filter": filter_type,
            "note": f"Scanner error: {exc}",
            "timestamp": datetime.utcnow().isoformat(),
        }


@router.get("/filters")
async def get_scanner_filters() -> dict[str, Any]:
    """Return available scanner filter options."""
    return {
        "filters": [
            {"id": "all", "label": "All Signals", "description": "Show all symbols sorted by signal strength"},
            {"id": "breakout", "label": "Breakouts", "description": "Price up + elevated volume"},
            {"id": "breakdown", "label": "Breakdowns", "description": "Price down + elevated volume"},
            {"id": "volume", "label": "Volume Spikes", "description": "Unusual volume activity"},
            {"id": "oi", "label": "OI Buildup", "description": "Open interest increasing (long/short buildup)"},
            {"id": "indices", "label": "Indices Only", "description": "Nifty, Bank Nifty, Fin Nifty, Sensex"},
        ],
        "signals": [
            {"id": "strong_breakout", "label": "Strong Breakout", "color": "emerald"},
            {"id": "breakout", "label": "Breakout", "color": "green"},
            {"id": "strong_breakdown", "label": "Strong Breakdown", "color": "red"},
            {"id": "breakdown", "label": "Breakdown", "color": "orange"},
            {"id": "long_buildup", "label": "Long Buildup", "color": "blue"},
            {"id": "short_buildup", "label": "Short Buildup", "color": "purple"},
            {"id": "volume_spike", "label": "Volume Spike", "color": "yellow"},
            {"id": "bullish", "label": "Bullish", "color": "teal"},
            {"id": "bearish", "label": "Bearish", "color": "rose"},
            {"id": "neutral", "label": "Neutral", "color": "slate"},
        ],
    }
