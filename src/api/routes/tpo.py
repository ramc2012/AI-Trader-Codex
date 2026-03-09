"""Market Profile (TPO) API routes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.analysis.tpo_engine import compute_tpo_profile, profile_to_dict
from src.api.dependencies import get_db, get_fyers_client, get_tick_aggregator
from src.config.market_hours import IST
from src.database.operations import get_latest_ohlc_timestamp, get_ohlc_candles
from src.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/tpo", tags=["tpo"])

# IST = UTC + 5:30.  Used to shift Fyers UTC-epoch timestamps so that
# c.timestamp.hour / .minute land in the [9, 15] range expected by the
# TPO period maths (9:15 IST = minute 555 from midnight IST).
_IST_OFFSET = timedelta(hours=5, minutes=30)
_CACHE_TTL = timedelta(seconds=30)
_single_tpo_cache: dict[tuple[str, str, float | None], tuple[datetime, dict[str, Any]]] = {}
_multi_tpo_cache: dict[tuple[str, int, float | None], tuple[datetime, dict[str, Any]]] = {}


@dataclass
class _CandleRow:
    """Lightweight candle object for Fyers API fallback data.

    Mirrors the ORM attributes accessed by ``compute_tpo_profile`` so that
    duck-typing passes without modifying the engine.

    Timestamps are stored as IST-naive datetimes so the TPO period
    calculation (``hour * 60 + minute - 555``) is correct.
    """

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


async def _fetch_1min_from_fyers(symbol: str, date_str: str) -> list[_CandleRow]:
    """Fetch 1-min OHLC candles from Fyers for a single calendar date.

    Returns a list of :class:`_CandleRow` objects with **IST-naive** timestamps
    suitable for the TPO engine.  Returns an empty list when Fyers is not
    authenticated or the API call fails.
    """
    try:
        fyers = get_fyers_client()
        if not fyers.is_authenticated:
            logger.warning("fyers_not_authenticated_tpo", symbol=symbol)
            return []

        raw = await asyncio.to_thread(
            lambda: fyers.get_history(
                symbol=symbol,
                resolution="1",
                range_from=date_str,
                range_to=date_str,
            )
        )

        if not raw or "candles" not in raw or not raw["candles"]:
            logger.warning("fyers_1min_empty", symbol=symbol, date=date_str)
            return []

        rows: list[_CandleRow] = []
        for row in raw["candles"]:
            # Fyers returns UTC epoch seconds; add IST offset so that
            # timestamp.hour/minute are in IST for TPO period maths.
            ts_ist = datetime.utcfromtimestamp(row[0]) + _IST_OFFSET
            rows.append(
                _CandleRow(
                    timestamp=ts_ist,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=int(row[5]),
                )
            )

        logger.info("fyers_1min_fetched", symbol=symbol, date=date_str, rows=len(rows))
        return rows

    except Exception as exc:
        logger.warning("fyers_1min_fetch_failed", symbol=symbol, error=str(exc))
        return []


def _cache_get(
    cache: dict[tuple[Any, ...], tuple[datetime, dict[str, Any]]],
    key: tuple[Any, ...],
) -> dict[str, Any] | None:
    entry = cache.get(key)
    if entry is None:
        return None
    created_at, payload = entry
    if datetime.utcnow() - created_at > _CACHE_TTL:
        cache.pop(key, None)
        return None
    return payload


def _cache_set(
    cache: dict[tuple[Any, ...], tuple[datetime, dict[str, Any]]],
    key: tuple[Any, ...],
    payload: dict[str, Any],
) -> None:
    cache[key] = (datetime.utcnow(), payload)


def _market_of_symbol(symbol: str) -> str:
    token = str(symbol or "").upper()
    if token.startswith("CRYPTO:"):
        return "CRYPTO"
    if token.startswith(("US:", "NASDAQ:", "NYSE:", "AMEX:")):
        return "US"
    return "NSE"


def _session_bounds(session_date: datetime, market: str) -> tuple[datetime, datetime]:
    """Return start/end bounds for DB lookup for a symbol's market session."""
    if market == "NSE":
        # 9:15 IST to 15:30 IST as UTC-naive storage window.
        return (
            session_date.replace(hour=3, minute=45),
            session_date.replace(hour=10, minute=0),
        )
    # US + crypto use full-day window for robust profile availability.
    return (
        session_date.replace(hour=0, minute=0, second=0, microsecond=0),
        session_date.replace(hour=23, minute=59, second=59, microsecond=999999),
    )


