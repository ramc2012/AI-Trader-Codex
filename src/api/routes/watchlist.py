"""
API endpoints for advanced watchlist and analytics.
Bloomberg terminal-grade data access.
"""

import asyncio
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_fyers_client, get_instrument_registry
from src.config.agent_universe import NIFTY50_WATCHLIST_SYMBOLS
from src.config.fno_constants import get_instrument as get_fno_instrument
from src.config.market_hours import IST
from src.config.settings import get_settings
from src.integrations.fyers_client import FyersClient
from src.utils.logger import get_logger
from src.watchlist.data_collector import IndexDataCollector
from src.watchlist.indices import INDIAN_INDICES
from src.watchlist.instrument_registry_service import InstrumentRegistryService
from src.watchlist.options_analytics import BlackScholes, OptionsAnalyzer
from src.watchlist.options_data_service import OptionsDataService

logger = get_logger(__name__)

router = APIRouter(tags=["Watchlist"])


_GLOBAL_WATCHLIST_CACHE: tuple[datetime, dict[str, Any]] | None = None
_GLOBAL_WATCHLIST_TTL_SECONDS = 30
_GLOBAL_WATCHLIST_STALE_SECONDS = 15 * 60
_GLOBAL_WATCHLIST_REFRESH_TASK: asyncio.Task[dict[str, Any]] | None = None
_US_UNDERLYINGS: list[tuple[str, str]] = [
    ("SPY", "SPDR S&P 500 ETF Trust"),
    ("QQQ", "Invesco QQQ Trust"),
    ("DIA", "SPDR Dow Jones Industrial Average ETF Trust"),
    ("IWM", "iShares Russell 2000 ETF"),
    ("AAPL", "Apple Inc."),
    ("AMZN", "Amazon.com Inc."),
    ("JPM", "JPMorgan Chase & Co."),
    ("XOM", "Exxon Mobil Corp."),
    ("UNH", "UnitedHealth Group"),
    ("CAT", "Caterpillar Inc."),
    ("PG", "Procter & Gamble"),
    ("LIN", "Linde plc"),
    ("NEE", "NextEra Energy"),
    ("DIS", "Walt Disney Co."),
]
_US_ASSET_CLASS: dict[str, str] = {
    "SPY": "etf",
    "QQQ": "etf",
    "DIA": "etf",
    "IWM": "etf",
}
_COINGECKO_TOP_COINS = 10
_CRYPTO_FALLBACK_PAIRS: list[tuple[str, str]] = [
    ("BTCUSDT", "Bitcoin"),
    ("ETHUSDT", "Ethereum"),
    ("USDTUSDT", "Tether"),
    ("BNBUSDT", "BNB"),
    ("SOLUSDT", "Solana"),
    ("XRPUSDT", "XRP"),
    ("USDCUSDT", "USD Coin"),
    ("ADAUSDT", "Cardano"),
    ("DOGEUSDT", "Dogecoin"),
    ("AVAXUSDT", "Avalanche"),
]


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _nasdaq_headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (compatible; NiftyAITrader/1.0)",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.nasdaq.com/",
    }


def _parse_num(text: Any) -> float:
    if text is None:
        return 0.0
    raw = str(text)
    raw = raw.replace("$", "").replace(",", "").replace("%", "").strip()
    if raw in {"", "--", "N/A"}:
        return 0.0
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _parse_last_trade_price(last_trade: str) -> float:
    # Example: "LAST TRADE: $263.75 (AS OF MAR 4, 2026)"
    raw = str(last_trade or "")
    dollar = re.search(r"\$([0-9][0-9,]*(?:\.[0-9]+)?)", raw)
    if dollar:
        return _parse_num(dollar.group(1))

    contextual = re.search(
        r"(?i)(?:last\s*(?:trade|sale)|close|price)\D*([0-9][0-9,]*(?:\.[0-9]+)?)",
        raw,
    )
    if contextual:
        return _parse_num(contextual.group(1))

    numbers = re.findall(r"([0-9][0-9,]*(?:\.[0-9]+)?)", raw)
    for token in numbers:
        if "." not in token:
            continue
        value = _parse_num(token)
        if value > 0:
            return value
    return 0.0


def _market_of_symbol(symbol: str) -> str:
    token = str(symbol or "").upper().strip()
    if token.startswith("CRYPTO:"):
        return "CRYPTO"
    if token.startswith(("US:", "NASDAQ:", "NYSE:", "AMEX:")):
        return "US"
    if token.startswith("BSE:"):
        return "BSE"
    return "NSE"


