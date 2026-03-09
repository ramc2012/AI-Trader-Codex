"""Reusable fractal profile context loading and scan helpers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.analysis.fractal_profile import (
    DailyFractalContext,
    OptionFlowSummary,
    build_daily_fractal_context,
    normalize_timestamp,
)
from src.analysis.order_flow import OrderFlowAnalyzer
from src.api.routes.orderflow import _load_1min_candles
from src.api.routes.scanner import _INDICES, _NIFTY50_STOCKS
from src.api.routes.tpo import (
    _fetch_1min_external,
    _fetch_1min_from_fyers,
    _fetch_1min_nse_public,
    _fetch_1min_realtime,
    _market_of_symbol,
    _session_bounds,
)
from src.config.constants import ALL_WATCHLIST_SYMBOLS
from src.database.models import OptionChain
from src.database.operations import get_ohlc_candles

_CROSS_MARKET_SYMBOLS = [
    "US:SPY",
    "US:QQQ",
    "US:AAPL",
    "CRYPTO:BTCUSDT",
    "CRYPTO:ETHUSDT",
    "CRYPTO:SOLUSDT",
]

DEFAULT_SCAN_SYMBOLS = _INDICES + _NIFTY50_STOCKS + _CROSS_MARKET_SYMBOLS
DEFAULT_WATCHLIST_SYMBOLS = list(ALL_WATCHLIST_SYMBOLS) + _CROSS_MARKET_SYMBOLS


@dataclass(frozen=True)
class FractalContextSnapshot:
    context: DailyFractalContext
    source_timeframe: Optional[str]
    prev_source_timeframe: Optional[str]

    @property
    def symbol(self) -> str:
        return self.context.symbol

    def to_dict(self) -> dict[str, Any]:
        payload = self.context.to_dict()
        payload["source_timeframe"] = self.source_timeframe
        payload["prev_source_timeframe"] = self.prev_source_timeframe
        return payload


def parse_session_date(date_str: Optional[str]) -> datetime:
    if date_str:
        return datetime.strptime(date_str, "%Y-%m-%d")
    return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)


def symbols_from_query(raw_symbols: Optional[str], default_symbols: list[str]) -> list[str]:
    if not raw_symbols:
        return list(default_symbols)

    out: list[str] = []
    seen: set[str] = set()
    for symbol in raw_symbols.split(","):
        token = symbol.strip()
        if not token or token in seen:
            continue
        out.append(token)
        seen.add(token)
    return out


def display_symbol(symbol: str) -> str:
    token = str(symbol or "").strip()
    if ":" in token:
        token = token.split(":", 1)[1]
    return token.replace("-EQ", "").replace("-INDEX", "")


def _row_timestamp(row: Any) -> Any:
    if isinstance(row, dict):
        return row.get("timestamp")
    return getattr(row, "timestamp")


def row_close(row: Any) -> float:
    if isinstance(row, dict):
        return float(row.get("close", 0.0) or 0.0)
    return float(getattr(row, "close", 0.0) or 0.0)


async def _load_exact_session_candles(
    db: AsyncSession,
    symbol: str,
    session_date: datetime,
    market: str,
) -> tuple[list[Any], Optional[str]]:
    start, end = _session_bounds(session_date, market)
    for timeframe in ("1", "3", "5", "15", "60"):
        rows = list(await get_ohlc_candles(db, symbol, timeframe, start, end, limit=5000))
        if rows:
            return rows, timeframe

    if market == "NSE":
        realtime_rows = _fetch_1min_realtime(symbol, session_date)
        if realtime_rows:
            return realtime_rows, "1"
        fyers_rows = await _fetch_1min_from_fyers(symbol, session_date.strftime("%Y-%m-%d"))
        if fyers_rows:
            return fyers_rows, "1"
        public_rows = await _fetch_1min_nse_public(symbol, session_date)
        if public_rows:
            return public_rows, "1"
        return [], None

    external_rows = await _fetch_1min_external(symbol, session_date)
    if external_rows:
        return external_rows, "1"
    return [], None


async def _find_nearest_session(
    db: AsyncSession,
    symbol: str,
    market: str,
    start_date: datetime,
    max_lookback_days: int = 7,
) -> tuple[list[Any], datetime, Optional[str]]:
    for offset in range(max_lookback_days + 1):
        candidate_date = start_date - timedelta(days=offset)
        rows, source_tf = await _load_exact_session_candles(
            db=db,
            symbol=symbol,
            session_date=candidate_date,
            market=market,
        )
        if rows:
            normalized_day = normalize_timestamp(_row_timestamp(rows[0]), market).date()
            return rows, datetime.combine(normalized_day, datetime.min.time()), source_tf
    return [], start_date, None


async def _fetch_orderflow_summary(db: AsyncSession, symbol: str) -> dict[str, Any]:
    candles = await _load_1min_candles(db, symbol, 6)
    if not candles:
        return {}
    analyzer = OrderFlowAnalyzer(tick_size=0.05 if _market_of_symbol(symbol) == "NSE" else 0.01)
    footprints = analyzer.build_footprints(candles, bar_minutes=15)
    return analyzer.summarize(footprints)


async def _fetch_option_flow_summary(
    db: AsyncSession,
    symbol: str,
    spot_price: float,
    direction: str,
) -> Optional[OptionFlowSummary]:
    latest_stmt = (
        select(OptionChain.timestamp)
        .where(OptionChain.underlying == symbol)
        .order_by(OptionChain.timestamp.desc())
        .limit(1)
    )
    latest_result = await db.execute(latest_stmt)
    latest_ts = latest_result.scalar_one_or_none()
    if latest_ts is None:
        return None

    expiry_stmt = (
        select(OptionChain.expiry)
        .where(OptionChain.underlying == symbol, OptionChain.timestamp == latest_ts)
        .order_by(OptionChain.expiry)
        .limit(1)
    )
    expiry_result = await db.execute(expiry_stmt)
    nearest_expiry = expiry_result.scalar_one_or_none()
    if nearest_expiry is None:
        return None

    rows_stmt = (
        select(OptionChain)
        .where(
            OptionChain.underlying == symbol,
            OptionChain.timestamp == latest_ts,
            OptionChain.expiry == nearest_expiry,
        )
        .order_by(OptionChain.strike, OptionChain.option_type)
    )
    rows_result = await db.execute(rows_stmt)
    rows = list(rows_result.scalars().all())
    if not rows:
        return None

    strikes = sorted({float(row.strike) for row in rows})
    if not strikes:
        return None
    near_strikes = set(sorted(strikes, key=lambda strike: abs(strike - spot_price))[:5])
    filtered = [row for row in rows if float(row.strike) in near_strikes]
    if not filtered:
        filtered = rows

    call_rows = [row for row in filtered if str(row.option_type).upper() == "CE"]
    put_rows = [row for row in filtered if str(row.option_type).upper() == "PE"]
    call_oi_change = sum(float(row.oich or 0) for row in call_rows)
    put_oi_change = sum(float(row.oich or 0) for row in put_rows)
    call_ivs = [float(row.iv or 0) for row in call_rows if float(row.iv or 0) > 0]
    put_ivs = [float(row.iv or 0) for row in put_rows if float(row.iv or 0) > 0]
    avg_call_iv = sum(call_ivs) / len(call_ivs) if call_ivs else 0.0
    avg_put_iv = sum(put_ivs) / len(put_ivs) if put_ivs else 0.0

    if call_oi_change > put_oi_change * 1.05:
        dominant = "CE"
    elif put_oi_change > call_oi_change * 1.05:
        dominant = "PE"
    else:
        dominant = "neutral"

    supportive = (direction == "bullish" and dominant == "CE") or (
        direction == "bearish" and dominant == "PE"
    )

    target_rows = call_rows if direction == "bullish" else put_rows
    if target_rows:
        target_rows.sort(
            key=lambda row: (
                abs(float(row.strike) - spot_price),
                abs(abs(float(row.delta or 0.35)) - 0.35),
            )
        )
        best = target_rows[0]
        contract = best.symbol or f"{display_symbol(symbol)} {float(best.strike):.0f} {best.option_type}"
        suggested_delta = float(best.delta) if best.delta is not None else 0.35
    else:
        contract = None
        suggested_delta = None

    return OptionFlowSummary(
        snapshot_time=latest_ts.isoformat() if hasattr(latest_ts, "isoformat") else str(latest_ts),
        nearest_expiry=nearest_expiry.isoformat()
        if hasattr(nearest_expiry, "isoformat")
        else str(nearest_expiry),
        dominant_side=dominant,
        call_oi_change=call_oi_change,
        put_oi_change=put_oi_change,
        avg_call_iv=avg_call_iv,
        avg_put_iv=avg_put_iv,
        supportive=supportive,
        suggested_contract=contract,
        suggested_delta=suggested_delta,
    )


async def build_context_snapshot(
    db: AsyncSession,
    symbol: str,
    session_date: datetime,
) -> Optional[FractalContextSnapshot]:
    market = _market_of_symbol(symbol)
    current_rows, resolved_date, current_source_tf = await _find_nearest_session(
        db=db,
        symbol=symbol,
        market=market,
        start_date=session_date,
        max_lookback_days=7,
    )
    if not current_rows:
        return None

    prev_rows, _, prev_source_tf = await _find_nearest_session(
        db=db,
        symbol=symbol,
        market=market,
        start_date=resolved_date - timedelta(days=1),
        max_lookback_days=10,
    )

    orderflow_summary = await _fetch_orderflow_summary(db, symbol)
    option_flow: Optional[OptionFlowSummary] = None

    initial_context = build_daily_fractal_context(
        symbol=symbol,
        market=market,
        session_date=resolved_date,
        current_day_candles=current_rows,
        prev_day_candles=prev_rows,
        orderflow_summary=orderflow_summary,
        option_flow=None,
    )
    if initial_context is None:
        return None

    if initial_context.candidate is not None:
        option_flow = await _fetch_option_flow_summary(
            db=db,
            symbol=symbol,
            spot_price=row_close(current_rows[-1]),
            direction=initial_context.candidate.direction,
        )

    context = build_daily_fractal_context(
        symbol=symbol,
        market=market,
        session_date=resolved_date,
        current_day_candles=current_rows,
        prev_day_candles=prev_rows,
        orderflow_summary=orderflow_summary,
        option_flow=option_flow,
    )
    if context is None:
        return None

    return FractalContextSnapshot(
        context=context,
        source_timeframe=current_source_tf,
        prev_source_timeframe=prev_source_tf,
    )


async def load_context_snapshots(
    session_factory: async_sessionmaker[AsyncSession],
    symbols: list[str],
    session_date: datetime,
    concurrency: int = 8,
) -> list[FractalContextSnapshot]:
    semaphore = asyncio.Semaphore(max(concurrency, 1))

    async def evaluate(symbol: str) -> Optional[FractalContextSnapshot]:
        async with semaphore:
            async with session_factory() as session:
                return await build_context_snapshot(
                    db=session,
                    symbol=symbol,
                    session_date=session_date,
                )

    snapshots = await asyncio.gather(*(evaluate(symbol) for symbol in symbols))
    return [snapshot for snapshot in snapshots if snapshot is not None]


def evaluate_snapshot(
    snapshot: FractalContextSnapshot,
    min_consecutive_hours: int,
) -> dict[str, Any]:
    context = snapshot.context
    current_hour = context.hourly_profiles[-1] if context.hourly_profiles else None
    candidate = context.candidate
    if current_hour is None:
        return {
            "context": context,
            "snapshot": snapshot,
            "shape_pass": False,
            "migration_pass": False,
            "daily_pass": False,
            "orderflow_pass": False,
        }

    shape_pass = current_hour.shape in {"elongated_up", "elongated_down"}
    migration_pass = shape_pass and current_hour.consecutive_direction_hours >= min_consecutive_hours
    daily_pass = migration_pass and candidate is not None and candidate.daily_alignment
    orderflow_pass = daily_pass and candidate is not None and candidate.aggressive_flow_detected
    return {
        "context": context,
        "snapshot": snapshot,
        "shape_pass": shape_pass,
        "migration_pass": migration_pass,
        "daily_pass": daily_pass,
        "orderflow_pass": orderflow_pass,
    }


def build_scan_payload(
    symbols: list[str],
    snapshots: list[FractalContextSnapshot],
    session_date: datetime,
    min_consecutive_hours: int,
    limit: int,
) -> dict[str, Any]:
    evaluations = [evaluate_snapshot(snapshot, min_consecutive_hours) for snapshot in snapshots]
    shape_pass = [row for row in evaluations if row["shape_pass"]]
    migration_pass = [row for row in shape_pass if row["migration_pass"]]
    daily_pass = [row for row in migration_pass if row["daily_pass"]]
    orderflow_pass = [row for row in daily_pass if row["orderflow_pass"]]

    candidates = [
        row["context"].candidate.to_dict()
        for row in orderflow_pass
        if row["context"].candidate is not None
    ]
    candidates.sort(
        key=lambda item: (
            -int(item.get("conviction", 0)),
            -int(item.get("consecutive_migration_hours", 0)),
            str(item.get("symbol", "")),
        )
    )

    return {
        "date": session_date.strftime("%Y-%m-%d"),
        "total_symbols": len(symbols),
        "stages": {
            "input": len(symbols),
            "profile_built": len(evaluations),
            "shape_pass": len(shape_pass),
            "migration_pass": len(migration_pass),
            "daily_pass": len(daily_pass),
            "orderflow_pass": len(orderflow_pass),
            "final": min(len(candidates), limit),
        },
        "candidates": candidates[:limit],
        "generated_at": datetime.utcnow().isoformat(),
    }