async def _fetch_1min_external(
    symbol: str,
    session_date: datetime,
) -> list[_CandleRow]:
    """Fetch 1-minute candles from public providers for US/crypto symbols."""
    market = _market_of_symbol(symbol)
    if market not in {"US", "CRYPTO"}:
        return []

    try:
        # Reuse existing provider adapters from market_data routes.
        from src.api.routes.market_data import _fetch_crypto_ohlc, _fetch_us_ohlc

        candles = (
            await _fetch_us_ohlc(symbol, "1", 1440)
            if market == "US"
            else await _fetch_crypto_ohlc(symbol, "1", 1440)
        )
    except Exception as exc:
        logger.warning("external_1min_fetch_failed", symbol=symbol, error=str(exc))
        return []

    if not candles:
        return []

    target_day = session_date.date()
    rows: list[_CandleRow] = []
    for c in candles:
        ts = c.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        ts_ist = ts.astimezone(IST)
        if ts_ist.date() != target_day:
            continue
        rows.append(
            _CandleRow(
                timestamp=ts_ist.replace(tzinfo=None),
                open=float(c.open),
                high=float(c.high),
                low=float(c.low),
                close=float(c.close),
                volume=int(c.volume or 0),
            )
        )

    if rows:
        return rows

    # Off-session fallback: return latest block so MP still renders instantly.
    fallback_rows: list[_CandleRow] = []
    for c in candles[-390:]:
        ts = c.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        ts_ist = ts.astimezone(IST).replace(tzinfo=None)
        fallback_rows.append(
            _CandleRow(
                timestamp=ts_ist,
                open=float(c.open),
                high=float(c.high),
                low=float(c.low),
                close=float(c.close),
                volume=int(c.volume or 0),
            )
        )
    return fallback_rows


def _fetch_1min_realtime(
    symbol: str,
    session_date: datetime,
) -> list[_CandleRow]:
    """Derive 1-minute candles from in-memory real-time aggregator history."""
    try:
        agg = get_tick_aggregator()
        bars = agg.get_history(symbol, 1, count=1600)
    except Exception:
        return []

    if not bars:
        return []

    target_day = session_date.date()
    rows: list[_CandleRow] = []
    for bar in bars:
        ts_raw = bar.get("open_time") or bar.get("close_time")
        if not ts_raw:
            continue
        try:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=IST)
        ts_ist = ts.astimezone(IST)
        if ts_ist.date() != target_day:
            continue
        open_px = bar.get("open")
        high_px = bar.get("high")
        low_px = bar.get("low")
        close_px = bar.get("close")
        if open_px is None or high_px is None or low_px is None or close_px is None:
            continue
        rows.append(
            _CandleRow(
                timestamp=ts_ist.replace(tzinfo=None),
                open=float(open_px),
                high=float(high_px),
                low=float(low_px),
                close=float(close_px),
                volume=max(int(float(bar.get("volume", 0))), 1),
            )
        )
    if rows:
        return rows

    # If date-matched rows are unavailable, keep latest bars for immediate render.
    fallback: list[_CandleRow] = []
    for bar in bars[-390:]:
        ts_raw = bar.get("open_time") or bar.get("close_time")
        if not ts_raw:
            continue
        try:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=IST)
        ts_ist = ts.astimezone(IST)
        open_px = bar.get("open")
        high_px = bar.get("high")
        low_px = bar.get("low")
        close_px = bar.get("close")
        if open_px is None or high_px is None or low_px is None or close_px is None:
            continue
        fallback.append(
            _CandleRow(
                timestamp=ts_ist.replace(tzinfo=None),
                open=float(open_px),
                high=float(high_px),
                low=float(low_px),
                close=float(close_px),
                volume=max(int(float(bar.get("volume", 0))), 1),
            )
        )
    return fallback


