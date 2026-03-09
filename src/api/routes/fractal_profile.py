"""Fractal Market Profile API routes."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.analysis.fractal_scan import (
    DEFAULT_SCAN_SYMBOLS,
    DEFAULT_WATCHLIST_SYMBOLS,
    build_context_snapshot,
    build_scan_payload,
    load_context_snapshots,
    parse_session_date,
    symbols_from_query,
)
from src.api.dependencies import get_db
from src.api.routes.tpo import _market_of_symbol
from src.config.settings import get_settings
from src.database.connection import get_session_factory
from src.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/fractal", tags=["Fractal Profile"])

_CONTEXT_CACHE_TTL = timedelta(seconds=45)
_SCAN_CACHE_TTL = timedelta(seconds=45)
_WATCHLIST_CACHE_TTL = timedelta(seconds=30)
_CONTEXT_CACHE: dict[tuple[str, str], tuple[datetime, dict[str, Any]]] = {}
_SCAN_CACHE: dict[tuple[str, str, int, int], tuple[datetime, dict[str, Any]]] = {}
_WATCHLIST_CACHE: dict[tuple[str, str, int, int], tuple[datetime, dict[str, Any]]] = {}
_SCAN_REDIS_CHANNEL = "scanner:fractal_profile"


def _cache_get(
    cache: dict[tuple[Any, ...], tuple[datetime, dict[str, Any]]],
    key: tuple[Any, ...],
    ttl: timedelta,
) -> Optional[dict[str, Any]]:
    entry = cache.get(key)
    if entry is None:
        return None
    created_at, payload = entry
    if datetime.utcnow() - created_at > ttl:
        cache.pop(key, None)
        return None
    return payload


def _cache_set(
    cache: dict[tuple[Any, ...], tuple[datetime, dict[str, Any]]],
    key: tuple[Any, ...],
    payload: dict[str, Any],
) -> None:
    cache[key] = (datetime.utcnow(), payload)


async def _publish_scan(payload: dict[str, Any]) -> bool:
    try:
        import redis.asyncio as redis

        client = redis.from_url(get_settings().redis_url, decode_responses=True)
        try:
            await client.publish(_SCAN_REDIS_CHANNEL, json.dumps(payload))
        finally:
            await client.aclose()
        return True
    except Exception as exc:
        logger.warning("fractal_scan_publish_failed", error=str(exc))
        return False


@router.get("/context/{symbol:path}")
async def get_fractal_context(
    symbol: str,
    date: Optional[str] = Query(None, description="Session date YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    session_date = parse_session_date(date)
    cache_key = (symbol, session_date.strftime("%Y-%m-%d"))
    cached = _cache_get(_CONTEXT_CACHE, cache_key, _CONTEXT_CACHE_TTL)
    if cached is not None:
        return cached

    snapshot = await build_context_snapshot(db=db, symbol=symbol, session_date=session_date)
    if snapshot is None:
        payload = {
            "symbol": symbol,
            "market": _market_of_symbol(symbol),
            "session_date": session_date.strftime("%Y-%m-%d"),
            "daily_profile": None,
            "prev_day_profile": None,
            "hourly_profiles": [],
            "candidate": None,
            "source_timeframe": None,
            "prev_source_timeframe": None,
            "error": "No intraday data available for fractal profile context",
        }
        _cache_set(_CONTEXT_CACHE, cache_key, payload)
        return payload

    payload = snapshot.to_dict()
    _cache_set(_CONTEXT_CACHE, cache_key, payload)
    return payload


@router.get("/scan")
async def run_fractal_scan(
    symbols: Optional[str] = Query(None, description="Comma-separated symbol list"),
    date: Optional[str] = Query(None, description="Session date YYYY-MM-DD"),
    min_consecutive_hours: int = Query(2, ge=1, le=6),
    limit: int = Query(8, ge=1, le=30),
    publish: bool = Query(False, description="Publish resulting payload to Redis"),
) -> dict[str, Any]:
    universe = symbols_from_query(symbols, DEFAULT_SCAN_SYMBOLS)
    session_date = parse_session_date(date)
    cache_key = (
        ",".join(universe),
        session_date.strftime("%Y-%m-%d"),
        min_consecutive_hours,
        limit,
    )
    cached = _cache_get(_SCAN_CACHE, cache_key, _SCAN_CACHE_TTL)
    if cached is not None and not publish:
        return cached

    snapshots = await load_context_snapshots(
        session_factory=get_session_factory(),
        symbols=universe,
        session_date=session_date,
        concurrency=8,
    )
    payload = build_scan_payload(
        symbols=universe,
        snapshots=snapshots,
        session_date=session_date,
        min_consecutive_hours=min_consecutive_hours,
        limit=limit,
    )
    payload["published"] = False
    payload["channel"] = None

    if publish:
        payload["published"] = await _publish_scan(payload)
        payload["channel"] = _SCAN_REDIS_CHANNEL if payload["published"] else None

    _cache_set(_SCAN_CACHE, cache_key, payload)
    return payload


@router.get("/watchlist")
async def get_fractal_watchlist(
    symbols: Optional[str] = Query(None, description="Comma-separated watchlist symbol list"),
    date: Optional[str] = Query(None, description="Session date YYYY-MM-DD"),
    min_consecutive_hours: int = Query(2, ge=1, le=6),
    limit: int = Query(5, ge=1, le=20),
) -> dict[str, Any]:
    universe = symbols_from_query(symbols, DEFAULT_WATCHLIST_SYMBOLS)
    session_date = parse_session_date(date)
    cache_key = (
        ",".join(universe),
        session_date.strftime("%Y-%m-%d"),
        min_consecutive_hours,
        limit,
    )
    cached = _cache_get(_WATCHLIST_CACHE, cache_key, _WATCHLIST_CACHE_TTL)
    if cached is not None:
        return cached

    snapshots = await load_context_snapshots(
        session_factory=get_session_factory(),
        symbols=universe,
        session_date=session_date,
        concurrency=min(6, max(len(universe), 1)),
    )
    scan_payload = build_scan_payload(
        symbols=universe,
        snapshots=snapshots,
        session_date=session_date,
        min_consecutive_hours=min_consecutive_hours,
        limit=limit,
    )
    payload = {
        "date": session_date.strftime("%Y-%m-%d"),
        "symbols": universe,
        "contexts": [snapshot.to_dict() for snapshot in snapshots],
        "scan": scan_payload,
        "generated_at": scan_payload["generated_at"],
    }
    _cache_set(_WATCHLIST_CACHE, cache_key, payload)
    return payload

