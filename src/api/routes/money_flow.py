"""Money Flow analysis API routes.

Computes net money flow from market snapshot data and groups
results by sector.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime
import math
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_fyers_client
from src.database.operations import get_assets, get_market_snapshots
from src.integrations.fyers_client import FyersClient
from src.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/money-flow", tags=["money-flow"])

_FLOW_CACHE_TTL_SECONDS = 8
_flow_cache: tuple[datetime, dict[str, Any]] | None = None
_FALLBACK_QUOTES = [
    "NSE:NIFTY50-INDEX",
    "NSE:NIFTYBANK-INDEX",
    "NSE:FINNIFTY-INDEX",
    "NSE:RELIANCE-EQ",
    "NSE:HDFCBANK-EQ",
    "NSE:ICICIBANK-EQ",
    "NSE:TCS-EQ",
    "NSE:INFY-EQ",
    "NSE:SBIN-EQ",
    "NSE:LT-EQ",
    "NSE:ITC-EQ",
    "NSE:BHARTIARTL-EQ",
    "NSE:HINDUNILVR-EQ",
    "NSE:KOTAKBANK-EQ",
    "NSE:AXISBANK-EQ",
]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return parsed


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _sector_for_symbol(symbol: str, asset_map: dict[str, Any]) -> tuple[str, str]:
    asset = asset_map.get(symbol)
    if asset:
        return (asset.name, asset.sector or "Unknown")
    if symbol.endswith("-INDEX"):
        return (symbol.split(":")[-1], "Index")
    if symbol.endswith("-EQ"):
        return (symbol.split(":")[-1].replace("-EQ", ""), "Equity")
    return (symbol, "Unknown")


async def _fallback_live_snapshots(client: FyersClient) -> list[dict[str, Any]]:
    """Fetch a lightweight live snapshot if market_snapshot table is empty."""
    if not client.is_authenticated:
        return []
    try:
        raw = await asyncio.to_thread(lambda: client.get_quotes(_FALLBACK_QUOTES))
    except Exception as exc:
        logger.warning("money_flow_fallback_quotes_failed", error=str(exc))
        return []

    rows = raw.get("d", []) if isinstance(raw, dict) else []
    snapshots: list[dict[str, Any]] = []
    for row in rows:
        payload = row.get("v", {}) if isinstance(row, dict) else {}
        symbol = str(payload.get("symbol") or row.get("n") or "").strip()
        if not symbol:
            continue
        ltp = _safe_float(payload.get("lp"), 0.0)
        if ltp <= 0:
            continue
        change = _safe_float(payload.get("ch"), 0.0)
        change_pct = _safe_float(payload.get("chp"), 0.0)
        volume = _safe_int(payload.get("volume") or payload.get("vol_traded_today"), 0)
        oi = _safe_int(payload.get("oi"), 0)
        snapshots.append(
            {
                "symbol": symbol,
                "ltp": ltp,
                "change_percent": change_pct,
                "change": change,
                "volume": volume,
                "oi": oi,
            }
        )
    return snapshots


# =========================================================================
# Endpoints
# =========================================================================


@router.get("/snapshot")
async def get_money_flow_snapshot(
    db: AsyncSession = Depends(get_db),
    client: FyersClient = Depends(get_fyers_client),
) -> dict[str, Any]:
    """Return market snapshot data with net money flow calculations.

    For each symbol:
      net_flow = volume * (change_percent / 100)

    Results are grouped by sector from the asset registry.
    """
    global _flow_cache
    now = datetime.utcnow()
    if _flow_cache is not None:
        created_at, cached = _flow_cache
        if (now - created_at).total_seconds() <= _FLOW_CACHE_TTL_SECONDS:
            return cached

    logger.info("money_flow_snapshot_request")

    # Fetch all market snapshots — table may not exist yet; return empty gracefully.
    try:
        snapshots = await get_market_snapshots(db)
    except Exception as exc:
        logger.warning("market_snapshot_unavailable", error=str(exc))
        # Rollback the failed transaction so subsequent queries can proceed
        await db.rollback()
        snapshots = []

    snapshot_rows: list[dict[str, Any]] = []
    source = "database"
    if snapshots:
        for snap in snapshots:
            snapshot_rows.append(
                {
                    "symbol": snap.symbol,
                    "ltp": _safe_float(snap.ltp),
                    "change_percent": _safe_float(snap.change_percent or 0.0),
                    "change": _safe_float(snap.change or 0.0),
                    "volume": _safe_int(snap.volume or 0),
                    "oi": _safe_int(snap.oi or 0),
                }
            )
    else:
        source = "live_fyers_quotes"
        snapshot_rows = await _fallback_live_snapshots(client)

    # Fetch asset registry for sector mapping
    try:
        assets = await get_assets(db)
    except Exception as exc:
        logger.warning("get_assets_failed", error=str(exc))
        assets = []
    asset_map: dict[str, Any] = {a.symbol: a for a in assets}

    stocks: list[dict[str, Any]] = []
    sector_flows: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"net_flow": 0.0, "stocks": []},
    )

    for snap in snapshot_rows:
        symbol = str(snap.get("symbol") or "")
        ltp = _safe_float(snap.get("ltp"), 0.0)
        change = _safe_float(snap.get("change"), 0.0)
        change_pct = _safe_float(snap.get("change_percent"), 0.0)
        volume = _safe_int(snap.get("volume"), 0)
        oi = _safe_int(snap.get("oi"), 0)
        if not symbol or ltp <= 0:
            continue

        # Net flow = volume * (change_percent / 100)
        net_flow = _safe_float(round(volume * (change_pct / 100), 2), 0.0)

        # Turnover approximation = volume * ltp
        turnover = _safe_float(round(volume * ltp, 2), 0.0)

        # Sector from asset registry
        name, sector = _sector_for_symbol(symbol, asset_map)
        stock_row = {
            "symbol": symbol,
            "name": name,
            "ltp": ltp,
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
            "change_percent": round(change_pct, 2),
            "volume": volume,
            "oi": oi,
            "net_flow": net_flow,
            "sector": sector,
            "turnover": turnover,
        }
        stocks.append(stock_row)

        sector_flows[sector]["net_flow"] += net_flow
        sector_flows[sector]["stocks"].append(stock_row)

    # Sort stocks by absolute net flow descending for the table
    stocks.sort(key=lambda x: abs(_safe_float(x["net_flow"])), reverse=True)
    total_net_flow = round(sum(float(s["net_flow"]) for s in stocks), 2)
    top_gainer = max(stocks, key=lambda s: float(s["change_pct"]), default=None)
    top_loser = min(stocks, key=lambda s: float(s["change_pct"]), default=None)

    # Build sector rows expected by frontend dashboard.
    sectors: list[dict[str, Any]] = []
    for sector, data in sorted(
        sector_flows.items(),
        key=lambda x: abs(float(x[1]["net_flow"])),
        reverse=True,
    ):
        bucket = data["stocks"]
        sec_top_gainer = max(bucket, key=lambda s: float(s["change_pct"]), default=None)
        sec_top_loser = min(bucket, key=lambda s: float(s["change_pct"]), default=None)
        sectors.append(
            {
                "sector": sector,
                "net_flow": round(float(data["net_flow"]), 2),
                "stock_count": len(bucket),
                "count": len(bucket),  # backward compatibility for old clients
                "top_gainer": sec_top_gainer["symbol"] if sec_top_gainer else "",
                "top_loser": sec_top_loser["symbol"] if sec_top_loser else "",
            }
        )

    payload = {
        "timestamp": now.isoformat(),
        "source": source,
        "total_net_flow": total_net_flow,
        "top_gainer": top_gainer,
        "top_loser": top_loser,
        "stocks": stocks,
        "sectors": sectors,
        # backward compatibility for older clients
        "items": stocks,
    }
    _flow_cache = (now, payload)
    return payload