def _historical_bar_limit(days: int, resolution: str, market: str) -> int:
    token = str(resolution or "D").strip().upper()
    if token in {"D", "W", "M"}:
        return max(days + 10, 90)

    minutes = int(token) if token.isdigit() else 60
    if market == "CRYPTO":
        session_minutes = 24 * 60
    elif market == "US":
        session_minutes = (6 * 60) + 30
    else:
        session_minutes = (6 * 60) + 15

    bars_per_day = max((session_minutes + minutes - 1) // minutes, 1)
    target = (days * bars_per_day) + bars_per_day
    return min(max(target, 240), 5000)


async def _fetch_crypto_quote(symbol: str) -> dict[str, Any] | None:
    from src.api.routes.market_data import _fetch_crypto_quote_snapshot

    return await _fetch_crypto_quote_snapshot(symbol)


async def _fetch_us_quotes_yahoo() -> dict[str, dict[str, Any]]:
    symbols = [symbol for symbol, _ in _US_UNDERLYINGS]
    timeout = httpx.Timeout(8.0, connect=4.0)
    async with httpx.AsyncClient(timeout=timeout) as http:
        res = await http.get(
            "https://query1.finance.yahoo.com/v7/finance/quote",
            params={"symbols": ",".join(symbols)},
        )
        if res.status_code >= 400:
            return {}
        payload = res.json()

    rows = payload.get("quoteResponse", {}).get("result", []) if isinstance(payload, dict) else []
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = str((row or {}).get("symbol") or "").strip().upper()
        if not symbol:
            continue
        out[symbol] = {
            "symbol": symbol,
            "name": (row or {}).get("shortName") or symbol,
            "price": _f((row or {}).get("regularMarketPrice")),
            "change": _f((row or {}).get("regularMarketChange")),
            "change_pct": _f((row or {}).get("regularMarketChangePercent")),
            "volume": _i((row or {}).get("regularMarketVolume")),
            "currency": "USD",
            "market": "US",
            "source": "yahoo_fallback",
        }
    return out


async def _fetch_us_quotes_finnhub() -> dict[str, dict[str, Any]]:
    settings = get_settings()
    token = str(settings.finnhub_api_key or "").strip()
    if not token:
        return {}

    timeout = httpx.Timeout(8.0, connect=4.0)
    async with httpx.AsyncClient(timeout=timeout) as http:
        tasks = [
            asyncio.create_task(
                http.get(
                    "https://finnhub.io/api/v1/quote",
                    params={"symbol": symbol, "token": token},
                )
            )
            for symbol, _ in _US_UNDERLYINGS
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

    out: dict[str, dict[str, Any]] = {}
    for (symbol, label), response in zip(_US_UNDERLYINGS, responses):
        if isinstance(response, Exception) or response.status_code >= 400:
            continue
        payload = response.json()
        if not isinstance(payload, dict):
            continue
        price = _f(payload.get("c"))
        if price <= 0:
            continue
        out[symbol] = {
            "symbol": symbol,
            "name": label,
            "price": price,
            "change": _f(payload.get("d")),
            "change_pct": _f(payload.get("dp")),
            "volume": 0,
            "currency": "USD",
            "market": "US",
            "source": "finnhub",
        }
    return out


async def _fetch_us_quotes() -> list[dict[str, Any]]:
    timeout = httpx.Timeout(10.0, connect=4.0)
    headers = _nasdaq_headers()
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as http:
        tasks = [
            asyncio.create_task(
                http.get(
                    f"https://api.nasdaq.com/api/quote/{symbol}/info",
                    params={"assetclass": _US_ASSET_CLASS.get(symbol, "stocks")},
                )
            )
            for symbol, _ in _US_UNDERLYINGS
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

    out: list[dict[str, Any]] = []
    for (symbol, label), response in zip(_US_UNDERLYINGS, responses):
        if isinstance(response, Exception):
            out.append({"symbol": symbol, "name": label, "market": "US"})
            continue
        if response.status_code >= 400:
            out.append({"symbol": symbol, "name": label, "market": "US"})
            continue
        payload = response.json()
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        if not isinstance(data, dict):
            data = {}
        primary = data.get("primaryData", {}) or {}
        if not isinstance(primary, dict):
            primary = {}
        out.append(
            {
                "symbol": symbol,
                "name": data.get("companyName") or label,
                "price": _parse_num(primary.get("lastSalePrice")),
                "change": _parse_num(primary.get("netChange")),
                "change_pct": _parse_num(primary.get("percentageChange")),
                "volume": _i(_parse_num(primary.get("volume"))),
                "currency": "USD",
                "market": "US",
                "source": "nasdaq",
            }
        )

    need_fallback = any(_f(row.get("price")) <= 0 for row in out)
    if need_fallback:
        try:
            finnhub = await _fetch_us_quotes_finnhub()
        except Exception as exc:
            logger.warning("us_quotes_finnhub_fallback_failed", error=str(exc))
            finnhub = {}
        if finnhub:
            merged: list[dict[str, Any]] = []
            for row in out:
                symbol = str(row.get("symbol") or "").upper()
                fb = finnhub.get(symbol, {})
                merged_row = dict(row)
                if _f(merged_row.get("price")) <= 0 and _f(fb.get("price")) > 0:
                    merged_row.update(fb)
                merged.append(merged_row)
            out = merged

    need_fallback = any(_f(row.get("price")) <= 0 for row in out)
    if need_fallback:
        try:
            fallback = await _fetch_us_quotes_yahoo()
        except Exception as exc:
            logger.warning("us_quotes_fallback_failed", error=str(exc))
            fallback = {}
        if fallback:
            merged: list[dict[str, Any]] = []
            for row in out:
                symbol = str(row.get("symbol") or "").upper()
                fb = fallback.get(symbol, {})
                merged_row = dict(row)
                if _f(merged_row.get("price")) <= 0 and _f(fb.get("price")) > 0:
                    merged_row["price"] = _f(fb.get("price"))
                    merged_row["change"] = _f(fb.get("change"))
                    merged_row["change_pct"] = _f(fb.get("change_pct"))
                    merged_row["volume"] = _i(fb.get("volume"))
                    merged_row["name"] = fb.get("name") or merged_row.get("name")
                    merged_row["source"] = "yahoo_fallback"
                merged.append(merged_row)
            out = merged
    return out


async def _fetch_us_option_summary(symbol: str) -> dict[str, Any]:
    """Fetch ATM call/put snapshot for a US underlying from yfinance API."""
    try:
        import yfinance as yf
        import asyncio
        import pandas as pd
        import math
        
        def _fetch():
            ticker = yf.Ticker(symbol)
            expiries = ticker.options
            if not expiries:
                return None
            near_exp = expiries[0]
            chain = ticker.option_chain(near_exp)
            spot = getattr(ticker.fast_info, 'last_price', 0.0)
            if not spot:
                spot = ticker.info.get("regularMarketPrice") or 0.0
            return spot, near_exp, chain.calls, chain.puts

        data = await asyncio.to_thread(_fetch)
        if not data:
            return {"symbol": symbol}
        
        spot, expiry_str, calls, puts = data
        if spot <= 0 or calls.empty or puts.empty:
            return {"symbol": symbol, "spot": spot}
            
        calls_list = calls.to_dict('records')
        puts_list = puts.to_dict('records')
        calls_by_strike = {c['strike']: c for c in calls_list}
        puts_by_strike = {p['strike']: p for p in puts_list}
        
        common_strikes = set(calls_by_strike.keys()).intersection(set(puts_by_strike.keys()))
        if not common_strikes:
            return {"symbol": symbol, "spot": spot}
            
        tolerance = 0.03
        valid_strikes = [s for s in common_strikes if abs(s - spot) / spot <= tolerance]
        if not valid_strikes:
            valid_strikes = list(common_strikes)
            
        def _combo_oi(s):
            coi = calls_by_strike.get(s, {}).get('openInterest', 0)
            poi = puts_by_strike.get(s, {}).get('openInterest', 0)
            if math.isnan(coi): coi = 0
            if math.isnan(poi): poi = 0
            return coi + poi
            
        atm_strike = max(valid_strikes, key=_combo_oi)
        atm_call = calls_by_strike.get(atm_strike, {})
        atm_put = puts_by_strike.get(atm_strike, {})

        return {
            "symbol": symbol,
            "spot": spot,
            "expiry": expiry_str,
            "atm_strike": atm_strike,
            "call_last": float(atm_call.get("lastPrice", 0.0)),
            "call_bid": float(atm_call.get("bid", 0.0)) if not pd.isna(atm_call.get("bid")) else 0.0,
            "call_ask": float(atm_call.get("ask", 0.0)) if not pd.isna(atm_call.get("ask")) else 0.0,
            "call_iv": float(atm_call.get("impliedVolatility", 0.0)) if not pd.isna(atm_call.get("impliedVolatility")) else 0.0,
            "call_oi": int(atm_call.get("openInterest", 0)) if not pd.isna(atm_call.get("openInterest")) else 0,
            "put_last": float(atm_put.get("lastPrice", 0.0)),
            "put_bid": float(atm_put.get("bid", 0.0)) if not pd.isna(atm_put.get("bid")) else 0.0,
            "put_ask": float(atm_put.get("ask", 0.0)) if not pd.isna(atm_put.get("ask")) else 0.0,
            "put_iv": float(atm_put.get("impliedVolatility", 0.0)) if not pd.isna(atm_put.get("impliedVolatility")) else 0.0,
            "put_oi": int(atm_put.get("openInterest", 0)) if not pd.isna(atm_put.get("openInterest")) else 0,
        }
    except Exception as e:
        from src.utils.logger import get_logger
        get_logger(__name__).error("us_option_summary_failed", symbol=symbol, error=str(e))
        return {"symbol": symbol}


async def _fetch_crypto_top10() -> list[dict[str, Any]]:
    rows = await asyncio.gather(
        *[
            _fetch_crypto_quote(f"CRYPTO:{pair}")
            for pair, _ in _CRYPTO_FALLBACK_PAIRS[:_COINGECKO_TOP_COINS]
        ],
        return_exceptions=True,
    )

    out: list[dict[str, Any]] = []
    for rank, ((pair, label), row) in enumerate(
        zip(_CRYPTO_FALLBACK_PAIRS[:_COINGECKO_TOP_COINS], rows),
        start=1,
    ):
        if isinstance(row, Exception) or not isinstance(row, dict):
            continue
        out.append(
            {
                "symbol": pair.replace("USDT", ""),
                "name": label,
                "price_usd": _f(row.get("ltp")),
                "change_pct_24h": _f(row.get("change_pct")),
                "volume_24h": _f(row.get("volume")),
                "market_cap": 0.0,
                "rank": rank,
                "source": str(row.get("source") or "provider"),
            }
        )
    return out


async def _fetch_crypto_top10_binance() -> list[dict[str, Any]]:
    timeout = httpx.Timeout(8.0, connect=4.0)
    out: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=timeout) as http:
        tasks = [
            asyncio.create_task(http.get("https://api.binance.com/api/v3/ticker/24hr", params={"symbol": pair}))
            for pair, _ in _CRYPTO_FALLBACK_PAIRS
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

    for rank, ((pair, label), response) in enumerate(zip(_CRYPTO_FALLBACK_PAIRS, responses), start=1):
        if isinstance(response, Exception):
            continue
        if response.status_code >= 400:
            continue
        row = response.json() if response.content else {}
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "symbol": pair.replace("USDT", ""),
                "name": label,
                "price_usd": _f(row.get("lastPrice")),
                "change_pct_24h": _f(row.get("priceChangePercent")),
                "volume_24h": _f(row.get("quoteVolume")),
                "market_cap": 0.0,
                "rank": rank,
                "source": "binance_fallback",
            }
        )
    return out


def _build_default_global_payload(now: datetime, reason: str) -> dict[str, Any]:
    us_underlyings = [
        {"symbol": symbol, "name": label, "market": "US"}
        for symbol, label in _US_UNDERLYINGS
    ]
    return {
        "timestamp": now.isoformat(),
        "us_underlyings": us_underlyings,
        "us_options": [{"symbol": item["symbol"], "name": item["name"], "market": "US"} for item in us_underlyings],
        "crypto_top10": [],
        "sources": {"us": "nasdaq", "crypto": "providers"},
        "errors": [reason] if reason else [],
        "stale": True,
        "cache_age_seconds": None,
    }


async def _refresh_global_watchlist_cache() -> dict[str, Any]:
    """Fetch global US+crypto universe and atomically update cache."""
    global _GLOBAL_WATCHLIST_CACHE
    now = datetime.now(tz=IST)

    us_quotes: list[dict[str, Any]] = []
    us_option_focus: list[dict[str, Any]] = []
    crypto_top10: list[dict[str, Any]] = []
    errors: list[str] = []

    # Fetch base US quotes + top crypto in parallel.
    us_task = asyncio.create_task(_fetch_us_quotes())
    crypto_task = asyncio.create_task(_fetch_crypto_top10())
    for name, task in (("us_quotes", us_task), ("crypto_top10", crypto_task)):
        try:
            if name == "us_quotes":
                us_quotes = await task
            else:
                crypto_top10 = await task
        except Exception as exc:
            logger.warning("global_watchlist_fetch_failed", source=name, error=str(exc))
            errors.append(f"{name}: {exc}")

    if not crypto_top10:
        try:
            crypto_top10 = await _fetch_crypto_top10_binance()
            if crypto_top10:
                errors.append("crypto_top10: using_binance_fallback")
        except Exception as exc:
            logger.warning("global_watchlist_crypto_fallback_failed", error=str(exc))
            errors.append(f"crypto_fallback: {exc}")

    # Fetch ATM option snapshots for all configured US underlyings.
    option_tasks = [asyncio.create_task(_fetch_us_option_summary(symbol)) for symbol, _ in _US_UNDERLYINGS]
    option_results = await asyncio.gather(*option_tasks, return_exceptions=True)
    by_symbol = {row["symbol"]: row for row in us_quotes if row.get("symbol")}
    for result in option_results:
        if isinstance(result, Exception):
            errors.append(f"us_options: {result}")
            continue
        merged = dict(by_symbol.get(result.get("symbol", ""), {}))
        merged.update(result)
        if _f(merged.get("spot")) <= 0 and _f(merged.get("price")) > 0:
            merged["spot"] = _f(merged.get("price"))
        us_option_focus.append(merged)

    # Keep quote list stable in configured order.
    us_quote_by_symbol = {row.get("symbol"): row for row in us_quotes}
    us_underlyings = [
        us_quote_by_symbol.get(sym, {"symbol": sym, "name": label, "market": "US"})
        for sym, label in _US_UNDERLYINGS
    ]
    us_sources = sorted({
        str(row.get("source") or "nasdaq")
        for row in us_underlyings
        if str(row.get("source") or "").strip()
    })

    payload = {
        "timestamp": now.isoformat(),
        "us_underlyings": us_underlyings,
        "us_options": us_option_focus,
        "crypto_top10": crypto_top10,
        "sources": {
            "us": ",".join(us_sources) or "nasdaq",
            "crypto": ",".join(sorted({str(row.get("source") or "provider") for row in crypto_top10})) or "providers",
        },
        "errors": errors,
        "stale": False,
        "cache_age_seconds": 0,
    }
    _GLOBAL_WATCHLIST_CACHE = (now, payload)
    return payload


def _ensure_global_watchlist_refresh() -> asyncio.Task[dict[str, Any]]:
    global _GLOBAL_WATCHLIST_REFRESH_TASK
    if _GLOBAL_WATCHLIST_REFRESH_TASK and not _GLOBAL_WATCHLIST_REFRESH_TASK.done():
        return _GLOBAL_WATCHLIST_REFRESH_TASK
    _GLOBAL_WATCHLIST_REFRESH_TASK = asyncio.create_task(_refresh_global_watchlist_cache())
    return _GLOBAL_WATCHLIST_REFRESH_TASK


# Response Models
class IndexQuoteResponse(BaseModel):
    """Real-time quote for an index."""

    symbol: str
    name: str
    ltp: float
    open: float
    high: float
    low: float
    close: float
    volume: int
    change: Optional[float]
    change_pct: Optional[float]
    timestamp: str


class WatchlistSummaryResponse(BaseModel):
    """Summary of all indices in watchlist."""

    timestamp: str
    indices: List[Dict]
    total_count: int


class HistoricalDataResponse(BaseModel):
    """Historical OHLC data."""

    symbol: str
    resolution: str
    from_date: str
    to_date: str
    data: List[Dict]
    count: int


class DataAvailabilityResponse(BaseModel):
    """Data availability test results."""

    timestamp: str
    indices: Dict
    summary: Dict


class UniverseInstrumentResponse(BaseModel):
    """Tradable instrument exposed to watchlist/analytics selectors."""

    symbol: str
    display_name: str
    market: str
    exchange: str
    asset_class: str
    source: str
    tradable: bool = True
    derivatives: List[str] = Field(default_factory=list)


class WatchlistUniverseResponse(BaseModel):
    """Unified watchlist universe across India, US, and crypto."""

    timestamp: str
    markets: List[str]
    total_count: int
    items: List[UniverseInstrumentResponse]


class OptionGreeksResponse(BaseModel):
    """Option Greeks calculation."""

    spot: float
    strike: float
    time_to_expiry_days: int
    volatility: float
    option_type: str
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float


def _display_name_for_symbol(symbol: str) -> str:
    token = str(symbol or "").strip()
    if token.startswith("CRYPTO:"):
        pair = token.split(":", 1)[1]
        return pair.replace("USDT", "").strip() or pair
    if ":" in token:
        token = token.split(":", 1)[1]
    token = token.replace("-INDEX", "").replace("-EQ", "")
    return token.replace("-", " ").strip() or symbol


def _normalize_universe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        symbol = str(item.get("symbol") or "").strip()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        normalized = dict(item)
        normalized.setdefault("display_name", _display_name_for_symbol(symbol))
        normalized.setdefault("market", _market_of_symbol(symbol))
        normalized.setdefault("exchange", normalized["market"])
        normalized.setdefault("asset_class", "unknown")
        normalized.setdefault("source", "watchlist")
        normalized.setdefault("tradable", True)
        normalized.setdefault("derivatives", [])
        out.append(normalized)
    out.sort(key=lambda row: (str(row.get("market")), str(row.get("display_name"))))
    return out


# API Endpoints


@router.get("/watchlist/indices", response_model=List[Dict])
async def get_indices_list(
    client: FyersClient = Depends(get_fyers_client),
    registry: InstrumentRegistryService = Depends(get_instrument_registry),
):
    """
    Get list of all supported indices.

    Returns:
        List of index configurations
    """
    if not registry.get_cache():
        await asyncio.to_thread(registry.refresh, client)

    indices = []
    for name, idx in INDIAN_INDICES.items():
        item = registry.get_item(name)
        indices.append(
            {
                "name": name,
                "display_name": idx.display_name,
                "spot_symbol": idx.spot_symbol,
                "futures_symbol": item.futures_symbol if item else idx.futures_symbol,
                "sector": idx.sector,
                "lot_size": idx.lot_size,
                "expiries": item.to_dict().get("expiries", []) if item else [],
            }
        )

    logger.info("indices_list_requested", count=len(indices))
    return indices


@router.get("/watchlist/universe", response_model=WatchlistUniverseResponse)
async def get_watchlist_universe(
    market: str | None = Query(default=None, description="Optional market filter: NSE | BSE | US | CRYPTO"),
    search: str | None = Query(default=None, description="Optional case-insensitive symbol/name search"),
) -> WatchlistUniverseResponse:
    """Return the unified instrument universe used by watchlist and analytics screens."""
    settings = get_settings()
    items: list[dict[str, Any]] = []

    for name, idx in INDIAN_INDICES.items():
        symbol = idx.spot_symbol
        items.append(
            {
                "symbol": symbol,
                "display_name": idx.display_name,
                "market": _market_of_symbol(symbol),
                "exchange": str(symbol).split(":", 1)[0],
                "asset_class": "index",
                "source": "india_indices",
                "tradable": True,
                "derivatives": ["futures", "options"],
            }
        )

    for symbol in NIFTY50_WATCHLIST_SYMBOLS:
        root = symbol.split(":", 1)[-1].replace("-EQ", "").upper()
        fno = get_fno_instrument(root)
        derivatives = ["cash"]
        if fno is not None:
            derivatives = ["cash", "options", "futures"]
        items.append(
            {
                "symbol": symbol,
                "display_name": _display_name_for_symbol(symbol),
                "market": "NSE",
                "exchange": "NSE",
                "asset_class": "equity",
                "source": "nifty50",
                "tradable": True,
                "derivatives": derivatives,
            }
        )

    us_names = {symbol: label for symbol, label in _US_UNDERLYINGS}
    configured_us = [
        symbol.strip()
        for symbol in str(settings.agent_us_symbols or "").split(",")
        if symbol.strip()
    ]
    for symbol in configured_us:
        ticker = symbol.split(":", 1)[-1].upper()
        items.append(
            {
                "symbol": symbol,
                "display_name": us_names.get(ticker, ticker),
                "market": "US",
                "exchange": "US",
                "asset_class": _US_ASSET_CLASS.get(ticker, "equity"),
                "source": "agent_us_symbols",
                "tradable": True,
                "derivatives": ["options"],
            }
        )

    configured_crypto = [
        symbol.strip()
        for symbol in str(settings.agent_crypto_symbols or "").split(",")
        if symbol.strip()
    ]
    for symbol in configured_crypto:
        pair = symbol.split(":", 1)[-1].upper()
        items.append(
            {
                "symbol": symbol,
                "display_name": _display_name_for_symbol(symbol),
                "market": "CRYPTO",
                "exchange": "BINANCE",
                "asset_class": "crypto_spot",
                "source": "agent_crypto_symbols",
                "tradable": True,
                "derivatives": ["options"] if pair in {"BTCUSDT", "ETHUSDT"} else [],
            }
        )

    normalized = _normalize_universe_items(items)

    market_filter = str(market or "").strip().upper()
    if market_filter:
        normalized = [item for item in normalized if str(item.get("market", "")).upper() == market_filter]

    query = str(search or "").strip().lower()
    if query:
        normalized = [
            item
            for item in normalized
            if query in str(item.get("symbol", "")).lower()
            or query in str(item.get("display_name", "")).lower()
        ]

    markets = sorted({str(item.get("market") or "").upper() for item in normalized if item.get("market")})
    return WatchlistUniverseResponse(
        timestamp=datetime.now(tz=IST).isoformat(),
        markets=markets,
        total_count=len(normalized),
        items=[UniverseInstrumentResponse(**item) for item in normalized],
    )


@router.get("/watchlist/summary", response_model=WatchlistSummaryResponse)
async def get_watchlist_summary(
    client: FyersClient = Depends(get_fyers_client),
    registry: InstrumentRegistryService = Depends(get_instrument_registry),
):
    """
    Get real-time summary of all indices.
    Bloomberg-style overview with key metrics.

    Returns:
        Watchlist summary with quotes and analytics
    """
    try:
        if not registry.get_cache():
            await asyncio.to_thread(registry.refresh, client)

        collector = IndexDataCollector(client)
        collector.watchlist.indices = INDIAN_INDICES

        # Fetch all quotes
        quotes = await collector.fetch_all_quotes()

        # Get watchlist summary
        summary = collector.watchlist.get_watchlist_summary()

        logger.info("watchlist_summary_requested", quotes_count=len(quotes))
        return summary

    except Exception as exc:
        logger.error("get_watchlist_summary_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/watchlist/global/continuous")
async def get_global_continuous_watchlist() -> dict[str, Any]:
    """Global evaluation universe: US underlyings+ATM options + top-10 crypto.

    Designed for rapid dashboard validation even when local exchange feeds
    are delayed or partially unavailable.
    """
    global _GLOBAL_WATCHLIST_CACHE
    now = datetime.now(tz=IST)
    if _GLOBAL_WATCHLIST_CACHE is not None:
        created_at, payload = _GLOBAL_WATCHLIST_CACHE
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=IST)
        age_seconds = int((now - created_at).total_seconds())
        if age_seconds <= _GLOBAL_WATCHLIST_TTL_SECONDS:
            fresh = dict(payload)
            fresh["stale"] = False
            fresh["cache_age_seconds"] = age_seconds
            return fresh

        # Serve stale immediately; refresh in background for instant UI response.
        _ensure_global_watchlist_refresh()
        if age_seconds <= _GLOBAL_WATCHLIST_STALE_SECONDS:
            stale = dict(payload)
            stale["stale"] = True
            stale["cache_age_seconds"] = age_seconds
            return stale

    # No cache (or too stale): start refresh and wait briefly only.
    refresh = _ensure_global_watchlist_refresh()
    try:
        await asyncio.wait_for(asyncio.shield(refresh), timeout=1.2)
    except asyncio.TimeoutError:
        pass
    except Exception as exc:
        logger.warning("global_watchlist_refresh_failed", error=str(exc))

    if _GLOBAL_WATCHLIST_CACHE is not None:
        created_at, payload = _GLOBAL_WATCHLIST_CACHE
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=IST)
        stale = dict(payload)
        stale["cache_age_seconds"] = int((now - created_at).total_seconds())
        stale["stale"] = stale["cache_age_seconds"] > _GLOBAL_WATCHLIST_TTL_SECONDS
        return stale

    return _build_default_global_payload(now, reason="global_watchlist_warming")