async def _fetch_1min_nse_public(
    symbol: str,
    session_date: datetime,
) -> list[_CandleRow]:
    """Fallback for NSE/BSE indices via Yahoo chart symbols."""
    try:
        from src.api.routes.orderflow import _fetch_1min_from_yahoo
    except Exception:
        return []

    start_utc = session_date.replace(hour=0, minute=0, second=0, microsecond=0) - _IST_OFFSET
    end_utc = session_date.replace(hour=23, minute=59, second=59, microsecond=0) - _IST_OFFSET
    raw_rows = await _fetch_1min_from_yahoo(symbol, start_utc, end_utc)
    if not raw_rows:
        return []

    target_day = session_date.date()
    rows: list[_CandleRow] = []
    for r in raw_rows:
        ts = r.timestamp
        ts_ist = ts + _IST_OFFSET if ts.tzinfo is None else ts.astimezone(IST).replace(tzinfo=None)
        if ts_ist.date() != target_day:
            continue
        rows.append(
            _CandleRow(
                timestamp=ts_ist,
                open=float(r.open),
                high=float(r.high),
                low=float(r.low),
                close=float(r.close),
                volume=int(r.volume or 0),
            )
        )
    return rows


async def _load_session_candles(
    db: AsyncSession,
    symbol: str,
    session_date: datetime,
    market: str,
) -> tuple[list[Any], str | None]:
    """Load best available intraday candles for one session from local DB.

    Preference order is 1m -> 3m -> 5m -> 15m -> 60m.
    If session window is empty (off-market), shifts to latest available block.
    """
    start, end = _session_bounds(session_date, market)
    tf_order = ("1", "3", "5", "15", "60")

    for timeframe in tf_order:
        rows = list(await get_ohlc_candles(db, symbol, timeframe, start, end, limit=5000))
        if rows:
            return rows, timeframe

    session_span = end - start
    for timeframe in tf_order:
        latest_ts = await get_latest_ohlc_timestamp(db, symbol, timeframe)
        if latest_ts is None:
            continue
        shifted_end = latest_ts
        shifted_start = shifted_end - session_span
        rows = list(
            await get_ohlc_candles(
                db,
                symbol,
                timeframe,
                shifted_start,
                shifted_end,
                limit=5000,
            )
        )
        if rows:
            return rows, timeframe

    return [], None


