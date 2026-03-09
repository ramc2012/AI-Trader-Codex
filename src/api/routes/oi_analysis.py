"""Open Interest analysis API routes.

Provides OI quadrant classification, ATM watchlist, and OI trending
data for NIFTY/BANKNIFTY indices and FnO stocks.

Falls back to live Fyers API data when local DB tables are empty.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_fyers_client
from src.database.models import OptionChain
from src.database.operations import (
    get_market_snapshots,
    get_ohlc_candles,
    get_option_chain_oi_history,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/oi", tags=["oi-analysis"])


# =========================================================================
# Constants
# =========================================================================

INDEX_UNDERLYINGS = ["NSE:NIFTY50-INDEX", "NSE:NIFTYBANK-INDEX"]

_UNDERLYING_NAMES: dict[str, str] = {
    "NSE:NIFTY50-INDEX": "NIFTY",
    "NSE:NIFTYBANK-INDEX": "BANKNIFTY",
    "NSE:FINNIFTY-INDEX": "FINNIFTY",
    "NSE:NIFTYMIDCAP50-INDEX": "MIDCPNIFTY",
    "BSE:SENSEX-INDEX": "SENSEX",
}

# Top FnO stocks with OI data available via Fyers
_FNO_STOCKS = [
    "NSE:RELIANCE-EQ", "NSE:TCS-EQ", "NSE:INFY-EQ", "NSE:HDFCBANK-EQ",
    "NSE:ICICIBANK-EQ", "NSE:SBIN-EQ", "NSE:AXISBANK-EQ", "NSE:KOTAKBANK-EQ",
    "NSE:LT-EQ", "NSE:BAJFINANCE-EQ", "NSE:HINDUNILVR-EQ", "NSE:ITC-EQ",
    "NSE:BHARTIARTL-EQ", "NSE:SUNPHARMA-EQ", "NSE:TATAMOTORS-EQ",
    "NSE:MARUTI-EQ", "NSE:WIPRO-EQ", "NSE:HCLTECH-EQ", "NSE:TECHM-EQ",
    "NSE:TITAN-EQ", "NSE:ULTRACEMCO-EQ", "NSE:ONGC-EQ", "NSE:NTPC-EQ",
    "NSE:POWERGRID-EQ", "NSE:NESTLEIND-EQ", "NSE:TATASTEEL-EQ",
    "NSE:JSWSTEEL-EQ", "NSE:INDUSINDBK-EQ", "NSE:HINDALCO-EQ",
    "NSE:DRREDDY-EQ", "NSE:BPCL-EQ", "NSE:APOLLOHOSP-EQ",
    "NSE:ADANIPORTS-EQ", "NSE:BAJAJ-AUTO-EQ", "NSE:CIPLA-EQ",
    "NSE:DIVISLAB-EQ", "NSE:EICHERMOT-EQ", "NSE:HEROMOTOCO-EQ",
    "NSE:GRASIM-EQ", "NSE:COALINDIA-EQ",
]

# Index underlyings for ATM watchlist
_ATM_UNDERLYINGS = [
    "NSE:NIFTY50-INDEX",
    "NSE:NIFTYBANK-INDEX",
    "NSE:FINNIFTY-INDEX",
    "NSE:NIFTYMIDCAP50-INDEX",
]

# Strike intervals per index
_STRIKE_INTERVALS: dict[str, float] = {
    "NSE:NIFTY50-INDEX": 50.0,
    "NSE:NIFTYBANK-INDEX": 100.0,
    "NSE:FINNIFTY-INDEX": 50.0,
    "NSE:NIFTYMIDCAP50-INDEX": 100.0,
    "BSE:SENSEX-INDEX": 100.0,
}


# =========================================================================
# Helpers
# =========================================================================


def _classify_quadrant(price_change: float, oi_change: int) -> str:
    """Classify a symbol into one of 4 OI-price quadrants (snake_case keys)."""
    if price_change >= 0 and oi_change >= 0:
        return "long_buildup"
    elif price_change < 0 and oi_change >= 0:
        return "short_buildup"
    elif price_change >= 0 and oi_change < 0:
        return "short_covering"
    else:
        return "long_unwinding"


def _find_atm_strike(spot_price: float, strike_interval: float = 50.0) -> float:
    """Round spot price to the nearest ATM strike."""
    return round(round(spot_price / strike_interval) * strike_interval, 2)


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


async def _get_latest_option_chain_snapshot(
    db: AsyncSession,
    underlying: str,
) -> list[Any]:
    """Fetch the most recent option chain snapshot for an underlying."""
    latest_ts_stmt = (
        select(OptionChain.timestamp)
        .where(OptionChain.underlying == underlying)
        .order_by(OptionChain.timestamp.desc())
        .limit(1)
    )
    result = await db.execute(latest_ts_stmt)
    latest_ts = result.scalar_one_or_none()
    if latest_ts is None:
        return []

    expiry_stmt = (
        select(OptionChain.expiry)
        .where(OptionChain.underlying == underlying, OptionChain.timestamp == latest_ts)
        .order_by(OptionChain.expiry)
        .limit(1)
    )
    result = await db.execute(expiry_stmt)
    nearest_expiry = result.scalar_one_or_none()
    if nearest_expiry is None:
        return []

    rows_stmt = (
        select(OptionChain)
        .where(
            OptionChain.underlying == underlying,
            OptionChain.expiry == nearest_expiry,
            OptionChain.timestamp == latest_ts,
        )
        .order_by(OptionChain.strike, OptionChain.option_type)
    )
    result = await db.execute(rows_stmt)
    return list(result.scalars().all())


async def _fyers_quadrants_fallback(top_n: int) -> dict[str, Any]:
    """Fetch live Fyers quotes for FnO stocks and classify into quadrants."""
    fyers = get_fyers_client()
    if not fyers.is_authenticated:
        return {
            "long_buildup": [],
            "short_buildup": [],
            "short_covering": [],
            "long_unwinding": [],
            "timestamp": datetime.utcnow().isoformat(),
            "source": "unauthenticated",
        }

    # Fetch in batches of 50
    symbols = _FNO_STOCKS
    all_quotes: list[dict[str, Any]] = []
    BATCH = 50
    for i in range(0, len(symbols), BATCH):
        batch = symbols[i : i + BATCH]
        try:
            raw = await asyncio.to_thread(lambda b=batch: fyers.get_quotes(b))
            if raw and "d" in raw:
                all_quotes.extend(raw["d"])
        except Exception as exc:
            logger.warning("fyers_oi_quadrant_batch_failed", error=str(exc))

    quadrants: dict[str, list[dict[str, Any]]] = {
        "long_buildup": [],
        "short_buildup": [],
        "short_covering": [],
        "long_unwinding": [],
    }

    for q in all_quotes:
        v = q.get("v", {})
        symbol = v.get("symbol", q.get("n", ""))
        ltp = _safe_float(v.get("lp"))
        prev_close = _safe_float(v.get("prev_close_price", ltp))
        if prev_close <= 0:
            prev_close = ltp

        change_pct = ((ltp - prev_close) / prev_close * 100) if prev_close > 0 else 0.0
        oi = _safe_int(v.get("oi"))
        prev_oi = _safe_int(v.get("prev_oi", oi))
        oi_change = oi - prev_oi
        oi_change_pct = (oi_change / max(prev_oi, 1)) * 100

        # Only include stocks with meaningful OI data
        if oi == 0:
            continue

        category = _classify_quadrant(change_pct, oi_change)

        # Display name: strip exchange prefix + suffix
        display = symbol
        if ":" in display:
            display = display.split(":")[1]
        display = display.replace("-EQ", "")

        quadrants[category].append({
            "symbol": display,
            "ltp": round(ltp, 2),
            "price_change": round(ltp - prev_close, 2),
            "price_change_pct": round(change_pct, 2),
            "oi": oi,
            "oi_change": oi_change,
            "oi_change_pct": round(oi_change_pct, 2),
            "volume": _safe_int(v.get("volume")),
        })

    # Sort by absolute OI change, take top N
    for cat in quadrants:
        quadrants[cat] = sorted(
            quadrants[cat],
            key=lambda x: abs(x["oi_change"]),
            reverse=True,
        )[:top_n]

    return {
        **quadrants,
        "timestamp": datetime.utcnow().isoformat(),
        "source": "fyers_live",
    }


async def _fyers_atm_watchlist_fallback() -> dict[str, Any]:
    """Fetch live spot prices and option chain data from Fyers for ATM watchlist."""
    fyers = get_fyers_client()
    if not fyers.is_authenticated:
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "entries": [],
        }

    # Fetch spot prices for all ATM underlyings at once
    try:
        raw_quotes = await asyncio.to_thread(
            lambda: fyers.get_quotes(_ATM_UNDERLYINGS)
        )
    except Exception as exc:
        logger.warning("fyers_atm_quotes_failed", error=str(exc))
        return {"timestamp": datetime.utcnow().isoformat(), "entries": []}

    spot_map: dict[str, float] = {}
    if raw_quotes and "d" in raw_quotes:
        for q in raw_quotes["d"]:
            v = q.get("v", {})
            sym = v.get("symbol", q.get("n", ""))
            spot_map[sym] = _safe_float(v.get("lp"))

    entries: list[dict[str, Any]] = []

    for underlying in _ATM_UNDERLYINGS:
        spot = spot_map.get(underlying, 0.0)
        if spot <= 0:
            continue

        interval = _STRIKE_INTERVALS.get(underlying, 50.0)
        atm = _find_atm_strike(spot, interval)

        try:
            raw_chain = await asyncio.to_thread(
                lambda u=underlying, s=int(atm): fyers.get_option_chain(
                    symbol=u,
                    strike_count=3,
                )
            )
        except Exception as exc:
            logger.warning("fyers_atm_chain_failed", symbol=underlying, error=str(exc))
            continue

        if not raw_chain or "data" not in raw_chain:
            continue

        chain_data = raw_chain["data"]
        option_list = chain_data.get("optionsChain", [])

        # Find CE and PE at or nearest to ATM
        ce_ltp = pe_ltp = 0.0
        ce_oi = pe_oi = 0
        ce_iv = pe_iv = 0.0

        for row in option_list:
            strike = _safe_float(row.get("strikePrice") or row.get("strike"))
            if abs(strike - atm) < 0.01:
                opt_type = row.get("option_type", "").upper()
                if opt_type == "CE":
                    ce_ltp = _safe_float(row.get("ltp"))
                    ce_oi = _safe_int(row.get("oi"))
                    ce_iv = _safe_float(row.get("implied_volatility") or row.get("iv"))
                elif opt_type == "PE":
                    pe_ltp = _safe_float(row.get("ltp"))
                    pe_oi = _safe_int(row.get("oi"))
                    pe_iv = _safe_float(row.get("implied_volatility") or row.get("iv"))

        if ce_ltp == 0 and pe_ltp == 0:
            # Try to get from expiry data
            expiry_data = chain_data.get("expiryData", [])
            if expiry_data:
                for exp in expiry_data[:1]:
                    ce_ltp = _safe_float(exp.get("CE_ltp") or exp.get("ce_ltp"))
                    pe_ltp = _safe_float(exp.get("PE_ltp") or exp.get("pe_ltp"))
                    ce_oi = _safe_int(exp.get("CE_oi") or exp.get("ce_oi"))
                    pe_oi = _safe_int(exp.get("PE_oi") or exp.get("pe_oi"))
                    ce_iv = _safe_float(exp.get("CE_iv") or exp.get("ce_iv"))
                    pe_iv = _safe_float(exp.get("PE_iv") or exp.get("pe_iv"))

        pcr = round(pe_oi / max(ce_oi, 1), 4)
        straddle = round(ce_ltp + pe_ltp, 2)

        entries.append({
            "symbol": underlying,
            "display_name": _UNDERLYING_NAMES.get(underlying, underlying),
            "spot": round(spot, 2),
            "atm_strike": atm,
            "ce_ltp": round(ce_ltp, 2),
            "ce_oi": ce_oi,
            "ce_iv": round(ce_iv, 2),
            "ce_delta": 0.5,  # ATM delta approximation
            "pe_ltp": round(pe_ltp, 2),
            "pe_oi": pe_oi,
            "pe_iv": round(pe_iv, 2),
            "pe_delta": -0.5,
            "pcr": pcr,
            "straddle_price": straddle,
        })

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "entries": entries,
    }


# =========================================================================
# Endpoints
# =========================================================================


@router.get("/quadrants")
async def get_oi_quadrants(
    top_n: int = Query(10, ge=1, le=50, description="Top N per category"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Classify FnO stocks into OI quadrants.

    Falls back to live Fyers quotes when no local DB data is available.
    """
    logger.info("oi_quadrants_request", top_n=top_n)

    # Try DB-based approach first
    try:
        latest_ts_stmt = (
            select(OptionChain.timestamp)
            .order_by(OptionChain.timestamp.desc())
            .limit(1)
        )
        result = await db.execute(latest_ts_stmt)
        latest_ts = result.scalar_one_or_none()
    except Exception as exc:
        logger.warning("oi_quadrants_db_error", error=str(exc))
        await db.rollback()
        latest_ts = None

    if latest_ts is None:
        # Live Fyers fallback
        return await _fyers_quadrants_fallback(top_n)

    # Aggregate total OI per underlying from option chain
    try:
        agg_stmt = (
            select(
                OptionChain.underlying,
                func.sum(OptionChain.oi).label("total_oi"),
                func.sum(OptionChain.prev_oi).label("total_prev_oi"),
            )
            .where(OptionChain.timestamp == latest_ts)
            .group_by(OptionChain.underlying)
        )
        agg_result = await db.execute(agg_stmt)
        oi_rows = agg_result.all()
    except Exception as exc:
        logger.warning("oi_quadrants_agg_failed", error=str(exc))
        await db.rollback()
        return await _fyers_quadrants_fallback(top_n)

    symbols_needed = [row.underlying for row in oi_rows]
    try:
        snapshots = await get_market_snapshots(db, symbols_needed)
    except Exception as exc:
        logger.warning("oi_market_snapshot_unavailable", error=str(exc))
        await db.rollback()
        snapshots = []
    snap_map: dict[str, Any] = {s.symbol: s for s in snapshots}

    quadrants: dict[str, list[dict[str, Any]]] = {
        "long_buildup": [], "short_buildup": [],
        "short_covering": [], "long_unwinding": [],
    }

    for row in oi_rows:
        underlying = row.underlying
        total_oi = int(row.total_oi or 0)
        total_prev_oi = int(row.total_prev_oi or 0)
        oi_change = total_oi - total_prev_oi

        price_change = 0.0
        snap = snap_map.get(underlying)
        if snap and snap.change_percent is not None:
            price_change = float(snap.change_percent)
        else:
            end = datetime.utcnow()
            start = end - timedelta(days=3)
            try:
                candles = await get_ohlc_candles(db, underlying, "1D", start, end, limit=5)
                if len(candles) >= 2:
                    prev_close = float(candles[-2].close)
                    curr_close = float(candles[-1].close)
                    if prev_close > 0:
                        price_change = ((curr_close - prev_close) / prev_close) * 100
            except Exception:
                pass

        category = _classify_quadrant(price_change, oi_change)
        ltp = float(snap.ltp) if snap else 0.0

        quadrants[category].append({
            "symbol": underlying,
            "ltp": ltp,
            "price_change": round(ltp - (ltp / (1 + price_change / 100)) if ltp and price_change else 0, 2),
            "price_change_pct": round(price_change, 2),
            "oi": total_oi,
            "oi_change": oi_change,
            "oi_change_pct": round((oi_change / max(total_prev_oi, 1)) * 100, 2),
            "volume": 0,
        })

    for cat in quadrants:
        quadrants[cat] = sorted(
            quadrants[cat], key=lambda x: abs(x["oi_change"]), reverse=True
        )[:top_n]

    return {**quadrants, "timestamp": latest_ts.isoformat()}