async def warm_global_watchlist_cache() -> None:
    """Best-effort startup warmup to reduce first-screen latency."""
    try:
        await _refresh_global_watchlist_cache()
        logger.info("global_watchlist_cache_warmed")
    except Exception as exc:
        logger.warning("global_watchlist_cache_warm_failed", error=str(exc))


@router.get("/watchlist/quote/{symbol}", response_model=IndexQuoteResponse)
async def get_index_quote(
    symbol: str,
    client: FyersClient = Depends(get_fyers_client),
    registry: InstrumentRegistryService = Depends(get_instrument_registry),
):
    """
    Get real-time quote for a specific index.

    Args:
        symbol: Fyers symbol (e.g., NSE:NIFTY50-INDEX)

    Returns:
        Current market quote
    """
    try:
        market = _market_of_symbol(symbol)
        if market == "US":
            rows = await _fetch_us_quotes()
            ticker = str(symbol).split(":")[-1].upper()
            row = next((item for item in rows if str(item.get("symbol", "")).upper() == ticker), None)
            if row is None:
                raise HTTPException(status_code=404, detail="Quote not found")
            ltp = _f(row.get("price"))
            change = _f(row.get("change"))
            open_px = max(ltp - change, 0.0)
            return IndexQuoteResponse(
                symbol=symbol,
                name=str(row.get("name") or ticker),
                ltp=ltp,
                open=open_px,
                high=max(_f(row.get("price")), open_px),
                low=min(_f(row.get("price")), open_px),
                close=open_px,
                volume=_i(row.get("volume")),
                change=change,
                change_pct=_f(row.get("change_pct")),
                timestamp=datetime.now(tz=IST).isoformat(),
            )
        if market == "CRYPTO":
            quote = await _fetch_crypto_quote(symbol)
            if quote is None:
                raise HTTPException(status_code=404, detail="Quote not found")
            return IndexQuoteResponse(**quote)

        if not registry.get_cache():
            await asyncio.to_thread(registry.refresh, client)

        collector = IndexDataCollector(client)
        market_data = await collector.fetch_current_quote(symbol)

        if not market_data:
            raise HTTPException(status_code=404, detail="Quote not found")

        # Find index name
        index_name = "Unknown"
        for name, idx in INDIAN_INDICES.items():
            if idx.spot_symbol == symbol or idx.futures_symbol == symbol:
                index_name = idx.display_name
                break

        return IndexQuoteResponse(
            symbol=symbol,
            name=index_name,
            ltp=market_data.ltp,
            open=market_data.open,
            high=market_data.high,
            low=market_data.low,
            close=market_data.close,
            volume=market_data.volume,
            change=market_data.change,
            change_pct=market_data.change_pct,
            timestamp=market_data.timestamp.isoformat(),
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_index_quote_failed", symbol=symbol, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/watchlist/historical/{symbol}", response_model=HistoricalDataResponse)
async def get_historical_data(
    symbol: str,
    days: int = Query(default=30, ge=1, le=365, description="Number of days"),
    resolution: str = Query(default="D", description="Timeframe (D, 60, 15, etc.)"),
    client: FyersClient = Depends(get_fyers_client),
):
    """
    Get historical OHLC data for an index.

    Args:
        symbol: Fyers symbol
        days: Number of days of data
        resolution: Timeframe (D=Daily, 60=1Hour, 15=15Min)

    Returns:
        Historical OHLC data
    """
    try:
        market = _market_of_symbol(symbol)
        if market in {"US", "CRYPTO"}:
            limit = _historical_bar_limit(days, resolution, market)
            if market == "US":
                from src.api.routes.market_data import _fetch_us_ohlc

                candles = await _fetch_us_ohlc(symbol, resolution, limit)
            else:
                from src.api.routes.market_data import _fetch_crypto_ohlc

                candles = await _fetch_crypto_ohlc(symbol, resolution, limit)

            if not candles:
                raise HTTPException(status_code=404, detail="No historical data found")

            cutoff = datetime.now(tz=IST) - timedelta(days=days + 2)
            filtered = [c for c in candles if c.timestamp >= cutoff]
            data = [
                {
                    "timestamp": c.timestamp.isoformat(),
                    "open": float(c.open),
                    "high": float(c.high),
                    "low": float(c.low),
                    "close": float(c.close),
                    "volume": int(c.volume),
                }
                for c in filtered[-max(len(filtered), 1):]
            ]
            if not data:
                raise HTTPException(status_code=404, detail="No historical data found")

            to_date = datetime.now(tz=IST)
            from_date = to_date - timedelta(days=days)
            return HistoricalDataResponse(
                symbol=symbol,
                resolution=resolution,
                from_date=from_date.isoformat(),
                to_date=to_date.isoformat(),
                data=data,
                count=len(data),
            )

        collector = IndexDataCollector(client)

        to_date = datetime.now(tz=IST)
        from_date = to_date - timedelta(days=days)

        df = await collector.fetch_historical_ohlc(
            symbol, from_date, to_date, resolution
        )

        if df is None or len(df) == 0:
            raise HTTPException(status_code=404, detail="No historical data found")

        # Convert DataFrame to list of dicts
        data = []
        for idx, row in df.iterrows():
            data.append({
                "timestamp": idx.isoformat(),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]),
            })

        logger.info(
            "historical_data_requested",
            symbol=symbol,
            days=days,
            resolution=resolution,
            count=len(data),
        )

        return HistoricalDataResponse(
            symbol=symbol,
            resolution=resolution,
            from_date=from_date.isoformat(),
            to_date=to_date.isoformat(),
            data=data,
            count=len(data),
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_historical_data_failed", symbol=symbol, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/watchlist/test-data", response_model=DataAvailabilityResponse)
async def test_data_availability(
    client: FyersClient = Depends(get_fyers_client),
):
    """
    Test data availability for all indices.
    Validates historical data, quotes, and market depth.

    Returns:
        Comprehensive data availability report
    """
    try:
        collector = IndexDataCollector(client)
        results = await collector.test_data_availability()

        logger.info("data_availability_test_requested")
        return results

    except Exception as exc:
        logger.error("test_data_availability_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/watchlist/options/greeks", response_model=OptionGreeksResponse)
