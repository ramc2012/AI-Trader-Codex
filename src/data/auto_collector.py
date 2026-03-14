"""Continuous automatic data collection service.

Runs as a background asyncio task. On startup, backfills any gaps.
During market hours, refreshes intraday data every few minutes.
After market close, runs a full EOD collection once.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Optional

from src.config.constants import ALL_WATCHLIST_SYMBOLS
from src.config.market_hours import IST, is_market_open
from src.config.settings import get_settings
from src.database.connection import get_session
from src.database.operations import (
    count_ohlc_candles,
    get_latest_ohlc_timestamp,
    upsert_ohlc_candles,
)
from src.integrations.fyers_client import FyersClient
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Timeframes and their backfill horizons
COLLECTION_PLAN = {
    "D": {"days_back": 365, "refresh_minutes": 0},      # Daily: backfill 1yr, no intraday refresh
    "60": {"days_back": 60, "refresh_minutes": 5},       # Hourly: backfill 60d, refresh every 5m
    "15": {"days_back": 30, "refresh_minutes": 5},       # 15min: backfill 30d, refresh every 5m
    "3": {"days_back": 14, "refresh_minutes": 3},        # 3min: backfill 14d, refresh every 3m
    "5": {"days_back": 10, "refresh_minutes": 3},        # 5min: backfill 10d, refresh every 3m
}

# Background task handle
_collector_task: Optional[asyncio.Task] = None


async def _get_client() -> Optional[FyersClient]:
    """Get an authenticated Fyers client, auto-refreshing if needed."""
    settings = get_settings()
    client = FyersClient(
        app_id=settings.fyers_app_id,
        secret_key=settings.fyers_secret_key,
        redirect_uri=settings.fyers_redirect_uri,
    )

    if not client.is_authenticated:
        try:
            refreshed = await asyncio.to_thread(client.ensure_authenticated_with_saved_pin)
            if refreshed:
                logger.info("auto_collector_token_refreshed")
        except Exception:
            pass

    return client if client.is_authenticated else None


async def collect_symbol_data(
    client: FyersClient,
    symbol: str,
    timeframe: str,
    days_back: int,
    force: bool = False,
) -> int:
    """Collect data for one symbol/timeframe. Uses upsert so safe to re-run."""
    try:
        end_date = datetime.now(tz=IST)

        # Smart start date: resume from where we left off
        if not force:
            async with get_session() as db:
                latest = await get_latest_ohlc_timestamp(db, symbol, timeframe)
                if latest:
                    # Only fetch from last known timestamp minus small overlap
                    start_date = latest - timedelta(hours=2)
                else:
                    start_date = end_date - timedelta(days=days_back)
        else:
            start_date = end_date - timedelta(days=days_back)

        data = await asyncio.to_thread(
            client.get_history,
            symbol=symbol,
            resolution=timeframe,
            range_from=start_date.strftime("%Y-%m-%d"),
            range_to=end_date.strftime("%Y-%m-%d"),
        )

        if not data or "candles" not in data or not data["candles"]:
            return 0

        candles = []
        for c in data["candles"]:
            candles.append({
                "symbol": symbol,
                "timeframe": timeframe,
                # Store a naive UTC datetime to match existing ORM column typing.
                # This avoids asyncpg "offset-naive and offset-aware" binding errors.
                "timestamp": datetime.utcfromtimestamp(c[0]),
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": int(c[5]),
            })

        if candles:
            async with get_session() as db:
                await upsert_ohlc_candles(db, candles)
                await db.commit()

        logger.debug("collected", symbol=symbol, tf=timeframe, count=len(candles))
        return len(candles)

    except Exception as e:
        logger.error("collection_failed", symbol=symbol, tf=timeframe, error=str(e))
        return 0


async def _backfill(client: FyersClient) -> int:
    """Full backfill: fetch historical data for all symbol/timeframe combos."""
    total = 0
    for symbol in ALL_WATCHLIST_SYMBOLS:
        for tf, plan in COLLECTION_PLAN.items():
            count = await collect_symbol_data(client, symbol, tf, plan["days_back"])
            total += count
            await asyncio.sleep(0.5)  # Rate limiting
    logger.info("backfill_complete", total_candles=total)
    return total


async def _intraday_refresh(client: FyersClient) -> int:
    """Quick refresh of intraday timeframes during market hours."""
    total = 0
    for symbol in ALL_WATCHLIST_SYMBOLS:
        for tf in ["3", "5", "15", "60"]:
            count = await collect_symbol_data(client, symbol, tf, days_back=2)
            total += count
            await asyncio.sleep(0.3)
    logger.debug("intraday_refresh", total_candles=total)
    return total


async def _eod_collection(client: FyersClient) -> int:
    """End-of-day collection: update daily candles."""
    total = 0
    for symbol in ALL_WATCHLIST_SYMBOLS:
        count = await collect_symbol_data(client, symbol, "D", days_back=7)
        total += count
        await asyncio.sleep(0.3)
    logger.info("eod_collection", total_candles=total)
    return total


async def _collector_loop() -> None:
    """Main continuous collection loop."""
    logger.info("auto_collector_starting")

    client = await _get_client()
    if not client:
        logger.warning("auto_collector_not_authenticated")
        # Wait and retry auth
        while True:
            await asyncio.sleep(60)
            client = await _get_client()
            if client:
                break

    # Phase 1: Initial backfill
    logger.info("auto_collector_backfill_start")
    await _backfill(client)

    # Phase 2: Continuous loop
    eod_done_today = False
    last_refresh = datetime.now()

    while True:
        try:
            now = datetime.now(tz=IST)

            # Re-check auth periodically
            if not client.is_authenticated:
                client = await _get_client()
                if not client:
                    await asyncio.sleep(60)
                    continue

            if is_market_open():
                eod_done_today = False
                # Refresh intraday data every 5 minutes
                if (datetime.now() - last_refresh).total_seconds() >= 300:
                    await _intraday_refresh(client)
                    last_refresh = datetime.now()
                else:
                    await asyncio.sleep(30)
            else:
                # After market close: run EOD once
                if not eod_done_today and now.hour >= 15 and now.hour < 23:
                    await _eod_collection(client)
                    eod_done_today = True
                    logger.info("eod_collection_done")

                # Sleep longer outside market hours
                await asyncio.sleep(300)

        except asyncio.CancelledError:
            logger.info("auto_collector_cancelled")
            raise
        except Exception as e:
            logger.error("auto_collector_error", error=str(e))
            await asyncio.sleep(60)


async def start_auto_collection() -> None:
    """Start the continuous collection background task."""
    global _collector_task
    if _collector_task and not _collector_task.done():
        return  # Already running
    _collector_task = asyncio.create_task(_collector_loop())
    logger.info("auto_collector_task_created")


async def stop_auto_collection() -> None:
    """Stop the collection background task."""
    global _collector_task
    if _collector_task and not _collector_task.done():
        _collector_task.cancel()
        try:
            await _collector_task
        except asyncio.CancelledError:
            pass
    _collector_task = None
    logger.info("auto_collector_stopped")
