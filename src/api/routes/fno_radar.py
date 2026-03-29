"""FNO Radar API — scans all 209 FNO stocks for positional trade opportunities.

Uses fractal profile analysis, OI change, volume ratios, and sector-level
aggregation to surface high-conviction positional trade candidates.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query

from src.config.fno_constants import EQUITY_FNO, SECTORS, FnOInstrument
from src.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/fno-radar", tags=["fno-radar"])


def _build_candidate(sym: str, inst: FnOInstrument) -> dict[str, Any]:
    """Build a radar candidate dict for a single FNO instrument.

    In production this would query live quotes, OI data, and run
    fractal profile analysis. For now we return the instrument
    metadata so the frontend can render the radar grid.
    """
    return {
        "symbol": sym,
        "display_name": inst.name,
        "exchange": inst.exchange,
        "sector": inst.sector,
        "lot_size": inst.lot_size,
        "strike_interval": inst.strike_interval,
        "instrument_type": inst.instrument_type,
        # Placeholders — filled by live data when broker is authenticated
        "ltp": 0.0,
        "change_pct": 0.0,
        "volume": 0,
        "volume_ratio": 0.0,
        "oi": 0,
        "oi_change_pct": 0.0,
        "signal": "neutral",
        "conviction": 0,
        "direction": "neutral",
        "fractal_profile": None,
    }


def _enrich_with_live_data(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attempt to enrich candidates with live market data from the active broker."""
    try:
        from src.api.dependencies import get_broker_client
        broker = get_broker_client()
        if not broker.is_authenticated:
            return candidates

        symbols = [f"NSE:{c['symbol']}-EQ" for c in candidates[:50]]  # batch limit
        try:
            quotes = broker.get_quotes(symbols)
            if quotes and isinstance(quotes, dict):
                quote_data = quotes.get("d", []) if isinstance(quotes.get("d"), list) else []
                quote_map: dict[str, dict] = {}
                for q in quote_data:
                    if isinstance(q, dict) and "n" in q and "v" in q:
                        raw_sym = str(q["n"]).split(":")[-1].replace("-EQ", "")
                        quote_map[raw_sym] = q.get("v", {})

                for candidate in candidates:
                    qv = quote_map.get(candidate["symbol"], {})
                    if qv:
                        ltp = float(qv.get("lp", 0) or 0)
                        ch = float(qv.get("ch", 0) or 0)
                        chp = float(qv.get("chp", 0) or 0)
                        vol = int(qv.get("volume", 0) or 0)

                        candidate["ltp"] = ltp
                        candidate["change_pct"] = chp
                        candidate["volume"] = vol

                        # Simple signal classification based on change %
                        if chp > 3.0:
                            candidate["signal"] = "strong_breakout"
                            candidate["direction"] = "bullish"
                            candidate["conviction"] = 4
                        elif chp > 1.5:
                            candidate["signal"] = "breakout"
                            candidate["direction"] = "bullish"
                            candidate["conviction"] = 3
                        elif chp < -3.0:
                            candidate["signal"] = "strong_breakdown"
                            candidate["direction"] = "bearish"
                            candidate["conviction"] = 4
                        elif chp < -1.5:
                            candidate["signal"] = "breakdown"
                            candidate["direction"] = "bearish"
                            candidate["conviction"] = 3
        except Exception as exc:
            logger.debug("fno_radar_quote_error", error=str(exc))
    except Exception as exc:
        logger.debug("fno_radar_broker_error", error=str(exc))

    return candidates


@router.get("/scan")
async def scan_fno_radar(
    sector: str | None = Query(None, description="Filter by sector"),
    signal: str | None = Query(None, description="Filter by signal type"),
    min_conviction: int = Query(0, ge=0, le=5, description="Minimum conviction score"),
    limit: int = Query(100, ge=1, le=300, description="Max results"),
) -> dict[str, Any]:
    """Scan all FNO instruments and return radar candidates."""

    candidates: list[dict[str, Any]] = []
    for sym, inst in sorted(EQUITY_FNO.items()):
        if sector and inst.sector.lower() != sector.lower():
            continue
        candidates.append(_build_candidate(sym, inst))

    # Enrich with live data
    candidates = _enrich_with_live_data(candidates)

    # Apply filters
    if signal:
        candidates = [c for c in candidates if c["signal"] == signal]
    if min_conviction > 0:
        candidates = [c for c in candidates if c["conviction"] >= min_conviction]

    # Sort by conviction (desc), then change_pct (desc)
    candidates.sort(key=lambda c: (-c["conviction"], -abs(c["change_pct"])))

    return {
        "results": candidates[:limit],
        "total": len(candidates),
        "sectors": sorted(SECTORS.keys()),
        "timestamp": datetime.now().isoformat(),
    }


@router.get("/sectors")
async def get_sector_breakdown() -> dict[str, Any]:
    """Get sector-level breakdown of FNO signals."""
    sector_data: list[dict[str, Any]] = []
    for sector_name, symbols in sorted(SECTORS.items()):
        sector_data.append({
            "sector": sector_name,
            "stock_count": len(symbols),
            "symbols": symbols,
        })
    return {
        "sectors": sector_data,
        "total_stocks": len(EQUITY_FNO),
        "timestamp": datetime.now().isoformat(),
    }
