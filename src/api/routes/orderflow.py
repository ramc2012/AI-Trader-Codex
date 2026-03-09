"""Order flow analysis API routes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.analysis.order_flow import OrderFlowAnalyzer
from src.api.dependencies import get_db, get_fyers_client, get_ohlc_cache, get_tick_aggregator
from src.database.operations import get_latest_ohlc_timestamp, get_ohlc_candles
from src.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/orderflow", tags=["orderflow"])

_FAST_CACHE_TTL = timedelta(seconds=8)
_footprint_cache: dict[tuple[str, int, int, float], tuple[datetime, dict[str, Any]]] = {}
_cvd_cache: dict[tuple[str, int, float], tuple[datetime, dict[str, Any]]] = {}
_YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://finance.yahoo.com/",
}
_NSE_YAHOO_MAP = {
    "NSE:NIFTY50-INDEX": "^NSEI",
    "NSE:NIFTYBANK-INDEX": "^NSEBANK",
    "NSE:FINNIFTY-INDEX": "NIFTY_FIN_SERVICE.NS",
    "NSE:NIFTYMIDCAP50-INDEX": "NIFTY_MIDCAP_50.NS",
    "BSE:SENSEX-INDEX": "^BSESN",
}


@dataclass
class _CandleRow:
    """Fallback candle shape for Fyers responses."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


def _symbol_market(symbol: str) -> str:
    token = str(symbol or "").strip().upper()
    if token.startswith("CRYPTO:"):
        return "CRYPTO"
    if token.startswith(("US:", "NASDAQ:", "NYSE:", "AMEX:")):
        return "US"
    return "NSE"


def _normalize_us_ticker(symbol: str) -> str:
    return str(symbol or "").split(":")[-1].strip().upper()


def _normalize_yahoo_ticker(symbol: str) -> str:
    token = str(symbol or "").strip().upper()
    if token in _NSE_YAHOO_MAP:
        return _NSE_YAHOO_MAP[token]
    if token.startswith("NSE:") and token.endswith("-EQ"):
        return f"{token.split(':', 1)[1].replace('-EQ', '')}.NS"
    if token.startswith("BSE:") and token.endswith("-EQ"):
        return f"{token.split(':', 1)[1].replace('-EQ', '')}.BO"
    return _normalize_us_ticker(symbol)


def _normalize_crypto_pair(symbol: str) -> str:
    pair = str(symbol or "").split(":")[-1].strip().upper().replace("/", "").replace("-", "")
    if pair.endswith("USD") and not pair.endswith("USDT"):
        pair = f"{pair}T"
    if pair.isalpha() and len(pair) <= 6:
        pair = f"{pair}USDT"
    return pair


async def _fetch_1min_from_fyers(
    symbol: str,
    start: datetime,
    end: datetime,
) -> list[_CandleRow]:
    """Fetch 1-minute candles from Fyers when local DB has no data."""
    try:
        fyers = get_fyers_client()
        if not fyers.is_authenticated:
            logger.warning("fyers_not_authenticated_orderflow", symbol=symbol)
            return []

        raw = await asyncio.to_thread(
            lambda: fyers.get_history(
                symbol=symbol,
                resolution="1",
                range_from=start.strftime("%Y-%m-%d"),
                range_to=end.strftime("%Y-%m-%d"),
            )
        )

        candles = raw.get("candles", []) if isinstance(raw, dict) else []
        if not candles:
            return []

        rows: list[_CandleRow] = []
        for row in candles:
            if len(row) < 6:
                continue
            rows.append(
                _CandleRow(
                    timestamp=datetime.utcfromtimestamp(row[0]),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=int(row[5]),
                )
            )
        # Keep a short in-memory copy so repeated orderflow calls are instant.
        if rows:
            await get_ohlc_cache().upsert(
                symbol,
                "1",
                [
                    {
                        "timestamp": r.timestamp.isoformat(),
                        "open": r.open,
                        "high": r.high,
                        "low": r.low,
                        "close": r.close,
                        "volume": r.volume,
                    }
                    for r in rows
                ],
            )
        return rows
    except Exception as exc:
        logger.warning("fyers_orderflow_fetch_failed", symbol=symbol, error=str(exc))
        return []