@router.get("/atm-watchlist")
async def get_atm_watchlist(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return ATM option data for index underlyings.

    Falls back to live Fyers option chain when DB is empty.
    """
    logger.info("atm_watchlist_request")

    # Try DB-based approach
    try:
        distinct_stmt = select(OptionChain.underlying).distinct()
        result = await db.execute(distinct_stmt)
        underlyings = [row[0] for row in result.all()]
    except Exception as exc:
        logger.warning("atm_watchlist_db_error", error=str(exc))
        await db.rollback()
        underlyings = []

    if not underlyings:
        # Fyers live fallback
        return await _fyers_atm_watchlist_fallback()

    # DB-based path
    try:
        snapshots = await get_market_snapshots(db, underlyings)
    except Exception as exc:
        logger.warning("atm_watchlist_snapshot_failed", error=str(exc))
        await db.rollback()
        return await _fyers_atm_watchlist_fallback()

    snap_map: dict[str, Any] = {s.symbol: s for s in snapshots}
    entries: list[dict[str, Any]] = []

    for underlying in underlyings:
        snap = snap_map.get(underlying)
        spot_price = float(snap.ltp) if snap else 0.0
        if spot_price <= 0:
            continue

        interval = _STRIKE_INTERVALS.get(underlying, 50.0)
        atm_strike = _find_atm_strike(spot_price, interval)
        chain_rows = await _get_latest_option_chain_snapshot(db, underlying)
        if not chain_rows:
            continue

        ce_row = pe_row = None
        for row in chain_rows:
            if abs(float(row.strike) - atm_strike) < 0.01:
                if row.option_type == "CE":
                    ce_row = row
                elif row.option_type == "PE":
                    pe_row = row

        ce_oi = int(ce_row.oi) if ce_row else 0
        pe_oi = int(pe_row.oi) if pe_row else 0
        ce_ltp = float(ce_row.ltp or 0) if ce_row else 0.0
        pe_ltp = float(pe_row.ltp or 0) if pe_row else 0.0

        entries.append({
            "symbol": underlying,
            "display_name": _UNDERLYING_NAMES.get(underlying, underlying),
            "spot": spot_price,
            "atm_strike": atm_strike,
            "ce_ltp": ce_ltp,
            "ce_oi": ce_oi,
            "ce_iv": float(ce_row.iv or 0) if ce_row else 0.0,
            "ce_delta": 0.5,
            "pe_ltp": pe_ltp,
            "pe_oi": pe_oi,
            "pe_iv": float(pe_row.iv or 0) if pe_row else 0.0,
            "pe_delta": -0.5,
            "pcr": round(pe_oi / max(ce_oi, 1), 4),
            "straddle_price": round(ce_ltp + pe_ltp, 2),
        })

    return {"timestamp": datetime.utcnow().isoformat(), "entries": entries}


@router.get("/trending/{symbol}")
async def get_oi_trending(
    symbol: str,
    expiry: date | None = Query(None, description="Expiry date (YYYY-MM-DD). Uses nearest if omitted."),
    limit: int = Query(200, ge=10, le=1000, description="Max data points"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return OI time-series for a symbol's ATM strike."""
    logger.info("oi_trending_request", symbol=symbol, expiry=expiry)

    try:
        snap_rows = await get_market_snapshots(db, [symbol])
    except Exception:
        await db.rollback()
        snap_rows = []

    if not snap_rows:
        raise HTTPException(status_code=404, detail=f"No market snapshot found for {symbol}")

    snap = snap_rows[0]
    spot_price = float(snap.ltp)
    interval = _STRIKE_INTERVALS.get(symbol, 50.0)
    atm_strike = _find_atm_strike(spot_price, interval)

    if expiry is None:
        expiry_stmt = (
            select(OptionChain.expiry)
            .where(OptionChain.underlying == symbol, OptionChain.expiry >= date.today())
            .order_by(OptionChain.expiry)
            .limit(1)
        )
        result = await db.execute(expiry_stmt)
        expiry = result.scalar_one_or_none()
        if expiry is None:
            fallback_stmt = (
                select(OptionChain.expiry)
                .where(OptionChain.underlying == symbol)
                .order_by(OptionChain.expiry.desc())
                .limit(1)
            )
            result = await db.execute(fallback_stmt)
            expiry = result.scalar_one_or_none()
            if expiry is None:
                raise HTTPException(status_code=404, detail=f"No option chain data for {symbol}")

    ce_history = await get_option_chain_oi_history(db, symbol, expiry, float(atm_strike), "CE", limit=limit)
    pe_history = await get_option_chain_oi_history(db, symbol, expiry, float(atm_strike), "PE", limit=limit)

    return {
        "symbol": symbol,
        "expiry": expiry.isoformat(),
        "atm_strike": atm_strike,
        "spot_price": spot_price,
        "ce_series": [{"time": r.timestamp.isoformat(), "oi": int(r.oi), "ltp": float(r.ltp or 0), "iv": float(r.iv or 0)} for r in ce_history],
        "pe_series": [{"time": r.timestamp.isoformat(), "oi": int(r.oi), "ltp": float(r.ltp or 0), "iv": float(r.iv or 0)} for r in pe_history],
    }