async def calculate_option_greeks(
    spot: float = Query(..., description="Underlying price"),
    strike: float = Query(..., description="Strike price"),
    days_to_expiry: int = Query(..., ge=0, description="Days to expiry"),
    volatility: float = Query(..., ge=0.01, le=5.0, description="IV (0.3 = 30%)"),
    option_type: str = Query(..., pattern="^(CE|PE)$", description="CE or PE"),
    rate: float = Query(default=0.07, description="Risk-free rate"),
):
    """
    Calculate option Greeks using Black-Scholes model.

    Args:
        spot: Current underlying price
        strike: Strike price
        days_to_expiry: Days until expiry
        volatility: Implied volatility (e.g., 0.3 for 30%)
        option_type: CE (Call) or PE (Put)
        rate: Risk-free rate (default 7%)

    Returns:
        Calculated Greeks
    """
    try:
        time_to_expiry = days_to_expiry / 365.0

        greeks = BlackScholes.calculate_greeks(
            spot=spot,
            strike=strike,
            time_to_expiry=time_to_expiry,
            volatility=volatility,
            rate=rate,
            option_type=option_type,
        )

        logger.info(
            "greeks_calculated",
            spot=spot,
            strike=strike,
            days=days_to_expiry,
            delta=greeks.delta,
        )

        return OptionGreeksResponse(
            spot=spot,
            strike=strike,
            time_to_expiry_days=days_to_expiry,
            volatility=volatility,
            option_type=option_type,
            delta=greeks.delta,
            gamma=greeks.gamma,
            theta=greeks.theta,
            vega=greeks.vega,
            rho=greeks.rho,
        )

    except Exception as exc:
        logger.error("calculate_greeks_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/watchlist/options/chain/{index_name}")