async def _fetch_1min_from_yahoo(
    symbol: str,
    start: datetime,
    end: datetime,
) -> list[_CandleRow]:
    ticker = _normalize_yahoo_ticker(symbol)
    if not ticker:
        return []

    def _parse_payload(raw_payload: dict[str, Any]) -> list[_CandleRow]:
        chart = raw_payload.get("chart", {}) if isinstance(raw_payload, dict) else {}
        results = chart.get("result", []) if isinstance(chart, dict) else []
        if not results or not isinstance(results[0], dict):
            return []
        result = results[0]
        timestamps = result.get("timestamp", []) or []
        quote_rows = (result.get("indicators", {}) or {}).get("quote", []) or []
        if not quote_rows or not isinstance(quote_rows[0], dict):
            return []
        quote = quote_rows[0]
        opens = quote.get("open", []) or []
        highs = quote.get("high", []) or []
        lows = quote.get("low", []) or []
        closes = quote.get("close", []) or []
        volumes = quote.get("volume", []) or []

        parsed_rows: list[_CandleRow] = []
        for idx, ts in enumerate(timestamps):
            if idx >= len(opens) or idx >= len(highs) or idx >= len(lows) or idx >= len(closes):
                continue
            o = opens[idx]
            h = highs[idx]
            l = lows[idx]
            c = closes[idx]
            if o is None or h is None or l is None or c is None:
                continue
            vol = volumes[idx] if idx < len(volumes) and volumes[idx] is not None else 0
            parsed_rows.append(
                _CandleRow(
                    timestamp=datetime.utcfromtimestamp(int(ts)),
                    open=float(o),
                    high=float(h),
                    low=float(l),
                    close=float(c),
                    volume=int(vol),
                )
            )
        return parsed_rows

    timeout = httpx.Timeout(8.0, connect=4.0)
    target_rows = max(int((end - start).total_seconds() // 60) + 40, 240)
    try:
        async with httpx.AsyncClient(timeout=timeout, headers=_YAHOO_HEADERS) as http:
            res = await http.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
                params={
                    "interval": "1m",
                    "period1": int(start.timestamp()),
                    "period2": int(end.timestamp()),
                },
            )
            if res.status_code >= 400:
                return []
            rows = _parse_payload(res.json())
            if rows:
                return rows

            # Off-session requests can return empty intraday windows. Fall back
            # to the most recent session history so chart tabs render instantly.
            fallback = await http.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
                params={"interval": "1m", "range": "5d"},
            )
            if fallback.status_code >= 400:
                return []
            rows = _parse_payload(fallback.json())
            return rows[-target_rows:]
    except Exception as exc:
        logger.warning("orderflow_yahoo_fetch_failed", symbol=symbol, error=str(exc))
        return []


async def _fetch_1min_from_nasdaq(
    symbol: str,
    start: datetime,
    end: datetime,
) -> list[_CandleRow]:
    # Disabled intentionally: chart-point reconstruction from last-trade ticks
    # produces synthetic OHLCV bars.
    return []


async def _fetch_1min_from_binance(
    symbol: str,
    start: datetime,
    end: datetime,
) -> list[_CandleRow]:
    pair = _normalize_crypto_pair(symbol)
    if not pair:
        return []

    timeout = httpx.Timeout(8.0, connect=4.0)
    out: list[_CandleRow] = []
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    cursor = start_ms

    try:
        async with httpx.AsyncClient(timeout=timeout) as http:
            while cursor < end_ms:
                res = await http.get(
                    "https://api.binance.com/api/v3/klines",
                    params={
                        "symbol": pair,
                        "interval": "1m",
                        "startTime": cursor,
                        "endTime": end_ms,
                        "limit": 1000,
                    },
                )
                if res.status_code >= 400:
                    break
                payload = res.json()
                if not isinstance(payload, list) or not payload:
                    break
                for row in payload:
                    if not isinstance(row, list) or len(row) < 6:
                        continue
                    out.append(
                        _CandleRow(
                            timestamp=datetime.utcfromtimestamp(int(row[0]) / 1000.0),
                            open=float(row[1]),
                            high=float(row[2]),
                            low=float(row[3]),
                            close=float(row[4]),
                            volume=int(float(row[5])),
                        )
                    )
                last_open = int(payload[-1][0])
                next_cursor = last_open + 60_000
                if next_cursor <= cursor:
                    break
                cursor = next_cursor
    except Exception as exc:
        logger.warning("orderflow_binance_fetch_failed", symbol=symbol, error=str(exc))
        return []

    return out