@router.get("/profile/{symbol}")
async def get_tpo_profile(
    symbol: str,
    date: str | None = Query(None, description="Session date YYYY-MM-DD (defaults to today)"),
    tick_size: float | None = Query(None, description="Price bracket size (auto if omitted)"),
    db: AsyncSession = Depends(get_db),
):
    """Compute TPO Market Profile for a single session.

    Fetches 1-minute candles for the given date and builds the profile.
    Falls back to live Fyers API data when the local DB is empty.
    """
    market = _market_of_symbol(symbol)
    if date:
        session_date = datetime.strptime(date, "%Y-%m-%d")
    else:
        session_date = datetime.now(tz=IST).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)

    cache_key = (symbol, session_date.strftime("%Y-%m-%d"), tick_size)
    cached = _cache_get(_single_tpo_cache, cache_key)
    if cached is not None:
        return cached

    source_timeframe: str | None = None
    try:
        raw_candles, source_timeframe = await _load_session_candles(
            db=db,
            symbol=symbol,
            session_date=session_date,
            market=market,
        )
    except Exception as exc:
        logger.warning("tpo_db_unavailable_fallback", symbol=symbol, error=str(exc))
        raw_candles = []

    if not raw_candles:
        date_str = session_date.strftime("%Y-%m-%d")
        if market == "NSE":
            raw_candles = _fetch_1min_realtime(symbol, session_date)  # type: ignore[assignment]
            if not raw_candles:
                raw_candles = await _fetch_1min_from_fyers(symbol, date_str)  # type: ignore[assignment]
            if not raw_candles:
                raw_candles = await _fetch_1min_nse_public(symbol, session_date)  # type: ignore[assignment]
            if raw_candles:
                source_timeframe = source_timeframe or "1"
        else:
            raw_candles = await _fetch_1min_external(symbol, session_date)  # type: ignore[assignment]
            if raw_candles:
                source_timeframe = source_timeframe or "1"

    if not raw_candles:
        payload = {"error": "No intraday data available", "symbol": symbol, "date": date, "market": market}
        _cache_set(_single_tpo_cache, cache_key, payload)
        return payload

    profile = compute_tpo_profile(raw_candles, tick_size=tick_size)
    if not profile:
        payload = {"error": "Insufficient data for profile", "symbol": symbol, "market": market}
        _cache_set(_single_tpo_cache, cache_key, payload)
        return payload

    payload = profile_to_dict(profile)
    if source_timeframe is not None:
        payload["source_timeframe"] = source_timeframe
    _cache_set(_single_tpo_cache, cache_key, payload)
    return payload


@router.get("/multi/{symbol}")
async def get_multi_day_tpo(
    symbol: str,
    days: int = Query(5, ge=1, le=30),
    tick_size: float | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Compute TPO profiles for multiple days.

    Returns an array of daily profiles for overlay comparison.
    Falls back to live Fyers API data when the local DB is empty.
    """
    cache_key = (symbol, days, tick_size)
    cached = _cache_get(_multi_tpo_cache, cache_key)
    if cached is not None:
        return cached

    profiles = []
    market = _market_of_symbol(symbol)
    today = datetime.now(tz=IST).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)

    day_offset = 0
    max_scan_days = max(days * 4, days + 5)
    while len(profiles) < days and day_offset < max_scan_days:
        session_date = today - timedelta(days=day_offset)
        day_offset += 1

        if market == "NSE" and session_date.weekday() >= 5:
            # Skip Saturday/Sunday quickly to keep MP tab fast.
            continue

        source_timeframe: str | None = None
        try:
            raw_candles, source_timeframe = await _load_session_candles(
                db=db,
                symbol=symbol,
                session_date=session_date,
                market=market,
            )
        except Exception as exc:
            logger.warning("tpo_db_unavailable_fallback", symbol=symbol, error=str(exc))
            raw_candles = []

        if not raw_candles:
            date_str = session_date.strftime("%Y-%m-%d")
            if market == "NSE":
                raw_candles = _fetch_1min_realtime(symbol, session_date)  # type: ignore[assignment]
                if not raw_candles:
                    raw_candles = await _fetch_1min_from_fyers(symbol, date_str)  # type: ignore[assignment]
                if not raw_candles:
                    raw_candles = await _fetch_1min_nse_public(symbol, session_date)  # type: ignore[assignment]
                if raw_candles:
                    source_timeframe = source_timeframe or "1"
            else:
                raw_candles = await _fetch_1min_external(symbol, session_date)  # type: ignore[assignment]
                if raw_candles:
                    source_timeframe = source_timeframe or "1"

        if not raw_candles:
            continue

        profile = compute_tpo_profile(raw_candles, tick_size=tick_size)
        if profile:
            profile_payload = profile_to_dict(profile)
            if source_timeframe is not None:
                profile_payload["source_timeframe"] = source_timeframe
            profiles.append(profile_payload)

    payload = {"symbol": symbol, "profiles": profiles}
    _cache_set(_multi_tpo_cache, cache_key, payload)
    return payload
