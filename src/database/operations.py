"""CRUD operations for market data storage and retrieval.

All functions accept an AsyncSession and can be used inside
the `async with get_session()` context manager.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Sequence

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import IndexOHLC, TickData, TradeLog
from src.utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# IndexOHLC Operations
# =============================================================================


async def upsert_ohlc_candles(
    session: AsyncSession,
    candles: list[dict[str, Any]],
) -> int:
    """Insert OHLC candles, updating on conflict (upsert).

    Args:
        session: Active async session.
        candles: List of dicts with keys:
            symbol, timeframe, timestamp, open, high, low, close, volume.

    Returns:
        Number of rows upserted.
    """
    if not candles:
        return 0

    stmt = pg_insert(IndexOHLC).values(candles)
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol", "timeframe", "timestamp"],
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "volume": stmt.excluded.volume,
        },
    )
    result = await session.execute(stmt)
    count = result.rowcount  # type: ignore[union-attr]
    logger.debug("ohlc_upserted", count=count)
    return count


async def get_ohlc_candles(
    session: AsyncSession,
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    limit: int = 10000,
) -> Sequence[IndexOHLC]:
    """Fetch OHLC candles for a symbol/timeframe within a date range.

    Args:
        session: Active async session.
        symbol: Symbol string.
        timeframe: Timeframe string.
        start: Start timestamp (inclusive).
        end: End timestamp (inclusive).
        limit: Max rows to return.

    Returns:
        Sequence of IndexOHLC model instances, ordered by timestamp ASC.
    """
    stmt = (
        select(IndexOHLC)
        .where(
            IndexOHLC.symbol == symbol,
            IndexOHLC.timeframe == timeframe,
            IndexOHLC.timestamp >= start,
            IndexOHLC.timestamp <= end,
        )
        .order_by(IndexOHLC.timestamp)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_latest_ohlc_timestamp(
    session: AsyncSession,
    symbol: str,
    timeframe: str,
) -> datetime | None:
    """Get the most recent candle timestamp for a symbol/timeframe.

    Useful for resume-based data collection.

    Args:
        session: Active async session.
        symbol: Symbol string.
        timeframe: Timeframe string.

    Returns:
        Latest timestamp or None if no data exists.
    """
    stmt = (
        select(IndexOHLC.timestamp)
        .where(
            IndexOHLC.symbol == symbol,
            IndexOHLC.timeframe == timeframe,
        )
        .order_by(IndexOHLC.timestamp.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def count_ohlc_candles(
    session: AsyncSession,
    symbol: str,
    timeframe: str,
) -> int:
    """Count total candles stored for a symbol/timeframe.

    Args:
        session: Active async session.
        symbol: Symbol string.
        timeframe: Timeframe string.

    Returns:
        Number of stored candles.
    """
    from sqlalchemy import func

    stmt = (
        select(func.count())
        .select_from(IndexOHLC)
        .where(
            IndexOHLC.symbol == symbol,
            IndexOHLC.timeframe == timeframe,
        )
    )
    result = await session.execute(stmt)
    return result.scalar_one()


# =============================================================================
# TickData Operations
# =============================================================================


async def insert_ticks(
    session: AsyncSession,
    ticks: list[dict[str, Any]],
) -> int:
    """Bulk-insert tick data rows.

    Args:
        session: Active async session.
        ticks: List of dicts with keys:
            symbol, timestamp, ltp, bid, ask, volume, open, high, low, close.

    Returns:
        Number of rows inserted.
    """
    if not ticks:
        return 0

    stmt = pg_insert(TickData).values(ticks)
    # Ticks are append-only; skip conflicts silently
    stmt = stmt.on_conflict_do_nothing()
    result = await session.execute(stmt)
    count = result.rowcount  # type: ignore[union-attr]
    logger.debug("ticks_inserted", count=count)
    return count


async def get_recent_ticks(
    session: AsyncSession,
    symbol: str,
    limit: int = 100,
) -> Sequence[TickData]:
    """Fetch the most recent ticks for a symbol.

    Args:
        session: Active async session.
        symbol: Symbol string.
        limit: Max ticks to return.

    Returns:
        Sequence of TickData ordered by timestamp DESC.
    """
    stmt = (
        select(TickData)
        .where(TickData.symbol == symbol)
        .order_by(TickData.timestamp.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


# =============================================================================
# TradeLog Operations
# =============================================================================


async def insert_trade(
    session: AsyncSession,
    trade: dict[str, Any],
) -> int:
    """Insert a trade log entry.

    Args:
        session: Active async session.
        trade: Dict with keys: timestamp, symbol, side, quantity, price,
            order_type, product_type, order_id, status, strategy, notes.

    Returns:
        The auto-generated trade ID.
    """
    stmt = pg_insert(TradeLog).values(**trade).returning(TradeLog.id)
    result = await session.execute(stmt)
    trade_id: int = result.scalar_one()
    logger.info("trade_logged", trade_id=trade_id, symbol=trade.get("symbol"))
    return trade_id


async def get_trades(
    session: AsyncSession,
    symbol: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 100,
) -> Sequence[TradeLog]:
    """Fetch trade log entries with optional filters.

    Args:
        session: Active async session.
        symbol: Filter by symbol (optional).
        start: Start timestamp (optional).
        end: End timestamp (optional).
        limit: Max rows.

    Returns:
        Sequence of TradeLog ordered by timestamp DESC.
    """
    stmt = select(TradeLog).order_by(TradeLog.timestamp.desc()).limit(limit)
    if symbol:
        stmt = stmt.where(TradeLog.symbol == symbol)
    if start:
        stmt = stmt.where(TradeLog.timestamp >= start)
    if end:
        stmt = stmt.where(TradeLog.timestamp <= end)

    result = await session.execute(stmt)
    return result.scalars().all()


async def update_trade_status(
    session: AsyncSession,
    trade_id: int,
    status: str,
    pnl: Decimal | None = None,
) -> None:
    """Update the status (and optionally PnL) of a trade.

    Args:
        session: Active async session.
        trade_id: The trade log ID.
        status: New status string.
        pnl: Realized PnL (optional).
    """
    stmt = (
        select(TradeLog).where(TradeLog.id == trade_id)
    )
    result = await session.execute(stmt)
    trade = result.scalar_one_or_none()
    if trade:
        trade.status = status
        if pnl is not None:
            trade.pnl = pnl
        logger.info("trade_status_updated", trade_id=trade_id, status=status)
