"""Market data API endpoints.

Provides REST access to OHLC candles, recent ticks, health checks,
and symbol listings.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_fyers_client
from src.data.ohlc_cache import get_ohlc_cache
from src.api.schemas import (
    CollectionRequest,
    CollectionStatusResponse,
    DataSummaryItem,
    WatchlistSymbolResponse,
)
from src.config.constants import ALL_TIMEFRAMES, ALL_WATCHLIST_SYMBOLS, INDEX_SYMBOLS
from src.config.market_hours import IST, US_EASTERN
from src.config.settings import get_settings
from src.database.connection import check_db_health
from src.database.operations import (
    batch_latest_prices,
    batch_watchlist_summary,
    count_ohlc_candles,
    get_latest_ohlc_timestamp,
    get_ohlc_candles,
    get_recent_ticks,
)
from src.integrations.fyers_client import FyersClient
from src.utils.logger import get_logger
from src.utils.us_market_data import parse_nasdaq_chart_timestamp, parse_nasdaq_historical_date

router = APIRouter(tags=["Market Data"])
logger = get_logger(__name__)
_US_CHART_SYMBOLS = [
    "US:SPY",
    "US:QQQ",
    "US:DIA",
    "US:IWM",
    "US:AAPL",
    "US:AMZN",
    "US:JPM",
    "US:XOM",
    "US:UNH",
    "US:CAT",
]
_CRYPTO_CHART_SYMBOLS = [
    "CRYPTO:BTCUSDT",
    "CRYPTO:ETHUSDT",
    "CRYPTO:BNBUSDT",
    "CRYPTO:SOLUSDT",
    "CRYPTO:XRPUSDT",
]
_YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://finance.yahoo.com/",
}
_NASDAQ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NiftyAITrader/1.0)",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.nasdaq.com/",
}
_US_ETF_TICKERS = {"SPY", "QQQ", "IWM", "DIA"}

# =========================================================================
# Collection Job Tracking
# =========================================================================

_collection_jobs: dict[str, CollectionStatusResponse] = {}
_collection_lock = threading.Lock()


def _symbol_market(symbol: str) -> str:
    token = str(symbol or "").strip().upper()
    if token.startswith("CRYPTO:"):
        return "CRYPTO"
    if token.startswith(("US:", "NASDAQ:", "NYSE:", "AMEX:")):
        return "US"
    return "NSE"


def _normalize_us_ticker(symbol: str) -> str:
    return str(symbol or "").split(":")[-1].strip().upper()


def _normalize_crypto_pair(symbol: str) -> str:
    pair = str(symbol or "").split(":")[-1].strip().upper().replace("/", "").replace("-", "")
    if pair.endswith("USD") and not pair.endswith("USDT"):
        pair = f"{pair}T"
    if pair.isalpha() and len(pair) <= 6:
        pair = f"{pair}USDT"
    return pair


def _crypto_base_market(symbol: str) -> tuple[str, str]:
    pair = _normalize_crypto_pair(symbol)
    if not pair:
        return "", "USD"

    for suffix, market in (
        ("USDT", "USD"),
        ("USDC", "USD"),
        ("USD", "USD"),
        ("BTC", "BTC"),
        ("ETH", "ETH"),
    ):
        if pair.endswith(suffix) and len(pair) > len(suffix):
            return pair[: -len(suffix)], market
    return pair, "USD"


def _finnhub_crypto_symbol(symbol: str) -> str:
    pair = _normalize_crypto_pair(symbol)
    return f"BINANCE:{pair}" if pair else ""


def _alpha_crypto_series_key(payload: dict[str, Any], interval: str | None) -> dict[str, Any] | None:
    candidate_keys: list[str] = []
    if interval:
        candidate_keys.extend(
            [
                f"Time Series Crypto ({interval})",
                f"Time Series ({interval})",
            ]
        )
    else:
        candidate_keys.extend(
            [
                "Time Series (Digital Currency Daily)",
                "Time Series Crypto (Digital Currency Daily)",
                "Time Series (Digital Currency Weekly)",
            ]
        )

    for key in candidate_keys:
        series = payload.get(key)
        if isinstance(series, dict) and series:
            return series

    for key, value in payload.items():
        if "time series" in str(key).lower() and isinstance(value, dict) and value:
            return value
    return None


def _alpha_crypto_value(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        raw = row.get(key)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value == value:
            return value
    return None




def _us_session_is_open(now: datetime | None = None) -> bool:
    current = (now or datetime.now(tz=IST)).astimezone(US_EASTERN)
    if current.weekday() >= 5:
        return False
    session_open = current.replace(hour=9, minute=30, second=0, microsecond=0)
    session_close = current.replace(hour=16, minute=0, second=0, microsecond=0)
    return session_open <= current <= session_close


def _us_intraday_rows_stale(rows: list["CandleResponse"], timeframe: str) -> bool:
    token = str(timeframe or "").strip().upper()
    if token in {"D", "W", "M"} or not rows or not _us_session_is_open():
        return False
    try:
        minutes = max(int(token), 1)
    except ValueError:
        return False
    latest = rows[-1].timestamp
    age = datetime.now(tz=IST) - latest.astimezone(IST)
    max_age = timedelta(minutes=max(minutes * 3, 20))
    return age > max_age


def _yahoo_interval_range(timeframe: str) -> tuple[str, str]:
    mapping = {
        "1": ("1m", "7d"),
        "2": ("2m", "7d"),
        "3": ("5m", "10d"),
        "5": ("5m", "30d"),
        "15": ("15m", "60d"),
        "30": ("30m", "60d"),
        "60": ("60m", "6mo"),
        "90": ("90m", "6mo"),
        "D": ("1d", "2y"),
        "W": ("1wk", "5y"),
        "M": ("1mo", "10y"),
    }
    return mapping.get(timeframe, ("15m", "60d"))


def _binance_interval(timeframe: str) -> str:
    mapping = {
        "1": "1m",
        "3": "3m",
        "5": "5m",
        "15": "15m",
        "30": "30m",
        "60": "1h",
        "120": "2h",
        "240": "4h",
        "D": "1d",
        "W": "1w",
        "M": "1M",
    }
    return mapping.get(timeframe, "15m")


def _timeframe_millis(timeframe: str) -> int:
    token = str(timeframe or "").strip().upper()
    mapping = {
        "D": 86_400_000,
        "W": 7 * 86_400_000,
        "M": 30 * 86_400_000,
    }
    if token in mapping:
        return mapping[token]
    if token.isdigit():
        return max(int(token), 1) * 60_000
    return 15 * 60_000


def _aggregate_price_points_to_candles(
    points: list[tuple[datetime, float]],
    timeframe: str,
    limit: int,
) -> list[CandleResponse]:
    if not points:
        return []
    ordered = sorted(points, key=lambda item: item[0])
    buckets: dict[datetime, dict[str, float]] = {}

    if timeframe == "D":
        bucket_size_seconds = 86_400
    elif timeframe.isdigit():
        bucket_size_seconds = max(int(timeframe), 1) * 60
    else:
        bucket_size_seconds = 15 * 60

    for ts, price in ordered:
        ts_ist = ts.astimezone(IST)
        if bucket_size_seconds >= 86_400:
            bucket = datetime(ts_ist.year, ts_ist.month, ts_ist.day, tzinfo=IST)
        else:
            bucket_epoch = (int(ts_ist.timestamp()) // bucket_size_seconds) * bucket_size_seconds
            bucket = datetime.fromtimestamp(bucket_epoch, tz=timezone.utc).astimezone(IST)

        row = buckets.get(bucket)
        if row is None:
            buckets[bucket] = {
                "open": price,
                "high": price,
                "low": price,
                "close": price,
            }
            continue
        row["high"] = max(row["high"], price)
        row["low"] = min(row["low"], price)
        row["close"] = price

    candles = [
        CandleResponse(
            timestamp=bucket,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=0,
        )
        for bucket, row in sorted(buckets.items(), key=lambda item: item[0])
    ]
    return candles[-limit:]


def _aggregate_daily_candles(
    rows: list[CandleResponse],
    timeframe: str,
    limit: int,
) -> list[CandleResponse]:
    token = str(timeframe or "").strip().upper()
    if token == "D":
        return rows[-limit:]

    buckets: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        ts = row.timestamp.astimezone(IST)
        if token == "W":
            year, week, _ = ts.isocalendar()
            key = (year, week)
        elif token == "M":
            key = (ts.year, ts.month)
        else:
            return rows[-limit:]

        bucket = buckets.get(key)
        if bucket is None:
            buckets[key] = {
                "timestamp": ts,
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "volume": row.volume,
            }
            continue
        bucket["high"] = max(float(bucket["high"]), float(row.high))
        bucket["low"] = min(float(bucket["low"]), float(row.low))
        bucket["close"] = row.close
        bucket["volume"] = int(bucket["volume"]) + int(row.volume)

    aggregated = [
        CandleResponse(
            timestamp=value["timestamp"],
            open=float(value["open"]),
            high=float(value["high"]),
            low=float(value["low"]),
            close=float(value["close"]),
            volume=int(value["volume"]),
        )
        for _, value in sorted(buckets.items(), key=lambda item: item[0])
    ]
    return aggregated[-limit:]


async def _fetch_us_ohlc_nasdaq(symbol: str, timeframe: str, limit: int) -> list[CandleResponse]:
    ticker = _normalize_us_ticker(symbol)
    if not ticker:
        return []
    assetclass = "etf" if ticker in _US_ETF_TICKERS else "stocks"
    tf_token = str(timeframe or "").strip().upper()
    timeout = httpx.Timeout(8.0, connect=4.0)
    async with httpx.AsyncClient(timeout=timeout, headers=_NASDAQ_HEADERS) as http:
        if tf_token in {"D", "W", "M"}:
            to_date = datetime.now(tz=IST).date()
            from_date = to_date - timedelta(days=730 if tf_token in {"W", "M"} else 120)
            res = await http.get(
                f"https://api.nasdaq.com/api/quote/{ticker}/historical",
                params={
                    "assetclass": assetclass,
                    "fromdate": from_date.strftime("%Y-%m-%d"),
                    "todate": to_date.strftime("%Y-%m-%d"),
                    "limit": max(limit * 8, 120),
                },
            )
            if res.status_code >= 400:
                return []
            payload = res.json()
            data = payload.get("data", {}) if isinstance(payload, dict) else {}
            trades_table = data.get("tradesTable", {}) if isinstance(data, dict) else {}
            history_rows = trades_table.get("rows", []) if isinstance(trades_table, dict) else []
            candles: list[CandleResponse] = []
            for row in reversed(history_rows):
                if not isinstance(row, dict):
                    continue
                try:
                    timestamp = parse_nasdaq_historical_date(row.get("date"))
                    if timestamp is None:
                        continue
                    candles.append(
                        CandleResponse(
                            timestamp=timestamp,
                            open=float(str(row.get("open", "0")).replace("$", "").replace(",", "")),
                            high=float(str(row.get("high", "0")).replace("$", "").replace(",", "")),
                            low=float(str(row.get("low", "0")).replace("$", "").replace(",", "")),
                            close=float(str(row.get("close", "0")).replace("$", "").replace(",", "")),
                            volume=int(float(str(row.get("volume", "0")).replace(",", ""))),
                        )
                    )
                except (TypeError, ValueError):
                    continue
            return _aggregate_daily_candles(candles, tf_token, limit)

        res = await http.get(
            f"https://api.nasdaq.com/api/quote/{ticker}/chart",
            params={"assetclass": assetclass},
        )
        if res.status_code >= 400:
            return []
        payload = res.json()
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    chart_rows = data.get("chart", []) if isinstance(data, dict) else []
    time_as_of = data.get("timeAsOf") if isinstance(data, dict) else None
    points: list[tuple[datetime, float]] = []
    for row in chart_rows:
        if not isinstance(row, dict):
            continue
        px_raw = row.get("y")
        try:
            ts = parse_nasdaq_chart_timestamp(row, time_as_of=time_as_of)
            price = float(px_raw)
        except (TypeError, ValueError):
            continue
        if ts is None:
            continue
        if price <= 0:
            continue
        points.append((ts, price))
    return _aggregate_price_points_to_candles(points, timeframe, limit)


async def _fetch_us_ohlc(symbol: str, timeframe: str, limit: int) -> list[CandleResponse]:
    ticker = _normalize_us_ticker(symbol)
    if not ticker:
        return []
    settings = get_settings()
    prefer_finnhub = bool(str(settings.finnhub_api_key or "").strip())

    rows: list[CandleResponse] = []
    if prefer_finnhub:
        rows = await _fetch_us_ohlc_finnhub(ticker=ticker, timeframe=timeframe, limit=limit)
    if rows and not _us_intraday_rows_stale(rows, timeframe):
        return rows
    rows = await _fetch_us_ohlc_alphavantage(ticker=ticker, timeframe=timeframe, limit=limit)
    if rows and not _us_intraday_rows_stale(rows, timeframe):
        return rows
    rows = await _fetch_us_ohlc_yahoo(ticker=ticker, timeframe=timeframe, limit=limit)
    if rows and not _us_intraday_rows_stale(rows, timeframe):
        return rows
    rows = await _fetch_us_ohlc_nasdaq(symbol=symbol, timeframe=timeframe, limit=limit)
    if rows and not _us_intraday_rows_stale(rows, timeframe):
        return rows
    rows = await _fetch_us_ohlc_finnhub(ticker=ticker, timeframe=timeframe, limit=limit)
    if rows and not _us_intraday_rows_stale(rows, timeframe):
        return rows
    rows = await _fetch_us_ohlc_nasdaq(symbol=symbol, timeframe=timeframe, limit=limit)
    if rows:
        return rows
    return []


async def _fetch_us_ohlc_yahoo(ticker: str, timeframe: str, limit: int) -> list[CandleResponse]:
    interval, period = _yahoo_interval_range(timeframe)
    timeout = httpx.Timeout(8.0, connect=4.0)
    payload: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=timeout, headers=_YAHOO_HEADERS) as http:
        res = await http.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
            params={"interval": interval, "range": period},
        )
        if res.status_code < 400:
            payload = res.json()

    chart = payload.get("chart", {}) if isinstance(payload, dict) else {}
    results = chart.get("result", []) if isinstance(chart, dict) else []
    if not (results and isinstance(results[0], dict)):
        return []
    result = results[0]
    timestamps = result.get("timestamp", []) or []
    quote_rows = (result.get("indicators", {}) or {}).get("quote", []) or []
    if not (quote_rows and isinstance(quote_rows[0], dict)):
        return []
    quote = quote_rows[0]
    opens = quote.get("open", []) or []
    highs = quote.get("high", []) or []
    lows = quote.get("low", []) or []
    closes = quote.get("close", []) or []
    volumes = quote.get("volume", []) or []

    rows: list[CandleResponse] = []
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
        rows.append(
            CandleResponse(
                timestamp=datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(IST),
                open=float(o),
                high=float(h),
                low=float(l),
                close=float(c),
                volume=int(vol),
            )
        )
    return rows[-limit:]


def _finnhub_resolution_and_span(timeframe: str) -> tuple[str, int] | None:
    token = str(timeframe or "").strip().upper()
    if token in {"1", "5", "15", "30", "60"}:
        return token, 30 * 24 * 3600
    if token == "D":
        return "D", 2 * 365 * 24 * 3600
    if token == "W":
        return "W", 5 * 365 * 24 * 3600
    return None


async def _fetch_us_ohlc_finnhub(ticker: str, timeframe: str, limit: int) -> list[CandleResponse]:
    settings = get_settings()
    token = str(settings.finnhub_api_key or "").strip()
    if not token:
        return []
    mapped = _finnhub_resolution_and_span(timeframe)
    if mapped is None:
        return []
    resolution, span_seconds = mapped
    now_utc = datetime.now(tz=timezone.utc)
    end_ts = int(now_utc.timestamp())
    start_ts = end_ts - span_seconds
    timeout = httpx.Timeout(8.0, connect=4.0)
    async with httpx.AsyncClient(timeout=timeout) as http:
        res = await http.get(
            "https://finnhub.io/api/v1/stock/candle",
            params={
                "symbol": ticker,
                "resolution": resolution,
                "from": start_ts,
                "to": end_ts,
                "token": token,
            },
        )
        if res.status_code >= 400:
            return []
        payload = res.json()
    if not isinstance(payload, dict) or payload.get("s") != "ok":
        return []
    opens = payload.get("o", []) or []
    highs = payload.get("h", []) or []
    lows = payload.get("l", []) or []
    closes = payload.get("c", []) or []
    volumes = payload.get("v", []) or []
    timestamps = payload.get("t", []) or []
    rows: list[CandleResponse] = []
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
        rows.append(
            CandleResponse(
                timestamp=datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(IST),
                open=float(o),
                high=float(h),
                low=float(l),
                close=float(c),
                volume=int(vol),
            )
        )
    return rows[-limit:]


def _alphavantage_interval_for_timeframe(timeframe: str) -> str | None:
    token = str(timeframe or "").strip().upper()
    if token in {"1", "5", "15", "30", "60"}:
        return f"{token}min"
    return None


async def _fetch_us_ohlc_alphavantage(ticker: str, timeframe: str, limit: int) -> list[CandleResponse]:
    settings = get_settings()
    token = str(settings.alphavantage_api_key or "").strip()
    if not token:
        return []
    tf = str(timeframe or "").strip().upper()
    params: Dict[str, Any] = {
        "symbol": ticker,
        "apikey": token,
        "outputsize": "full",
    }
    daily = tf == "D"
    if daily:
        params["function"] = "TIME_SERIES_DAILY_ADJUSTED"
        series_key = "Time Series (Daily)"
    else:
        av_interval = _alphavantage_interval_for_timeframe(tf)
        if av_interval is None:
            return []
        params["function"] = "TIME_SERIES_INTRADAY"
        params["interval"] = av_interval
        series_key = f"Time Series ({av_interval})"

    timeout = httpx.Timeout(8.0, connect=4.0)
    async with httpx.AsyncClient(timeout=timeout) as http:
        res = await http.get("https://www.alphavantage.co/query", params=params)
        if res.status_code >= 400:
            return []
        payload = res.json()
    if not isinstance(payload, dict) or payload.get("Error Message") or payload.get("Note"):
        return []
    series = payload.get(series_key)
    if not isinstance(series, dict) or not series:
        return []

    rows: list[CandleResponse] = []
    for raw_ts, raw_row in series.items():
        if not isinstance(raw_row, dict):
            continue
        try:
            if daily:
                parsed = datetime.strptime(str(raw_ts), "%Y-%m-%d").replace(tzinfo=US_EASTERN)
            else:
                parsed = datetime.strptime(str(raw_ts), "%Y-%m-%d %H:%M:%S").replace(tzinfo=US_EASTERN)
            timestamp = parsed.astimezone(IST)
            rows.append(
                CandleResponse(
                    timestamp=timestamp,
                    open=float(raw_row.get("1. open")),
                    high=float(raw_row.get("2. high")),
                    low=float(raw_row.get("3. low")),
                    close=float(raw_row.get("4. close")),
                    volume=int(float(raw_row.get("5. volume", 0.0))),
                )
            )
        except Exception:
            continue
    rows = sorted(rows, key=lambda candle: candle.timestamp)
    return rows[-limit:]


def _finnhub_crypto_resolution_and_span(timeframe: str, limit: int) -> tuple[str, int] | None:
    token = str(timeframe or "").strip().upper()
    if token.isdigit():
        minutes = max(int(token), 1)
        return token, max(minutes * max(limit, 120) * 60, 14 * 24 * 3600)
    if token == "D":
        return "D", max(max(limit, 180) * 24 * 3600, 2 * 365 * 24 * 3600)
    if token == "W":
        return "W", max(max(limit, 104) * 7 * 24 * 3600, 5 * 365 * 24 * 3600)
    return None


async def _fetch_crypto_ohlc_finnhub(symbol: str, timeframe: str, limit: int) -> list[CandleResponse]:
    settings = get_settings()
    token = str(settings.finnhub_api_key or "").strip()
    if not token:
        return []

    mapped = _finnhub_crypto_resolution_and_span(timeframe, limit)
    finnhub_symbol = _finnhub_crypto_symbol(symbol)
    if mapped is None or not finnhub_symbol:
        return []

    resolution, span_seconds = mapped
    now_utc = datetime.now(tz=timezone.utc)
    end_ts = int(now_utc.timestamp())
    start_ts = end_ts - span_seconds

    timeout = httpx.Timeout(8.0, connect=4.0)
    async with httpx.AsyncClient(timeout=timeout) as http:
        res = await http.get(
            "https://finnhub.io/api/v1/crypto/candle",
            params={
                "symbol": finnhub_symbol,
                "resolution": resolution,
                "from": start_ts,
                "to": end_ts,
                "token": token,
            },
        )
        if res.status_code >= 400:
            return []
        payload = res.json()

    if not isinstance(payload, dict) or payload.get("s") != "ok":
        return []

    opens = payload.get("o", []) or []
    highs = payload.get("h", []) or []
    lows = payload.get("l", []) or []
    closes = payload.get("c", []) or []
    volumes = payload.get("v", []) or []
    timestamps = payload.get("t", []) or []

    rows: list[CandleResponse] = []
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
        rows.append(
            CandleResponse(
                timestamp=datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(IST),
                open=float(o),
                high=float(h),
                low=float(l),
                close=float(c),
                volume=int(float(vol)),
            )
        )
    return rows[-limit:]


async def _fetch_crypto_ohlc_alphavantage(symbol: str, timeframe: str, limit: int) -> list[CandleResponse]:
    settings = get_settings()
    token = str(settings.alphavantage_api_key or "").strip()
    if not token:
        return []

    base, market = _crypto_base_market(symbol)
    if not base:
        return []

    tf = str(timeframe or "").strip().upper()
    params: dict[str, Any] = {
        "symbol": base,
        "market": market,
        "apikey": token,
    }
    interval: str | None = None

    if tf == "D":
        params["function"] = "DIGITAL_CURRENCY_DAILY"
    else:
        interval = _alphavantage_interval_for_timeframe(tf)
        if interval is None:
            return []
        params["function"] = "CRYPTO_INTRADAY"
        params["interval"] = interval

    timeout = httpx.Timeout(8.0, connect=4.0)
    async with httpx.AsyncClient(timeout=timeout) as http:
        res = await http.get("https://www.alphavantage.co/query", params=params)
        if res.status_code >= 400:
            return []
        payload = res.json()

    if not isinstance(payload, dict) or payload.get("Error Message") or payload.get("Note"):
        return []

    series = _alpha_crypto_series_key(payload, interval)
    if not isinstance(series, dict) or not series:
        return []

    rows: list[CandleResponse] = []
    for raw_ts, raw_row in series.items():
        if not isinstance(raw_row, dict):
            continue
        try:
            if interval is None:
                parsed = datetime.strptime(str(raw_ts), "%Y-%m-%d").replace(tzinfo=timezone.utc)
            else:
                parsed = datetime.strptime(str(raw_ts), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)

            open_px = _alpha_crypto_value(raw_row, "1. open", f"1a. open ({market})")
            high_px = _alpha_crypto_value(raw_row, "2. high", f"2a. high ({market})")
            low_px = _alpha_crypto_value(raw_row, "3. low", f"3a. low ({market})")
            close_px = _alpha_crypto_value(raw_row, "4. close", f"4a. close ({market})")
            volume = _alpha_crypto_value(raw_row, "5. volume")
            if None in {open_px, high_px, low_px, close_px}:
                continue

            rows.append(
                CandleResponse(
                    timestamp=parsed.astimezone(IST),
                    open=float(open_px),
                    high=float(high_px),
                    low=float(low_px),
                    close=float(close_px),
                    volume=int(float(volume or 0.0)),
                )
            )
        except Exception:
            continue

    rows = sorted(rows, key=lambda candle: candle.timestamp)
    return rows[-limit:]


async def _fetch_crypto_ohlc_binance(symbol: str, timeframe: str, limit: int) -> list[CandleResponse]:
    pair = _normalize_crypto_pair(symbol)
    if not pair:
        return []
        
    # Try both .us and .com endpoints (GCloud US regions often block .com)
    domains = ["api.binance.us", "api.binance.com"]
    target = min(max(int(limit), 50), 5000)
    interval = _binance_interval(timeframe)
    interval_ms = _timeframe_millis(timeframe)
    timeout = httpx.Timeout(8.0, connect=4.0)
    
    for domain in domains:
        rows: list[CandleResponse] = []
        try:
            async with httpx.AsyncClient(timeout=timeout) as http:
                end_time: int | None = None
                requests = 0
                while len(rows) < target and requests < 8:
                    batch_limit = min(max(target - len(rows), 50), 1000)
                    params: Dict[str, Any] = {
                        "symbol": pair,
                        "interval": interval,
                        "limit": batch_limit,
                    }
                    if end_time is not None:
                        params["endTime"] = end_time

                    res = await http.get(f"https://{domain}/api/v3/klines", params=params)
                    if res.status_code == 451: # Unavailable For Legal Reasons (e.g. Binance.com in US)
                        logger.warning("binance_blocked_legal", domain=domain, symbol=symbol)
                        break
                    if res.status_code >= 400:
                        break
                        
                    payload = res.json()
                    if not isinstance(payload, list) or not payload:
                        break

                    batch_rows: list[CandleResponse] = []
                    for row in payload:
                        if not isinstance(row, list) or len(row) < 6:
                            continue
                        batch_rows.append(
                            CandleResponse(
                                timestamp=datetime.fromtimestamp(int(row[0]) / 1000.0, tz=timezone.utc).astimezone(IST),
                                open=float(row[1]),
                                high=float(row[2]),
                                low=float(row[3]),
                                close=float(row[4]),
                                volume=int(float(row[5])),
                            )
                        )
                    if not batch_rows:
                        break

                    batch_keys = {int(batch.timestamp.timestamp()) for batch in batch_rows}
                    rows = [
                        *batch_rows,
                        *[item for item in rows if int(item.timestamp.timestamp()) not in batch_keys],
                    ]

                    earliest_open_ms = int(payload[0][0])
                    end_time = earliest_open_ms - max(interval_ms, 1)
                    requests += 1

                    if len(payload) < batch_limit:
                        break
            
            if rows:
                return sorted(rows, key=lambda c: c.timestamp)[-target:]
                
        except Exception as e:
            logger.debug("binance_fetch_error", domain=domain, error=str(e))
            continue
            
    return []

async def _fetch_crypto_ohlc_yahoo(symbol: str, timeframe: str, limit: int) -> list[CandleResponse]:
    """Fallback to Yahoo Finance for crypto data (uses BTC-USD format)."""
    pair = _normalize_crypto_pair(symbol)
    if not pair:
        return []
    
    # Map symbols like BTCUSDT to BTC-USD for Yahoo
    base = pair.replace("USDT", "").replace("USDC", "").replace("TUSD", "")
    yahoo_ticker = f"{base}-USD"
    
    try:
        return await _fetch_us_ohlc_yahoo(yahoo_ticker, timeframe, limit)
    except Exception as e:
        logger.warning("yahoo_crypto_fallback_failed", symbol=symbol, ticker=yahoo_ticker, error=str(e))
        return []


async def _fetch_crypto_ohlc(symbol: str, timeframe: str, limit: int) -> list[CandleResponse]:
    candles = await _fetch_crypto_ohlc_binance(symbol, timeframe, limit)
    if candles:
        return candles[-limit:]
    
    return await _fetch_crypto_ohlc_yahoo(symbol, timeframe, limit)


def _build_crypto_quote_from_candles(
    symbol: str,
    candles: list[CandleResponse],
    *,
    source: str,
) -> dict[str, Any] | None:
    if not candles:
        return None

    ordered = sorted(candles, key=lambda candle: candle.timestamp)
    latest = ordered[-1]
    baseline = ordered[-25] if len(ordered) >= 25 else ordered[0]
    price = float(latest.close)
    reference_close = float(baseline.close or baseline.open or price)
    change = price - reference_close
    change_pct = (change / reference_close) * 100.0 if reference_close > 0 else 0.0

    session = ordered[-25:] if len(ordered) >= 25 else ordered
    session_high = max(float(item.high) for item in session)
    session_low = min(float(item.low) for item in session)
    session_volume = sum(int(item.volume) for item in session)
    pair = _normalize_crypto_pair(symbol)

    return {
        "symbol": symbol,
        "name": pair,
        "ltp": price,
        "open": float(baseline.open),
        "high": session_high,
        "low": session_low,
        "close": reference_close,
        "volume": int(session_volume),
        "change": change,
        "change_pct": change_pct,
        "timestamp": latest.timestamp.astimezone(IST).isoformat(),
        "source": source,
    }


async def _fetch_crypto_quote_snapshot(symbol: str) -> dict[str, Any] | None:
    settings = get_settings()
    if str(settings.finnhub_api_key or "").strip():
        candles = await _fetch_crypto_ohlc_finnhub(symbol, "60", 30)
        quote = _build_crypto_quote_from_candles(symbol, candles, source="finnhub")
        if quote is not None:
            return quote
    if str(settings.alphavantage_api_key or "").strip():
        candles = await _fetch_crypto_ohlc_alphavantage(symbol, "60", 30)
        quote = _build_crypto_quote_from_candles(symbol, candles, source="alphavantage")
        if quote is not None:
            return quote
    candles = await _fetch_crypto_ohlc_binance(symbol, "60", 30)
    return _build_crypto_quote_from_candles(symbol, candles, source="binance_fallback")


# =========================================================================
# Response Models
# =========================================================================


class HealthResponse(BaseModel):
    status: str
    database: bool
    version: str = "0.1.0"


class CandleResponse(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class OHLCResponse(BaseModel):
    symbol: str
    timeframe: str
    count: int
    candles: list[CandleResponse]


class TickResponse(BaseModel):
    symbol: str
    timestamp: datetime
    ltp: float
    bid: float | None = None
    ask: float | None = None
    volume: int = 0


class SymbolInfo(BaseModel):
    symbol: str
    timeframes: list[str]


class SymbolsResponse(BaseModel):
    symbols: list[SymbolInfo]


class DataSummary(BaseModel):
    symbol: str
    timeframe: str
    count: int
    latest_timestamp: datetime | None


# =========================================================================
# Endpoints
# =========================================================================


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """System health check including database connectivity."""
    db_ok = await check_db_health()
    status = "healthy" if db_ok else "degraded"
    return HealthResponse(status=status, database=db_ok)


@router.get("/symbols", response_model=SymbolsResponse)
async def list_symbols() -> SymbolsResponse:
    """List all supported symbols and their available timeframes."""
    return SymbolsResponse(
        symbols=[
            SymbolInfo(symbol=s, timeframes=list(ALL_TIMEFRAMES))
            for s in (list(INDEX_SYMBOLS) + _US_CHART_SYMBOLS + _CRYPTO_CHART_SYMBOLS)
        ]
    )


@router.get("/ohlc/{symbol:path}", response_model=OHLCResponse)
async def get_ohlc(
    symbol: str,
    timeframe: str = Query(default="D", description="Candle timeframe (1, 5, 15, 60, D, W, M)"),
    start: datetime | None = Query(default=None, description="Start timestamp (ISO 8601)"),
    end: datetime | None = Query(default=None, description="End timestamp (ISO 8601)"),
    limit: int = Query(default=500, ge=1, le=10000, description="Max candles to return"),
    db: AsyncSession = Depends(get_db),
) -> OHLCResponse:
    """Fetch OHLC candle data for a symbol.

    Serves from the in-memory cache first (< 1 ms) — DB and Fyers API are
    only hit when the cache has no data for this symbol/timeframe pair.

    Example: GET /api/v1/ohlc/NSE:NIFTY50-INDEX?timeframe=D&limit=100
    """
    if timeframe not in ALL_TIMEFRAMES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid timeframe '{timeframe}'. Valid: {ALL_TIMEFRAMES}",
        )

    # ── 1. In-memory cache (sub-millisecond) ────────────────────────────────
    cache = get_ohlc_cache()
    if cache.is_ready and cache.has(symbol, timeframe):
        cached = cache.get(symbol, timeframe, limit)
        if cached:
            logger.debug("ohlc_cache_hit", symbol=symbol, timeframe=timeframe, count=len(cached))
            return OHLCResponse(
                symbol=symbol,
                timeframe=timeframe,
                count=len(cached),
                candles=[
                    CandleResponse(
                        timestamp=datetime.fromisoformat(c["timestamp"]),
                        open=c["open"],
                        high=c["high"],
                        low=c["low"],
                        close=c["close"],
                        volume=c["volume"],
                    )
                    for c in cached
                ],
            )

    market = _symbol_market(symbol)
    if market in {"US", "CRYPTO"}:
        provider_candles = (
            await _fetch_us_ohlc(symbol, timeframe, limit)
            if market == "US"
            else await _fetch_crypto_ohlc(symbol, timeframe, limit)
        )
        if provider_candles:
            asyncio.create_task(
                cache.upsert(
                    symbol,
                    timeframe,
                    [
                        {
                            "timestamp": c.timestamp.isoformat(),
                            "open": c.open,
                            "high": c.high,
                            "low": c.low,
                            "close": c.close,
                            "volume": c.volume,
                        }
                        for c in provider_candles
                    ],
                )
            )
            return OHLCResponse(
                symbol=symbol,
                timeframe=timeframe,
                count=len(provider_candles),
                candles=provider_candles,
            )

    # ── 2. Database query (cache miss) ──────────────────────────────────────
    now = datetime.now(tz=IST)
    if end is None:
        end = now
    if start is None:
        start = end - timedelta(days=60)

    start_naive = start.replace(tzinfo=None) if start.tzinfo else start
    end_naive = end.replace(tzinfo=None) if end.tzinfo else end

    candles = await get_ohlc_candles(db, symbol, timeframe, start_naive, end_naive, limit)

    if candles:
        # Populate cache from DB result
        candle_dicts = [
            {
                "timestamp": c.timestamp.isoformat(),
                "open": float(c.open),
                "high": float(c.high),
                "low": float(c.low),
                "close": float(c.close),
                "volume": c.volume,
            }
            for c in candles
        ]
        asyncio.create_task(cache.upsert(symbol, timeframe, candle_dicts))
        return OHLCResponse(
            symbol=symbol,
            timeframe=timeframe,
            count=len(candles),
            candles=[
                CandleResponse(
                    timestamp=c.timestamp,
                    open=float(c.open),
                    high=float(c.high),
                    low=float(c.low),
                    close=float(c.close),
                    volume=c.volume,
                )
                for c in candles
            ],
        )

    # ── 3. Fyers REST API fallback (DB empty) ───────────────────────────────
    try:
        fyers = get_fyers_client()
        if fyers.is_authenticated:
            raw = await asyncio.to_thread(
                lambda: fyers.get_history(
                    symbol=symbol,
                    resolution=timeframe,
                    range_from=start_naive.strftime("%Y-%m-%d"),
                    range_to=end_naive.strftime("%Y-%m-%d"),
                )
            )
            if raw and "candles" in raw and raw["candles"]:
                candles_from_fyers: list[CandleResponse] = []
                cache_dicts: list[dict] = []
                for row in raw["candles"][-limit:]:
                    ts = datetime.utcfromtimestamp(row[0])
                    candles_from_fyers.append(
                        CandleResponse(
                            timestamp=ts,
                            open=float(row[1]),
                            high=float(row[2]),
                            low=float(row[3]),
                            close=float(row[4]),
                            volume=int(row[5]),
                        )
                    )
                    cache_dicts.append(
                        {
                            "timestamp": ts.isoformat(),
                            "open": float(row[1]),
                            "high": float(row[2]),
                            "low": float(row[3]),
                            "close": float(row[4]),
                            "volume": int(row[5]),
                        }
                    )
                logger.info(
                    "ohlc_fyers_fallback",
                    symbol=symbol,
                    timeframe=timeframe,
                    count=len(candles_from_fyers),
                )
                # Populate cache so the next request is instant
                asyncio.create_task(cache.upsert(symbol, timeframe, cache_dicts))
                return OHLCResponse(
                    symbol=symbol,
                    timeframe=timeframe,
                    count=len(candles_from_fyers),
                    candles=candles_from_fyers,
                )
    except Exception as exc:
        logger.warning("ohlc_fyers_fallback_failed", symbol=symbol, error=str(exc))

    # Nothing found anywhere
    return OHLCResponse(symbol=symbol, timeframe=timeframe, count=0, candles=[])


@router.get("/ticks/{symbol:path}", response_model=list[TickResponse])
async def get_ticks(
    symbol: str,
    limit: int = Query(default=100, ge=1, le=1000, description="Max ticks to return"),
    db: AsyncSession = Depends(get_db),
) -> list[TickResponse]:
    """Fetch the most recent ticks for a symbol.

    Example: GET /api/v1/ticks/NSE:NIFTY50-INDEX?limit=50
    """
    ticks = await get_recent_ticks(db, symbol, limit)
    return [
        TickResponse(
            symbol=t.symbol,
            timestamp=t.timestamp,
            ltp=float(t.ltp),
            bid=float(t.bid) if t.bid else None,
            ask=float(t.ask) if t.ask else None,
            volume=t.volume,
        )
        for t in ticks
    ]


@router.get("/summary/{symbol:path}", response_model=list[DataSummary])
async def get_data_summary(
    symbol: str,
    db: AsyncSession = Depends(get_db),
) -> list[DataSummary]:
    """Get a summary of stored data for each timeframe.

    Shows row counts and latest timestamps — useful for monitoring
    data collection status.
    """
    summaries = []
    for tf in ALL_TIMEFRAMES:
        count = await count_ohlc_candles(db, symbol, tf)
        latest = await get_latest_ohlc_timestamp(db, symbol, tf)
        summaries.append(
            DataSummary(
                symbol=symbol,
                timeframe=tf,
                count=count,
                latest_timestamp=latest,
            )
        )
    return summaries


# =========================================================================
# Watchlist Endpoints
# =========================================================================

# Display name mapping for clean UI
_DISPLAY_NAMES: dict[str, str] = {
    "NSE:NIFTY50-INDEX": "Nifty 50",
    "NSE:NIFTYBANK-INDEX": "Bank Nifty",
    "NSE:FINNIFTY-INDEX": "Fin Nifty",
    "NSE:NIFTYMIDCAP50-INDEX": "Midcap Nifty",
    "BSE:SENSEX-INDEX": "Sensex",
}


@router.get("/watchlist/symbols", response_model=list[WatchlistSymbolResponse])
async def get_watchlist_symbols(
    db: AsyncSession = Depends(get_db),
) -> list[WatchlistSymbolResponse]:
    """Get all tracked symbols with data summary — uses batch queries (2 total, not N*M)."""
    symbols = list(ALL_WATCHLIST_SYMBOLS)
    timeframes = list(ALL_TIMEFRAMES)

    # Two batch queries instead of 95 serial queries
    summary_map = await batch_watchlist_summary(db, symbols, timeframes)
    price_map = await batch_latest_prices(db, symbols)

    results = []
    for symbol in symbols:
        sym_summary = summary_map.get(symbol, {})
        summaries = []
        for tf in timeframes:
            info = sym_summary.get(tf, {"count": 0, "latest_timestamp": None})
            ts = info["latest_timestamp"]
            summaries.append(
                DataSummaryItem(
                    timeframe=tf,
                    count=info["count"],
                    latest_timestamp=ts.isoformat() if ts else None,
                )
            )

        prices = price_map.get(symbol, {})
        latest_price = prices.get("latest_price")
        prev_close = prices.get("prev_close")
        price_change_pct = None
        if latest_price is not None and prev_close is not None and prev_close > 0:
            price_change_pct = ((latest_price - prev_close) / prev_close) * 100

        results.append(
            WatchlistSymbolResponse(
                symbol=symbol,
                display_name=_DISPLAY_NAMES.get(symbol, symbol.split(":")[-1]),
                data_summary=summaries,
                latest_price=latest_price,
                price_change_pct=price_change_pct,
            )
        )
    return results


@router.post("/watchlist/collect", response_model=CollectionStatusResponse)
async def start_collection(
    request: CollectionRequest,
    client: FyersClient = Depends(get_fyers_client),
) -> CollectionStatusResponse:
    """Trigger background OHLC data collection for a symbol.

    Requires Fyers authentication. The collection runs in a background
    thread and progress can be tracked via GET /watchlist/collect/status.
    """
    # Check authentication
    is_auth = await asyncio.to_thread(lambda: client.is_authenticated)
    if not is_auth:
        raise HTTPException(
            status_code=401,
            detail="Fyers authentication required. Connect via Settings page.",
        )

    if request.timeframe not in ALL_TIMEFRAMES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid timeframe '{request.timeframe}'. Valid: {ALL_TIMEFRAMES}",
        )

    job_key = f"{request.symbol}:{request.timeframe}"

    # Check if already collecting
    with _collection_lock:
        existing = _collection_jobs.get(job_key)
        if existing and existing.status == "collecting":
            return existing

    # Create initial status
    status = CollectionStatusResponse(
        symbol=request.symbol,
        timeframe=request.timeframe,
        status="collecting",
        progress=0.0,
        candles_collected=0,
    )
    with _collection_lock:
        _collection_jobs[job_key] = status

    # Start background collection
    asyncio.create_task(
        _run_collection(client, request.symbol, request.timeframe, request.days_back, job_key)
    )

    return status


async def _run_collection(
    client: FyersClient,
    symbol: str,
    timeframe: str,
    days_back: int,
    job_key: str,
) -> None:
    """Run OHLC collection in a background thread."""
    from datetime import date as date_type
    from src.data.collectors.ohlc_collector import OHLCCollector, CollectionProgress

    def on_progress(progress: CollectionProgress) -> None:
        """Thread-safe progress callback."""
        with _collection_lock:
            job = _collection_jobs.get(job_key)
            if job:
                job.progress = progress.progress_pct
                job.candles_collected = progress.total_candles

    try:
        collector = OHLCCollector(
            client=client,
            symbols=[symbol],
            on_progress=on_progress,
        )

        end_date = date_type.today()
        start_date = end_date - timedelta(days=days_back)

        result = await asyncio.to_thread(
            collector.collect_symbol,
            symbol,
            timeframe,
            start_date,
            end_date,
        )

        with _collection_lock:
            job = _collection_jobs.get(job_key)
            if job:
                job.status = "completed" if result.success else "failed"
                job.progress = 100.0
                job.candles_collected = len(result.candles)
                if not result.success and result.progress.errors:
                    job.error = "; ".join(result.progress.errors[:3])

        logger.info(
            "collection_completed",
            symbol=symbol,
            timeframe=timeframe,
            candles=len(result.candles),
        )

    except Exception as exc:
        with _collection_lock:
            job = _collection_jobs.get(job_key)
            if job:
                job.status = "failed"
                job.error = str(exc)
        logger.error(
            "collection_failed",
            symbol=symbol,
            timeframe=timeframe,
            error=str(exc),
        )


@router.get("/watchlist/collect/status", response_model=list[CollectionStatusResponse])
async def get_collection_status() -> list[CollectionStatusResponse]:
    """Get status of all data collection jobs."""
    with _collection_lock:
        return list(_collection_jobs.values())