async def get_option_chain(
    index_name: str,
    expiry_date: Optional[str] = Query(None, description="Expiry date (YYYY-MM-DD)"),
    strike_count: int = Query(default=10, ge=1, le=25, description="Strikes around ATM"),
    include_expiries: int = Query(default=3, ge=1, le=6, description="Near/next/far expiries"),
    client: FyersClient = Depends(get_fyers_client),
    registry: InstrumentRegistryService = Depends(get_instrument_registry),
    db: AsyncSession = Depends(get_db),
):
    """
    Get options chain for an index.

    Args:
        index_name: Index name (NIFTY, BANKNIFTY, etc.)
        expiry_date: Optional expiry date

    Returns:
        Complete options chain with Greeks
    """
    try:
        index_name = index_name.upper()
        if index_name not in INDIAN_INDICES:
            raise HTTPException(status_code=404, detail="Index not found")

        if not registry.get_cache():
            await asyncio.to_thread(registry.refresh, client)

        idx = INDIAN_INDICES[index_name]
        service = OptionsDataService(client)

        expiry_ts: int | None = None
        if expiry_date:
            # Allow both epoch and ISO date input.
            if expiry_date.isdigit():
                expiry_ts = int(expiry_date)
            else:
                item = registry.get_item(index_name)
                if item:
                    for exp in item.expiries:
                        exp_iso = datetime.fromtimestamp(exp.expiry_ts).date().isoformat()
                        if expiry_date in {exp_iso, exp.date}:
                            expiry_ts = exp.expiry_ts
                            break

        chain_data = await asyncio.to_thread(
            service.get_canonical_chain,
            idx.spot_symbol,
            strike_count,
            expiry_ts,
            include_expiries,
        )
        if not chain_data.get("data", {}).get("expiryData"):
            raise HTTPException(status_code=404, detail="Option chain not available")

        persisted = await service.persist_canonical_chain(db, chain_data)
        logger.info(
            "option_chain_requested",
            index=index_name,
            expiries=len(chain_data.get("data", {}).get("expiryData", [])),
            rows_persisted=persisted,
        )
        return chain_data

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_option_chain_failed", index=index_name, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))
