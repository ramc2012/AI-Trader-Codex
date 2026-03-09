"""CRUD operations for market data storage and retrieval.

All functions accept an AsyncSession and can be used inside
the `async with get_session()` context manager.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Sequence

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Asset, IndexOHLC, MarketSnapshot, OptionChain, OptionOHLC, TickData, TradeLog
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

    deduped: dict[tuple[str, str, datetime], dict[str, Any]] = {}
    for row in candles:
        symbol = str(row.get("symbol") or "").strip()
        timeframe = str(row.get("timeframe") or "").strip()
        timestamp = row.get("timestamp")
        if not symbol or not timeframe or not isinstance(timestamp, datetime):
            continue
        deduped[(symbol, timeframe, timestamp)] = row

    if not deduped:
        return 0
    if len(deduped) != len(candles):
        logger.debug("ohlc_upsert_deduped", input_rows=len(candles), unique_rows=len(deduped))

    stmt = pg_insert(IndexOHLC).values(list(deduped.values()))
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


async def batch_watchlist_summary(
    session: AsyncSession,
    symbols: list[str],
    timeframes: list[str],
) -> dict[str, dict[str, dict[str, Any]]]:
    """Get count + latest timestamp for ALL symbol/timeframe combos in ONE query.

    Returns: { symbol: { timeframe: { count, latest_timestamp } } }
    """
    from sqlalchemy import func

    stmt = (
        select(
            IndexOHLC.symbol,
            IndexOHLC.timeframe,
            func.count().label("cnt"),
            func.max(IndexOHLC.timestamp).label("latest"),
        )
        .where(
            IndexOHLC.symbol.in_(symbols),
            IndexOHLC.timeframe.in_(timeframes),
        )
        .group_by(IndexOHLC.symbol, IndexOHLC.timeframe)
    )
    result = await session.execute(stmt)
    rows = result.all()

    out: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        sym, tf, cnt, latest = row[0], row[1], row[2], row[3]
        out.setdefault(sym, {})[tf] = {"count": cnt, "latest_timestamp": latest}
    return out


async def batch_latest_prices(
    session: AsyncSession,
    symbols: list[str],
) -> dict[str, dict[str, float | None]]:
    """Get latest daily close + prev close for all symbols in ONE query.

    Returns: { symbol: { latest_price, prev_close } }
    """
    from sqlalchemy import func, literal_column
    from datetime import timedelta

    now = datetime.now()
    week_ago = now - timedelta(days=7)

    # Subquery: rank candles by timestamp descending per symbol
    ranked = (
        select(
            IndexOHLC.symbol,
            IndexOHLC.close,
            func.row_number()
            .over(
                partition_by=IndexOHLC.symbol,
                order_by=IndexOHLC.timestamp.desc(),
            )
            .label("rn"),
        )
        .where(
            IndexOHLC.symbol.in_(symbols),
            IndexOHLC.timeframe == "D",
            IndexOHLC.timestamp >= week_ago,
        )
        .subquery()
    )

    stmt = select(ranked.c.symbol, ranked.c.close, ranked.c.rn).where(
        ranked.c.rn <= 2
    )
    result = await session.execute(stmt)
    rows = result.all()

    out: dict[str, dict[str, float | None]] = {}
    for sym, close_val, rn in rows:
        entry = out.setdefault(sym, {"latest_price": None, "prev_close": None})
        if rn == 1:
            entry["latest_price"] = float(close_val)
        elif rn == 2:
            entry["prev_close"] = float(close_val)
    return out


# =============================================================================
# OptionChain Operations
# =============================================================================


async def upsert_option_chain_rows(
    session: AsyncSession,
    rows: list[dict[str, Any]],
) -> int:
    """Insert option chain snapshot rows.

    Snapshot rows are unique by (timestamp, underlying, expiry, strike, option_type).
    """
    if not rows:
        return 0

    stmt = pg_insert(OptionChain).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["timestamp", "underlying", "expiry", "strike", "option_type"],
        set_={
            "symbol": stmt.excluded.symbol,
            "ltp": stmt.excluded.ltp,
            "oi": stmt.excluded.oi,
            "prev_oi": stmt.excluded.prev_oi,
            "oich": stmt.excluded.oich,
            "volume": stmt.excluded.volume,
            "iv": stmt.excluded.iv,
            "delta": stmt.excluded.delta,
            "gamma": stmt.excluded.gamma,
            "theta": stmt.excluded.theta,
            "vega": stmt.excluded.vega,
            "source_ts": stmt.excluded.source_ts,
            "source_latency_ms": stmt.excluded.source_latency_ms,
            "integrity_score": stmt.excluded.integrity_score,
            "is_stale": stmt.excluded.is_stale,
            "is_partial": stmt.excluded.is_partial,
        },
    )
    result = await session.execute(stmt)
    count = result.rowcount  # type: ignore[union-attr]
    logger.debug("option_chain_upserted", count=count)
    return count


async def get_option_chain_rows_for_expiry(
    session: AsyncSession,
    underlying: str,
    expiry: date,
) -> Sequence[OptionChain]:
    """Fetch latest snapshot rows for one underlying + expiry."""
    latest_stmt = (
        select(OptionChain.timestamp)
        .where(
            OptionChain.underlying == underlying,
            OptionChain.expiry == expiry,
        )
        .order_by(OptionChain.timestamp.desc())
        .limit(1)
    )
    latest_result = await session.execute(latest_stmt)
    latest_ts = latest_result.scalar_one_or_none()
    if latest_ts is None:
        return []

    rows_stmt = (
        select(OptionChain)
        .where(
            OptionChain.underlying == underlying,
            OptionChain.expiry == expiry,
            OptionChain.timestamp == latest_ts,
        )
        .order_by(OptionChain.strike, OptionChain.option_type)
    )
    result = await session.execute(rows_stmt)
    return result.scalars().all()


async def get_option_chain_oi_history(
    session: AsyncSession,
    underlying: str,
    expiry: date,
    strike: float,
    option_type: str,
    limit: int = 500,
) -> Sequence[OptionChain]:
    """Fetch OI history points from option_chain snapshots."""
    stmt = (
        select(OptionChain)
        .where(
            OptionChain.underlying == underlying,
            OptionChain.expiry == expiry,
            OptionChain.strike == strike,
            OptionChain.option_type == option_type,
        )
        .order_by(OptionChain.timestamp.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return list(reversed(rows))


# =============================================================================
# OptionOHLC Operations
# =============================================================================


async def upsert_option_ohlc_candles(
    session: AsyncSession,
    candles: list[dict[str, Any]],
) -> int:
    """Insert option OHLC candles with upsert semantics."""
    if not candles:
        return 0

    stmt = pg_insert(OptionOHLC).values(candles)
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol", "timeframe", "timestamp"],
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "volume": stmt.excluded.volume,
            "underlying": stmt.excluded.underlying,
            "expiry": stmt.excluded.expiry,
            "strike": stmt.excluded.strike,
            "option_type": stmt.excluded.option_type,
        },
    )
    result = await session.execute(stmt)
    count = result.rowcount  # type: ignore[union-attr]
    logger.debug("option_ohlc_upserted", count=count)
    return count


async def get_option_ohlc_candles(
    session: AsyncSession,
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    limit: int = 2000,
) -> Sequence[OptionOHLC]:
    """Fetch option OHLC candles for a symbol/timeframe in range."""
    stmt = (
        select(OptionOHLC)
        .where(
            OptionOHLC.symbol == symbol,
            OptionOHLC.timeframe == timeframe,
            OptionOHLC.timestamp >= start,
            OptionOHLC.timestamp <= end,
        )
        .order_by(OptionOHLC.timestamp)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


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


# =============================================================================
# MarketSnapshot Operations
# =============================================================================


async def upsert_market_snapshots(
    session: AsyncSession,
    snapshots: list[dict[str, Any]],
) -> int:
    """Upsert market snapshot rows (keyed by symbol)."""
    if not snapshots:
        return 0

    stmt = pg_insert(MarketSnapshot).values(snapshots)
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol"],
        set_={
            "ltp": stmt.excluded.ltp,
            "prev_close": stmt.excluded.prev_close,
            "change": stmt.excluded.change,
            "change_percent": stmt.excluded.change_percent,
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "volume": stmt.excluded.volume,
            "oi": stmt.excluded.oi,
            "bid": stmt.excluded.bid,
            "ask": stmt.excluded.ask,
            "vwap": stmt.excluded.vwap,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    result = await session.execute(stmt)
    count = result.rowcount  # type: ignore[union-attr]
    logger.debug("market_snapshots_upserted", count=count)
    return count


async def get_market_snapshots(
    session: AsyncSession,
    symbols: list[str] | None = None,
) -> Sequence[MarketSnapshot]:
    """Fetch latest market snapshots, optionally filtered by symbols."""
    stmt = select(MarketSnapshot).order_by(MarketSnapshot.symbol)
    if symbols:
        stmt = stmt.where(MarketSnapshot.symbol.in_(symbols))
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_market_snapshot(
    session: AsyncSession,
    symbol: str,
) -> MarketSnapshot | None:
    """Fetch a single market snapshot by symbol."""
    stmt = select(MarketSnapshot).where(MarketSnapshot.symbol == symbol)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


# =============================================================================
# Asset Operations
# =============================================================================


async def upsert_assets(
    session: AsyncSession,
    assets: list[dict[str, Any]],
) -> int:
    """Upsert asset (instrument) registry rows."""
    if not assets:
        return 0

    stmt = pg_insert(Asset).values(assets)
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol"],
        set_={
            "name": stmt.excluded.name,
            "instrument_type": stmt.excluded.instrument_type,
            "lot_size": stmt.excluded.lot_size,
            "tick_size": stmt.excluded.tick_size,
            "strike_interval": stmt.excluded.strike_interval,
            "is_fno": stmt.excluded.is_fno,
            "sector": stmt.excluded.sector,
            "exchange": stmt.excluded.exchange,
            "is_active": stmt.excluded.is_active,
        },
    )
    result = await session.execute(stmt)
    count = result.rowcount  # type: ignore[union-attr]
    logger.debug("assets_upserted", count=count)
    return count


async def get_assets(
    session: AsyncSession,
    instrument_type: str | None = None,
    sector: str | None = None,
    is_fno: bool | None = None,
) -> Sequence[Asset]:
    """Fetch assets with optional filters."""
    stmt = select(Asset).where(Asset.is_active == True).order_by(Asset.symbol)  # noqa: E712
    if instrument_type:
        stmt = stmt.where(Asset.instrument_type == instrument_type)
    if sector:
        stmt = stmt.where(Asset.sector == sector)
    if is_fno is not None:
        stmt = stmt.where(Asset.is_fno == is_fno)  # noqa: E712
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_fno_symbols(session: AsyncSession) -> list[str]:
    """Get all FnO-eligible symbols."""
    stmt = (
        select(Asset.symbol)
        .where(Asset.is_fno == True, Asset.is_active == True)  # noqa: E712
        .order_by(Asset.symbol)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