def _load_cached_candles(
    symbol: str,
    timeframe: str,
    hours: int,
) -> list[_CandleRow]:
    """Load recent candles from in-memory OHLC cache for one timeframe."""
    cache = get_ohlc_cache()
    tf_minutes = max(int(timeframe), 1) if timeframe.isdigit() else 1
    frame = cache.as_dataframe(
        symbol,
        timeframe,
        limit=max((hours * 60) // tf_minutes + 40, 80),
    )
    if frame.empty:
        return []

    cutoff = datetime.utcnow() - timedelta(hours=hours)
    index = frame.index
    if getattr(index, "tz", None) is not None:
        frame.index = index.tz_convert(None)  # type: ignore[assignment]
    clipped = frame[frame.index >= cutoff]
    if clipped.empty:
        # During off-market hours, keep the most recent bars so the chart
        # can still render immediately instead of looking broken.
        clipped = frame.tail(max((hours * 60) // tf_minutes + 40, 80))
    if clipped.empty:
        return []

    rows: list[_CandleRow] = []
    for ts, row in clipped.iterrows():
        rows.append(
            _CandleRow(
                timestamp=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row["volume"]),
            )
        )
    return rows


async def _load_db_candles_for_timeframe(
    db: AsyncSession,
    symbol: str,
    timeframe: str,
    hours: int,
) -> list[Any]:
    """Load candles from DB for one timeframe with shifted-window fallback."""
    tf_minutes = max(int(timeframe), 1) if timeframe.isdigit() else 1
    max_rows = max((hours * 60) // tf_minutes + 10, 80)
    end = datetime.utcnow()
    start = end - timedelta(hours=hours)

    rows = list(
        await get_ohlc_candles(
            db,
            symbol,
            timeframe,
            start,
            end,
            limit=max_rows,
        )
    )
    if rows:
        return rows

    latest_ts = await get_latest_ohlc_timestamp(db, symbol, timeframe)
    if latest_ts is None:
        return []

    shifted_end = latest_ts
    if getattr(shifted_end, "tzinfo", None) is not None:
        shifted_end = shifted_end.replace(tzinfo=None)
    shifted_start = shifted_end - timedelta(hours=hours)
    return list(
        await get_ohlc_candles(
            db,
            symbol,
            timeframe,
            shifted_start,
            shifted_end,
            limit=max_rows,
        )
    )


async def _cache_rows(
    symbol: str,
    timeframe: str,
    rows: list[Any],
) -> None:
    if not rows:
        return
    await get_ohlc_cache().upsert(
        symbol,
        timeframe,
        [
            {
                "timestamp": r.timestamp.isoformat(),
                "open": float(r.open),
                "high": float(r.high),
                "low": float(r.low),
                "close": float(r.close),
                "volume": int(r.volume),
            }
            for r in rows
        ],
    )


async def _load_1min_candles(
    db: AsyncSession,
    symbol: str,
    hours: int,
) -> list[Any]:
    """Load the best available intraday candles for order-flow rendering.

    Preference order:
    1) In-memory cache: 1m -> 3m -> 5m -> 15m -> 60m
    2) DB store: same order
    3) External providers (US/crypto/NSE)
    """
    for timeframe in ("1", "3", "5", "15", "60"):
        cached_rows = _load_cached_candles(symbol, timeframe, hours)
        if cached_rows:
            return cached_rows

    end = datetime.utcnow()
    start = end - timedelta(hours=hours)

    rows: list[Any] = []
    try:
        for timeframe in ("1", "3", "5", "15", "60"):
            rows = await _load_db_candles_for_timeframe(db, symbol, timeframe, hours)
            if rows:
                await _cache_rows(symbol, timeframe, rows)
                return rows
    except Exception as exc:
        logger.warning("orderflow_db_unavailable_fallback", symbol=symbol, error=str(exc))
        rows = []

    market = _symbol_market(symbol)
    if market == "US":
        us_rows = await _fetch_1min_from_yahoo(symbol, start, end)
        if us_rows:
            await _cache_rows(symbol, "1", us_rows)
            return us_rows
    elif market == "NSE":
        nse_rows = await _fetch_1min_from_yahoo(symbol, start, end)
        if nse_rows:
            await _cache_rows(symbol, "1", nse_rows)
            return nse_rows
    elif market == "CRYPTO":
        crypto_rows = await _fetch_1min_from_binance(symbol, start, end)
        if crypto_rows:
            await _cache_rows(symbol, "1", crypto_rows)
            return crypto_rows

    return await _fetch_1min_from_fyers(symbol, start, end)


def _dominant_side(bid: int, ask: int) -> str:
    if ask > bid:
        return "ask"
    if bid > ask:
        return "bid"
    return "neutral"


def _footprints_from_realtime(symbol: str, bar_minutes: int, hours: int) -> list[dict[str, Any]]:
    """Build footprint payload directly from real-time aggregator history."""
    agg = get_tick_aggregator()
    bar_count = max(int((hours * 60) / max(bar_minutes, 1)) + 2, 10)
    bars = agg.get_history(symbol, bar_minutes, count=bar_count)
    if not bars:
        return []

    footprints: list[dict[str, Any]] = []
    cvd = 0

    for bar in bars:
        open_px = bar.get("open")
        close_px = bar.get("close")
        high_px = bar.get("high")
        low_px = bar.get("low")
        if open_px is None or close_px is None or high_px is None or low_px is None:
            continue

        levels_raw = bar.get("levels", {}) if isinstance(bar.get("levels", {}), dict) else {}
        levels: list[dict[str, Any]] = []
        total_bid = 0
        total_ask = 0
        imbalance_count = 0
        for price_raw, payload in sorted(
            levels_raw.items(),
            key=lambda item: float(item[0]),
        ):
            bid = int(float(payload.get("bid", 0)))
            ask = int(float(payload.get("ask", 0)))
            delta = ask - bid
            denom = max(ask, bid, 1)
            imbalance = abs(delta) / denom
            is_imbalanced = imbalance >= 0.30
            if is_imbalanced:
                imbalance_count += 1
            total_bid += bid
            total_ask += ask
            levels.append(
                {
                    "price": float(price_raw),
                    "bid": bid,
                    "ask": ask,
                    "delta": delta,
                    "imbalance": round(imbalance, 4),
                    "stack": False,
                    "dominant_side": _dominant_side(bid, ask),
                }
            )

        delta = int(float(bar.get("delta", 0)))
        cvd += delta
        total_volume = int(float(bar.get("volume", 0)))
        total_print_volume = max(total_bid + total_ask, 1)
        vwap = (
            sum(level["price"] * (level["bid"] + level["ask"]) for level in levels) / total_print_volume
            if levels
            else float(close_px)
        )
        buying_pressure = total_ask / max(total_bid + total_ask, 1)
        footprints.append(
            {
                "time": bar.get("open_time") or bar.get("close_time") or datetime.utcnow().isoformat(),
                "open": float(open_px),
                "high": float(high_px),
                "low": float(low_px),
                "close": float(close_px),
                "volume": total_volume,
                "delta": delta,
                "vwap": round(vwap, 6),
                "cvd": cvd,
                "levels": levels,
                "imbalance_count": imbalance_count,
                "buying_pressure": round(buying_pressure, 4),
                "selling_pressure": round(1.0 - buying_pressure, 4),
            }
        )
    return footprints


def _has_meaningful_footprints(footprints: list[dict[str, Any]]) -> bool:
    """Return True if at least one bar carries real order-flow information."""
    for bar in footprints:
        if int(float(bar.get("volume", 0))) > 0:
            return True
        if abs(float(bar.get("delta", 0))) > 0:
            return True
        levels = bar.get("levels", [])
        if isinstance(levels, list) and len(levels) > 0:
            return True
    return False


def _summarize_footprints_payload(footprints: list[dict[str, Any]]) -> dict[str, Any]:
    if not footprints:
        return {
            "bars": 0,
            "latest_delta": 0,
            "latest_cvd": 0,
            "delta_trend": "flat",
            "avg_buying_pressure": 0.5,
            "imbalance_ratio": 0.0,
            "stacked_levels": 0,
        }

    latest = footprints[-1]
    first_cvd = int(footprints[0].get("cvd", 0))
    last_cvd = int(latest.get("cvd", 0))
    trend = "up" if last_cvd > first_cvd else ("down" if last_cvd < first_cvd else "flat")

    all_levels = [lv for fp in footprints for lv in fp.get("levels", [])]
    imbalance_levels = [lv for lv in all_levels if float(lv.get("imbalance", 0.0)) >= 0.30]
    avg_buy = sum(float(fp.get("buying_pressure", 0.5)) for fp in footprints) / len(footprints)

    return {
        "bars": len(footprints),
        "latest_delta": int(latest.get("delta", 0)),
        "latest_cvd": last_cvd,
        "delta_trend": trend,
        "avg_buying_pressure": round(avg_buy, 4),
        "imbalance_ratio": round(len(imbalance_levels) / max(len(all_levels), 1), 4),
        "stacked_levels": sum(1 for lv in all_levels if lv.get("stack")),
    }


def _compress_levels(levels: list[dict[str, Any]], max_levels: int) -> list[dict[str, Any]]:
    """Reduce per-bar level count to keep payloads/UI rendering fast."""
    if max_levels <= 0 or len(levels) <= max_levels:
        return levels

    ordered = sorted(levels, key=lambda lv: float(lv.get("price", 0.0)))
    chunk_size = max(1, math.ceil(len(ordered) / max_levels))
    compressed: list[dict[str, Any]] = []

    for start in range(0, len(ordered), chunk_size):
        chunk = ordered[start:start + chunk_size]
        if not chunk:
            continue

        total_bid = sum(int(float(lv.get("bid", 0))) for lv in chunk)
        total_ask = sum(int(float(lv.get("ask", 0))) for lv in chunk)
        total_volume = max(total_bid + total_ask, 1)
        weighted_price = sum(
            float(lv.get("price", 0.0)) * (int(float(lv.get("bid", 0))) + int(float(lv.get("ask", 0))))
            for lv in chunk
        ) / total_volume

        delta = total_ask - total_bid
        imbalance = abs(delta) / max(total_ask, total_bid, 1)
        compressed.append(
            {
                "price": round(weighted_price, 6),
                "bid": total_bid,
                "ask": total_ask,
                "delta": delta,
                "imbalance": round(imbalance, 4),
                "stack": any(bool(lv.get("stack")) for lv in chunk),
                "dominant_side": _dominant_side(total_bid, total_ask),
            }
        )

    return compressed


def _compress_footprints(
    footprints: list[dict[str, Any]],
    max_levels: int,
) -> list[dict[str, Any]]:
    """Compress all footprint bars while preserving top-level metrics."""
    if max_levels <= 0:
        return footprints

    out: list[dict[str, Any]] = []
    for fp in footprints:
        raw_levels = fp.get("levels")
        levels = _compress_levels(
            [lv for lv in raw_levels if isinstance(lv, dict)] if isinstance(raw_levels, list) else [],
            max_levels=max_levels,
        )
        buying_pressure = (
            sum(int(float(lv.get("ask", 0))) for lv in levels)
            / max(sum(int(float(lv.get("bid", 0))) + int(float(lv.get("ask", 0))) for lv in levels), 1)
            if levels
            else float(fp.get("buying_pressure", 0.5))
        )

        next_fp = dict(fp)
        next_fp["levels"] = levels
        next_fp["imbalance_count"] = sum(1 for lv in levels if float(lv.get("imbalance", 0.0)) >= 0.30)
        next_fp["buying_pressure"] = round(buying_pressure, 4)
        next_fp["selling_pressure"] = round(1.0 - buying_pressure, 4)
        out.append(next_fp)
    return out


def _get_cached_payload(
    cache: dict[Any, tuple[datetime, dict[str, Any]]],
    key: Any,
) -> dict[str, Any] | None:
    entry = cache.get(key)
    if not entry:
        return None
    created_at, payload = entry
    if datetime.utcnow() - created_at > _FAST_CACHE_TTL:
        cache.pop(key, None)
        return None
    return payload


@router.get("/footprint/{symbol}")
async def get_footprint_candles(
    symbol: str,
    bar_minutes: int = Query(15, ge=1, le=120, description="Bar aggregation in minutes"),
    hours: int = Query(6, ge=1, le=48, description="Hours of 1-min data"),
    tick_size: float = Query(0.05, gt=0, description="Price tick size"),
    max_levels: int = Query(64, ge=8, le=320, description="Max rendered price levels per bar"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Generate footprint candles from 1-minute OHLC data."""
    cache_key = (symbol, bar_minutes, hours, round(tick_size, 6), max_levels)
    cached = _get_cached_payload(_footprint_cache, cache_key)
    if cached is not None:
        return cached

    logger.info(
        "orderflow_footprint_request",
        symbol=symbol,
        bar_minutes=bar_minutes,
        hours=hours,
        tick_size=tick_size,
        max_levels=max_levels,
    )

    realtime_footprints = _footprints_from_realtime(symbol, bar_minutes, hours)
    if len(realtime_footprints) >= 3 and _has_meaningful_footprints(realtime_footprints):
        compact = _compress_footprints(realtime_footprints, max_levels=max_levels)
        payload = {
            "symbol": symbol,
            "tick_size": tick_size,
            "bar_minutes": bar_minutes,
            "hours": hours,
            "max_levels": max_levels,
            "source": "realtime_aggregator",
            "summary": _summarize_footprints_payload(compact),
            "footprints": compact,
        }
        _footprint_cache[cache_key] = (datetime.utcnow(), payload)
        return payload

    candles = await _load_1min_candles(db, symbol, hours)
    if not candles:
        payload = {
            "symbol": symbol,
            "tick_size": tick_size,
            "bar_minutes": bar_minutes,
            "hours": hours,
            "max_levels": max_levels,
            "source": "no_data",
            "summary": _summarize_footprints_payload([]),
            "footprints": [],
        }
        _footprint_cache[cache_key] = (datetime.utcnow(), payload)
        return payload

    analyzer = OrderFlowAnalyzer(tick_size=tick_size)
    footprints = analyzer.build_footprints(candles, bar_minutes=bar_minutes)
    summary = analyzer.summarize(footprints)
    footprint_dicts = _compress_footprints([fp.to_dict() for fp in footprints], max_levels=max_levels)

    payload = {
        "symbol": symbol,
        "tick_size": tick_size,
        "bar_minutes": bar_minutes,
        "hours": hours,
        "max_levels": max_levels,
        "source": "historical_ohlc",
        "summary": summary,
        "footprints": footprint_dicts,
    }
    _footprint_cache[cache_key] = (datetime.utcnow(), payload)
    return payload


@router.get("/cvd/{symbol}")
async def get_cvd_series(
    symbol: str,
    hours: int = Query(6, ge=1, le=48, description="Hours of 1-min data"),
    tick_size: float = Query(0.05, gt=0, description="Price tick size"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return cumulative volume delta (CVD) time series."""
    cache_key = (symbol, hours, round(tick_size, 6))
    cached = _get_cached_payload(_cvd_cache, cache_key)
    if cached is not None:
        return cached

    logger.info("orderflow_cvd_request", symbol=symbol, hours=hours)

    realtime_footprints = _footprints_from_realtime(symbol, bar_minutes=1, hours=hours)
    if len(realtime_footprints) >= 3 and _has_meaningful_footprints(realtime_footprints):
        series = [
            {
                "time": fp["time"],
                "close": fp["close"],
                "volume": fp["volume"],
                "delta": fp["delta"],
                "cvd": fp["cvd"],
            }
            for fp in realtime_footprints
        ]
        payload = {
            "symbol": symbol,
            "hours": hours,
            "points": len(series),
            "source": "realtime_aggregator",
            "series": series,
        }
        _cvd_cache[cache_key] = (datetime.utcnow(), payload)
        return payload

    candles = await _load_1min_candles(db, symbol, hours)
    if not candles:
        payload = {
            "symbol": symbol,
            "hours": hours,
            "points": 0,
            "source": "no_data",
            "series": [],
        }
        _cvd_cache[cache_key] = (datetime.utcnow(), payload)
        return payload

    analyzer = OrderFlowAnalyzer(tick_size=tick_size)
    series = analyzer.build_cvd_series(candles)

    payload = {
        "symbol": symbol,
        "hours": hours,
        "points": len(series),
        "source": "historical_ohlc",
        "series": series,
    }
    _cvd_cache[cache_key] = (datetime.utcnow(), payload)
    return payload


@router.get("/summary/{symbol}")
async def get_orderflow_summary(
    symbol: str,
    bar_minutes: int = Query(15, ge=1, le=120, description="Bar aggregation in minutes"),
    hours: int = Query(6, ge=1, le=48, description="Hours of 1-min data"),
    tick_size: float = Query(0.05, gt=0, description="Price tick size"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get concise order-flow summary metrics."""
    realtime_footprints = _footprints_from_realtime(symbol, bar_minutes, hours)
    if len(realtime_footprints) >= 3 and _has_meaningful_footprints(realtime_footprints):
        return {
            "symbol": symbol,
            "bar_minutes": bar_minutes,
            "hours": hours,
            "source": "realtime_aggregator",
            "summary": _summarize_footprints_payload(realtime_footprints),
        }

    candles = await _load_1min_candles(db, symbol, hours)
    if not candles:
        return {
            "symbol": symbol,
            "bar_minutes": bar_minutes,
            "hours": hours,
            "source": "no_data",
            "summary": _summarize_footprints_payload([]),
        }

    analyzer = OrderFlowAnalyzer(tick_size=tick_size)
    footprints = analyzer.build_footprints(candles, bar_minutes=bar_minutes)

    return {
        "symbol": symbol,
        "bar_minutes": bar_minutes,
        "hours": hours,
        "source": "historical_ohlc",
        "summary": analyzer.summarize(footprints),
    }
