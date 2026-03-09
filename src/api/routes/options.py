"""Canonical options data and analytics API endpoints."""

from __future__ import annotations

import asyncio
import httpx
import math
import re
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_fyers_client, get_instrument_registry
from src.config.market_hours import IST
from src.data.collectors.option_ohlc_collector import OptionOHLCCollector
from src.database.models import OptionChain
from src.database.operations import get_option_ohlc_candles
from src.integrations.fyers_client import FyersClient
from src.utils.logger import get_logger
from src.watchlist.indices import INDIAN_INDICES
from src.watchlist.instrument_registry_service import InstrumentRegistryService
from src.watchlist.options_analytics import BlackScholes
from src.watchlist.options_data_service import OptionsDataService

logger = get_logger(__name__)
router = APIRouter(tags=["Options"])
_US_ETF_TICKERS = {"SPY", "QQQ", "IWM", "DIA"}
_NASDAQ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NiftyAITrader/1.0)",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.nasdaq.com/",
}
_YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NiftyAITrader/1.0)",
    "Accept": "application/json, text/plain, */*",
}
_DERIBIT_SUPPORTED = {"BTC", "ETH"}


def _resolve_underlying_symbol(
    underlying: str,
    registry: InstrumentRegistryService,
) -> str:
    if ":" in underlying:
        return underlying
    key = underlying.upper()
    item = registry.get_item(key)
    if item:
        return item.spot_symbol
    if key in INDIAN_INDICES:
        return INDIAN_INDICES[key].spot_symbol
    raise HTTPException(status_code=404, detail=f"Unknown underlying: {underlying}")


def _resolve_lot_size(underlying_symbol: str, registry: InstrumentRegistryService) -> int:
    for item in registry.get_cache().values():
        if item.spot_symbol == underlying_symbol:
            return max(int(item.lot_size or 1), 1)
    return 1


def _underlying_market(symbol: str) -> str:
    token = str(symbol or "").upper()
    if token.startswith("US:"):
        return "US"
    if token.startswith("CRYPTO:"):
        return "CRYPTO"
    return "NSE"


def _f(value: Any) -> float:
    if value in (None, "", "--"):
        return 0.0
    if isinstance(value, str):
        value = value.replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _i(value: Any) -> int:
    return int(round(_f(value)))


def _coalesce_price(last: Any, bid: Any, ask: Any) -> float:
    last_value = _f(last)
    if last_value > 0:
        return last_value
    bid_value = _f(bid)
    ask_value = _f(ask)
    if bid_value > 0 and ask_value > 0:
        return (bid_value + ask_value) / 2.0
    return max(bid_value, ask_value, 0.0)


def _parse_us_last_trade_price(raw: str) -> float:
    match = re.search(r"\$([0-9,]+(?:\.[0-9]+)?)", str(raw or ""))
    return _f(match.group(1) if match else 0.0)


def _parse_us_expiry_group(raw: str) -> Optional[datetime]:
    label = str(raw or "").strip()
    if not label:
        return None
    try:
        return datetime.strptime(label, "%B %d, %Y").replace(tzinfo=IST)
    except ValueError:
        return None


def _build_occ_option_symbol(ticker: str, expiry: datetime, strike: float, option_type: str) -> str:
    cp_flag = "C" if option_type.upper().startswith("C") else "P"
    strike_code = max(int(round(float(strike) * 1000)), 1)
    return f"{ticker.upper()}{expiry.strftime('%y%m%d')}{cp_flag}{strike_code:08d}"


def _window_strikes(strikes: list[dict[str, Any]], spot: float, strike_count: int) -> list[dict[str, Any]]:
    if strike_count <= 0 or len(strikes) <= strike_count:
        return strikes
    if spot <= 0:
        return strikes[:strike_count]
    atm_index = min(range(len(strikes)), key=lambda idx: abs(float(strikes[idx]["strike"]) - spot))
    half_window = max(strike_count // 2, 1)
    start = max(atm_index - half_window, 0)
    end = min(start + strike_count, len(strikes))
    start = max(end - strike_count, 0)
    return strikes[start:end]


def _chain_quality(strikes: list[dict[str, Any]]) -> dict[str, Any]:
    rows = len(strikes)
    partial_rows = sum(
        1 for row in strikes
        if bool((row.get("quality") or {}).get("is_partial"))
    )
    nonzero_oi_rows = sum(
        1 for row in strikes
        if _i((row.get("ce") or {}).get("oi")) > 0 or _i((row.get("pe") or {}).get("oi")) > 0
    )
    integrity = 100.0 if rows == 0 else max(25.0, 100.0 - (partial_rows / rows) * 60.0)
    return {
        "is_stale": False,
        "integrity_score": round(integrity, 2),
        "rows": rows,
        "partial_rows": partial_rows,
        "nonzero_oi_rows": nonzero_oi_rows,
    }


def _normalize_yahoo_interval(interval: str) -> str:
    token = str(interval or "15").strip().lower()
    if token.endswith(("m", "h", "d")):
        return token
    try:
        minutes = max(int(token), 1)
    except (TypeError, ValueError):
        return "15m"
    if minutes >= 1440:
        return "1d"
    return f"{minutes}m"


def _normalize_deribit_resolution(interval: str) -> str:
    token = str(interval or "15").strip().lower()
    if token.endswith("d"):
        return "1D"
    if token.endswith("h"):
        try:
            return str(max(int(token[:-1]), 1) * 60)
        except ValueError:
            return "15"
    if token.endswith("m"):
        token = token[:-1]
    try:
        return str(max(int(token), 1))
    except (TypeError, ValueError):
        return "15"


def _iso_from_unix(ts: Any, *, milliseconds: bool = False) -> str:
    factor = 1000.0 if milliseconds else 1.0
    return datetime.fromtimestamp(float(ts) / factor, tz=IST).isoformat()


def _is_valid_ohlc(open_value: Any, high_value: Any, low_value: Any, close_value: Any) -> bool:
    values = (_f(open_value), _f(high_value), _f(low_value), _f(close_value))
    return all(math.isfinite(value) and value > 0 for value in values)


async def _fetch_us_option_chart_public(
    option_symbol: str,
    interval: str,
    days: int,
) -> list[dict[str, Any]]:
    contract_symbol = str(option_symbol).split(":", 1)[-1].upper()
    if not contract_symbol:
        raise HTTPException(status_code=404, detail=f"Unknown US option symbol: {option_symbol}")

    end = datetime.now(tz=IST)
    start = end - timedelta(days=days)
    params = {
        "period1": str(int(start.timestamp())),
        "period2": str(int(end.timestamp())),
        "interval": _normalize_yahoo_interval(interval),
        "includePrePost": "false",
        "events": "div,splits",
    }
    result: Optional[dict[str, Any]] = None
    timeout = httpx.Timeout(10.0, connect=4.0)
    async with httpx.AsyncClient(timeout=timeout, headers=_YAHOO_HEADERS) as http:
        for endpoint in (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{contract_symbol}",
            f"https://query2.finance.yahoo.com/v8/finance/chart/{contract_symbol}",
        ):
            res = await http.get(endpoint, params=params)
            if res.status_code >= 400:
                continue
            payload = res.json() if res.content else {}
            result_rows = ((payload.get("chart") or {}).get("result") or []) if isinstance(payload, dict) else []
            if result_rows:
                result = result_rows[0]
                break

    if not result:
        raise HTTPException(status_code=404, detail=f"No option chart data available for {option_symbol}")

    timestamps = result.get("timestamp") or []
    quote = (((result.get("indicators") or {}).get("quote") or [{}])[0]) if isinstance(result, dict) else {}
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    candles: list[dict[str, Any]] = []
    for idx, ts in enumerate(timestamps):
        open_value = opens[idx] if idx < len(opens) else None
        high_value = highs[idx] if idx < len(highs) else None
        low_value = lows[idx] if idx < len(lows) else None
        close_value = closes[idx] if idx < len(closes) else None
        if not _is_valid_ohlc(open_value, high_value, low_value, close_value):
            continue
        volume = volumes[idx] if idx < len(volumes) else 0
        candles.append(
            {
                "timestamp": _iso_from_unix(ts),
                "open": _f(open_value),
                "high": _f(high_value),
                "low": _f(low_value),
                "close": _f(close_value),
                "volume": max(_i(volume), 0),
            }
        )
    return candles


async def _fetch_crypto_option_chart_public(
    option_symbol: str,
    interval: str,
    days: int,
) -> list[dict[str, Any]]:
    instrument = str(option_symbol).split(":", 1)[-1].upper()
    if not instrument:
        raise HTTPException(status_code=404, detail=f"Unknown crypto option symbol: {option_symbol}")

    end = datetime.now(tz=IST)
    start = end - timedelta(days=days)
    timeout = httpx.Timeout(10.0, connect=4.0)
    async with httpx.AsyncClient(timeout=timeout) as http:
        res = await http.get(
            "https://www.deribit.com/api/v2/public/get_tradingview_chart_data",
            params={
                "instrument_name": instrument,
                "start_timestamp": str(int(start.timestamp() * 1000)),
                "end_timestamp": str(int(end.timestamp() * 1000)),
                "resolution": _normalize_deribit_resolution(interval),
            },
        )
        if res.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Deribit chart fetch failed for {option_symbol}")
        payload = res.json() if res.content else {}

    result = payload.get("result", {}) if isinstance(payload, dict) else {}
    timestamps = result.get("ticks") or []
    opens = result.get("open") or []
    highs = result.get("high") or []
    lows = result.get("low") or []
    closes = result.get("close") or []
    volumes = result.get("volume") or result.get("cost") or []
    if not timestamps:
        raise HTTPException(status_code=404, detail=f"No option chart data available for {option_symbol}")

    candles: list[dict[str, Any]] = []
    for idx, ts in enumerate(timestamps):
        open_value = opens[idx] if idx < len(opens) else None
        high_value = highs[idx] if idx < len(highs) else None
        low_value = lows[idx] if idx < len(lows) else None
        close_value = closes[idx] if idx < len(closes) else None
        if not _is_valid_ohlc(open_value, high_value, low_value, close_value):
            continue
        volume = volumes[idx] if idx < len(volumes) else 0
        candles.append(
            {
                "timestamp": _iso_from_unix(ts, milliseconds=True),
                "open": _f(open_value),
                "high": _f(high_value),
                "low": _f(low_value),
                "close": _f(close_value),
                "volume": max(_i(volume), 0),
            }
        )
    return candles


async def _fetch_public_option_chart(
    option_symbol: str,
    interval: str,
    days: int,
) -> list[dict[str, Any]]:
    market = _underlying_market(option_symbol)
    if market == "US":
        return await _fetch_us_option_chart_public(option_symbol, interval, days)
    if market == "CRYPTO":
        return await _fetch_crypto_option_chart_public(option_symbol, interval, days)
    raise HTTPException(status_code=404, detail=f"Unsupported public option symbol: {option_symbol}")


def _select_expiry_block(chain: dict[str, Any], expiry_ts: Optional[int]) -> dict[str, Any]:
    expiry_data = chain.get("data", {}).get("expiryData", [])
    if not expiry_data:
        raise HTTPException(status_code=404, detail="No option chain available for straddle")
    if expiry_ts is not None:
        matched = next(
            (block for block in expiry_data if int(block.get("expiry_ts") or 0) == int(expiry_ts)),
            None,
        )
        if matched is not None:
            return matched
    return expiry_data[0]


def _select_strike_row(
    strikes: list[dict[str, Any]],
    spot: float,
    strike: Optional[float],
) -> tuple[float, str, str]:
    if not strikes:
        raise HTTPException(status_code=404, detail="No strike rows available for straddle")

    if strike is None:
        selected = min(strikes, key=lambda row: abs(float(row.get("strike") or 0) - spot))
    else:
        selected = min(strikes, key=lambda row: abs(float(row.get("strike") or 0) - strike))

    strike_value = float(selected.get("strike") or 0)
    ce_symbol = str((selected.get("ce") or {}).get("symbol") or "")
    pe_symbol = str((selected.get("pe") or {}).get("symbol") or "")
    if ce_symbol and pe_symbol:
        return strike_value, ce_symbol, pe_symbol

    fallback = next(
        (
            row
            for row in sorted(strikes, key=lambda row: abs(float(row.get("strike") or 0) - strike_value))
            if (row.get("ce") or {}).get("symbol") and (row.get("pe") or {}).get("symbol")
        ),
        None,
    )
    if fallback is None:
        raise HTTPException(status_code=404, detail="CE/PE symbols missing for selected strike")
    return (
        float(fallback.get("strike") or 0),
        str((fallback.get("ce") or {}).get("symbol") or ""),
        str((fallback.get("pe") or {}).get("symbol") or ""),
    )


def _merge_straddle_candles(
    ce_candles: list[dict[str, Any]],
    pe_candles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    pe_by_ts = {str(candle.get("timestamp")): candle for candle in pe_candles}
    merged: list[dict[str, Any]] = []
    for ce in ce_candles:
        pe = pe_by_ts.get(str(ce.get("timestamp")))
        if pe is None:
            continue
        merged.append(
            {
                "timestamp": str(ce.get("timestamp")),
                "open": _f(ce.get("open")) + _f(pe.get("open")),
                "high": _f(ce.get("high")) + _f(pe.get("high")),
                "low": _f(ce.get("low")) + _f(pe.get("low")),
                "close": _f(ce.get("close")) + _f(pe.get("close")),
                "volume": _i(ce.get("volume")) + _i(pe.get("volume")),
            }
        )
    return merged


async def _fetch_public_straddle_candles(
    strikes: list[dict[str, Any]],
    spot: float,
    strike: Optional[float],
    interval: str,
    days: int,
) -> tuple[float, str, str, list[dict[str, Any]]]:
    if not strikes:
        raise HTTPException(status_code=404, detail="No strike rows available for straddle")

    anchor = spot if strike is None else float(strike)
    last_error: Optional[HTTPException] = None
    for row in sorted(strikes, key=lambda item: abs(float(item.get("strike") or 0) - anchor)):
        strike_value = float(row.get("strike") or 0)
        ce_symbol = str((row.get("ce") or {}).get("symbol") or "")
        pe_symbol = str((row.get("pe") or {}).get("symbol") or "")
        if not ce_symbol or not pe_symbol:
            continue
        try:
            ce_candles = await _fetch_public_option_chart(ce_symbol, interval, days)
            pe_candles = await _fetch_public_option_chart(pe_symbol, interval, days)
        except HTTPException as exc:
            last_error = exc
            continue
        merged = _merge_straddle_candles(ce_candles, pe_candles)
        if merged:
            return strike_value, ce_symbol, pe_symbol, merged

    if last_error is not None:
        raise HTTPException(
            status_code=404,
            detail=f"No option chart data available for {anchor:.2f}; no nearby strike had matched CE/PE candles.",
        ) from last_error
    raise HTTPException(status_code=404, detail="CE/PE symbols missing for selected strike")


async def _fetch_us_option_chain_public(
    underlying: str,
    strike_count: int,
    include_expiries: int,
) -> dict[str, Any]:
    ticker = str(underlying).split(":", 1)[-1].upper()
    if not ticker:
        raise HTTPException(status_code=404, detail=f"Unknown US underlying: {underlying}")

    endpoint = f"https://api.nasdaq.com/api/quote/{ticker}/option-chain"
    payload: dict[str, Any] = {}
    timeout = httpx.Timeout(10.0, connect=4.0)
    async with httpx.AsyncClient(timeout=timeout, headers=_NASDAQ_HEADERS) as http:
        for assetclass in (
            "etf" if ticker in _US_ETF_TICKERS else "stocks",
            "stocks",
            "etf",
        ):
            res = await http.get(endpoint, params={"assetclass": assetclass})
            if res.status_code >= 400:
                continue
            raw = res.json() if res.content else {}
            data = raw.get("data", {}) if isinstance(raw, dict) else {}
            if isinstance(data, dict) and data:
                payload = raw
                break

    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    rows = ((data.get("table") or {}).get("rows") or []) if isinstance(data, dict) else []
    if not rows:
        raise HTTPException(status_code=404, detail=f"No option chain available for {underlying}")

    fetched_at = datetime.now(tz=IST)
    spot = _parse_us_last_trade_price(str(data.get("lastTrade") or ""))
    grouped: dict[str, dict[str, Any]] = {}
    current_group: Optional[datetime] = None

    for row in rows:
        if not isinstance(row, dict):
            continue
        expiry_group = _parse_us_expiry_group(row.get("expirygroup"))
        if expiry_group is not None:
            current_group = expiry_group
        if current_group is None:
            continue
        strike = _f(row.get("strike"))
        if strike <= 0:
            continue
        expiry_key = current_group.strftime("%Y-%m-%d")
        expiry_bucket = grouped.setdefault(
            expiry_key,
            {
                "expiry_dt": current_group,
                "spot": spot,
                "strikes": {},
            },
        )
        expiry_bucket["spot"] = max(_f(expiry_bucket.get("spot")), spot)

        call_symbol = f"US:{_build_occ_option_symbol(ticker, current_group, strike, 'CALL')}"
        put_symbol = f"US:{_build_occ_option_symbol(ticker, current_group, strike, 'PUT')}"
        strike_bucket = expiry_bucket["strikes"].setdefault(
            strike,
            {
                "strike": strike,
                "ce": {
                    "symbol": call_symbol,
                    "ltp": 0.0,
                    "oi": 0,
                    "oich": 0,
                    "prev_oi": 0,
                    "iv": 0.0,
                    "volume": 0,
                    "bid": 0.0,
                    "ask": 0.0,
                    "delta": None,
                    "gamma": None,
                    "theta": None,
                    "vega": None,
                },
                "pe": {
                    "symbol": put_symbol,
                    "ltp": 0.0,
                    "oi": 0,
                    "oich": 0,
                    "prev_oi": 0,
                    "iv": 0.0,
                    "volume": 0,
                    "bid": 0.0,
                    "ask": 0.0,
                    "delta": None,
                    "gamma": None,
                    "theta": None,
                    "vega": None,
                },
                "quality": {"is_partial": False},
            },
        )
        strike_bucket["ce"].update(
            {
                "ltp": _coalesce_price(row.get("c_Last"), row.get("c_Bid"), row.get("c_Ask")),
                "oi": _i(row.get("c_Openinterest")),
                "volume": _i(row.get("c_Volume")),
                "bid": _f(row.get("c_Bid")),
                "ask": _f(row.get("c_Ask")),
            }
        )
        strike_bucket["pe"].update(
            {
                "ltp": _coalesce_price(row.get("p_Last"), row.get("p_Bid"), row.get("p_Ask")),
                "oi": _i(row.get("p_Openinterest")),
                "volume": _i(row.get("p_Volume")),
                "bid": _f(row.get("p_Bid")),
                "ask": _f(row.get("p_Ask")),
            }
        )
        strike_bucket["quality"]["is_partial"] = (
            strike_bucket["ce"]["ltp"] <= 0
            or strike_bucket["pe"]["ltp"] <= 0
        )

    expiry_blocks: list[dict[str, Any]] = []
    for expiry_key, bucket in sorted(grouped.items(), key=lambda item: item[0])[:include_expiries]:
        strikes = sorted(bucket["strikes"].values(), key=lambda row: float(row["strike"]))
        strikes = _window_strikes(strikes, _f(bucket.get("spot")), strike_count)
        total_call_oi = sum(_i((row.get("ce") or {}).get("oi")) for row in strikes)
        total_put_oi = sum(_i((row.get("pe") or {}).get("oi")) for row in strikes)
        quality = _chain_quality(strikes)
        expiry_dt = bucket["expiry_dt"]
        expiry_blocks.append(
            {
                "expiry": expiry_key,
                "expiry_ts": int(expiry_dt.timestamp()),
                "expiry_label": expiry_dt.strftime("%d %b %Y"),
                "spot": round(_f(bucket.get("spot")), 4),
                "total_call_oi": total_call_oi,
                "total_put_oi": total_put_oi,
                "pcr": round(total_put_oi / total_call_oi, 4) if total_call_oi > 0 else 0.0,
                "strikes": strikes,
                "quality": quality,
                "source_ts": fetched_at.isoformat(),
            }
        )

    if not expiry_blocks:
        raise HTTPException(status_code=404, detail=f"No option chain available for {underlying}")

    integrity = sum(float(block["quality"]["integrity_score"]) for block in expiry_blocks) / len(expiry_blocks)
    return {
        "underlying": underlying,
        "fetched_at": fetched_at.isoformat(),
        "data": {"expiryData": expiry_blocks},
        "quality": {
            "is_stale": False,
            "integrity_score": round(integrity, 2),
            "expiries_loaded": len(expiry_blocks),
        },
    }


async def _fetch_crypto_option_chain_public(
    underlying: str,
    strike_count: int,
    include_expiries: int,
) -> dict[str, Any]:
    pair = str(underlying).split(":", 1)[-1].upper()
    base = pair.replace("USDT", "").replace("USD", "")
    if base not in _DERIBIT_SUPPORTED:
        raise HTTPException(
            status_code=404,
            detail=f"Crypto option chain currently supported only for BTC and ETH. No chain for {underlying}.",
        )

    timeout = httpx.Timeout(10.0, connect=4.0)
    async with httpx.AsyncClient(timeout=timeout) as http:
        res = await http.get(
            "https://www.deribit.com/api/v2/public/get_book_summary_by_currency",
            params={"currency": base, "kind": "option"},
        )
        if res.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Deribit option chain fetch failed for {underlying}")
        payload = res.json() if res.content else {}

    rows = payload.get("result", []) if isinstance(payload, dict) else []
    if not rows:
        raise HTTPException(status_code=404, detail=f"No option chain available for {underlying}")

    fetched_at = datetime.now(tz=IST)
    grouped: dict[str, dict[str, Any]] = {}
    pattern = re.compile(r"^(?P<base>[A-Z]+)-(?P<expiry>\d{1,2}[A-Z]{3}\d{2})-(?P<strike>\d+(?:\.\d+)?)-(?P<side>[CP])$")

    for row in rows:
        if not isinstance(row, dict):
            continue
        instrument = str(row.get("instrument_name") or "").upper()
        match = pattern.match(instrument)
        if match is None:
            continue
        try:
            expiry_dt = datetime.strptime(match.group("expiry"), "%d%b%y").replace(tzinfo=IST)
        except ValueError:
            continue
        strike = _f(match.group("strike"))
        if strike <= 0:
            continue
        side_key = "ce" if match.group("side") == "C" else "pe"
        expiry_key = expiry_dt.strftime("%Y-%m-%d")
        expiry_bucket = grouped.setdefault(
            expiry_key,
            {
                "expiry_dt": expiry_dt,
                "spot": 0.0,
                "strikes": {},
            },
        )
        expiry_bucket["spot"] = max(_f(expiry_bucket.get("spot")), _f(row.get("underlying_price")))
        strike_bucket = expiry_bucket["strikes"].setdefault(
            strike,
            {
                "strike": strike,
                "ce": {
                    "symbol": f"CRYPTO:{base}-{match.group('expiry')}-{int(strike) if strike.is_integer() else strike}-C",
                    "ltp": 0.0,
                    "oi": 0,
                    "oich": 0,
                    "prev_oi": 0,
                    "iv": 0.0,
                    "volume": 0,
                    "bid": 0.0,
                    "ask": 0.0,
                    "delta": None,
                    "gamma": None,
                    "theta": None,
                    "vega": None,
                },
                "pe": {
                    "symbol": f"CRYPTO:{base}-{match.group('expiry')}-{int(strike) if strike.is_integer() else strike}-P",
                    "ltp": 0.0,
                    "oi": 0,
                    "oich": 0,
                    "prev_oi": 0,
                    "iv": 0.0,
                    "volume": 0,
                    "bid": 0.0,
                    "ask": 0.0,
                    "delta": None,
                    "gamma": None,
                    "theta": None,
                    "vega": None,
                },
                "quality": {"is_partial": False},
            },
        )
        strike_bucket[side_key].update(
            {
                "symbol": f"CRYPTO:{instrument}",
                "ltp": _coalesce_price(row.get("last"), row.get("bid_price"), row.get("ask_price")),
                "oi": _i(row.get("open_interest")),
                "volume": _i(row.get("volume_usd") or row.get("volume")),
                "bid": _f(row.get("bid_price")),
                "ask": _f(row.get("ask_price")),
                "iv": _f(row.get("mark_iv")),
            }
        )
        strike_bucket["quality"]["is_partial"] = (
            strike_bucket["ce"]["ltp"] <= 0
            or strike_bucket["pe"]["ltp"] <= 0
        )

    expiry_blocks: list[dict[str, Any]] = []
    for expiry_key, bucket in sorted(grouped.items(), key=lambda item: item[0])[:include_expiries]:
        strikes = sorted(bucket["strikes"].values(), key=lambda row: float(row["strike"]))
        strikes = _window_strikes(strikes, _f(bucket.get("spot")), strike_count)
        total_call_oi = sum(_i((row.get("ce") or {}).get("oi")) for row in strikes)
        total_put_oi = sum(_i((row.get("pe") or {}).get("oi")) for row in strikes)
        quality = _chain_quality(strikes)
        expiry_dt = bucket["expiry_dt"]
        expiry_blocks.append(
            {
                "expiry": expiry_key,
                "expiry_ts": int(expiry_dt.timestamp()),
                "expiry_label": expiry_dt.strftime("%d %b %Y"),
                "spot": round(_f(bucket.get("spot")), 4),
                "total_call_oi": total_call_oi,
                "total_put_oi": total_put_oi,
                "pcr": round(total_put_oi / total_call_oi, 4) if total_call_oi > 0 else 0.0,
                "strikes": strikes,
                "quality": quality,
                "source_ts": fetched_at.isoformat(),
            }
        )

    if not expiry_blocks:
        raise HTTPException(status_code=404, detail=f"No option chain available for {underlying}")

    integrity = sum(float(block["quality"]["integrity_score"]) for block in expiry_blocks) / len(expiry_blocks)
    return {
        "underlying": underlying,
        "fetched_at": fetched_at.isoformat(),
        "data": {"expiryData": expiry_blocks},
        "quality": {
            "is_stale": False,
            "integrity_score": round(integrity, 2),
            "expiries_loaded": len(expiry_blocks),
        },
    }


def _normalize_iv(iv_raw: Any) -> float:
    try:
        iv = float(iv_raw)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(iv) or iv <= 0:
        return 0.0
    # Some vendors provide IV in percent (e.g. 12.5); normalize to decimal.
    if iv > 1.0:
        iv /= 100.0
    # Clamp outliers so downstream Greeks stay numerically stable.
    return min(max(iv, 0.01), 3.0)


def _infer_iv(
    spot: float,
    strike: float,
    time_to_expiry: float,
    premium: Any,
    option_type: str,
) -> float:
    try:
        premium_value = float(premium)
    except (TypeError, ValueError):
        return 0.0
    if premium_value <= 0 or spot <= 0 or strike <= 0 or time_to_expiry <= 0:
        return 0.0
    iv = BlackScholes.calculate_iv(
        spot=spot,
        strike=strike,
        time_to_expiry=time_to_expiry,
        premium=premium_value,
        option_type=option_type,
    )
    return _normalize_iv(iv)


def _speed(
    spot: float,
    strike: float,
    time_to_expiry: float,
    volatility: float,
    option_type: str,
) -> float:
    """Numerical approximation of dGamma/dS."""
    if spot <= 0 or strike <= 0 or time_to_expiry <= 0 or volatility <= 0:
        return 0.0
    bump = max(spot * 0.005, 0.5)
    upper = BlackScholes.calculate_greeks(
        spot=spot + bump,
        strike=strike,
        time_to_expiry=time_to_expiry,
        volatility=volatility,
        option_type=option_type,
    ).gamma
    lower = BlackScholes.calculate_greeks(
        spot=max(spot - bump, 1e-6),
        strike=strike,
        time_to_expiry=time_to_expiry,
        volatility=volatility,
        option_type=option_type,
    ).gamma
    return (upper - lower) / (2.0 * bump)


def _convexity_points(exposures: list[dict[str, Any]]) -> list[dict[str, float]]:
    if len(exposures) < 3:
        return []

    out: list[dict[str, float]] = []
    for idx in range(1, len(exposures) - 1):
        x1 = float(exposures[idx - 1]["strike"])
        x2 = float(exposures[idx]["strike"])
        x3 = float(exposures[idx + 1]["strike"])
        y1 = float(exposures[idx - 1]["net_gamma_exposure"])
        y2 = float(exposures[idx]["net_gamma_exposure"])
        y3 = float(exposures[idx + 1]["net_gamma_exposure"])

        dx12 = x2 - x1
        dx23 = x3 - x2
        dx13 = x3 - x1
        if dx12 == 0 or dx23 == 0 or dx13 == 0:
            continue

        # Second derivative over non-uniform strike spacing.
        second_derivative = 2.0 * (((y3 - y2) / dx23) - ((y2 - y1) / dx12)) / dx13
        out.append({"strike": x2, "gamma_convexity": second_derivative})
    return out


@router.get("/options/expiries/{underlying}")
async def get_option_expiries(
    underlying: str,
    client: FyersClient = Depends(get_fyers_client),
    registry: InstrumentRegistryService = Depends(get_instrument_registry),
) -> dict[str, Any]:
    market = _underlying_market(underlying)
    if market == "US":
        chain = await _fetch_us_option_chain_public(underlying, strike_count=1, include_expiries=6)
        expiries = [
            {"label": block["expiry_label"], "expiry": block["expiry"], "expiry_ts": block["expiry_ts"]}
            for block in chain.get("data", {}).get("expiryData", [])
        ]
        return {"underlying": underlying, "expiries": expiries, "count": len(expiries)}
    if market == "CRYPTO":
        chain = await _fetch_crypto_option_chain_public(underlying, strike_count=1, include_expiries=6)
        expiries = [
            {"label": block["expiry_label"], "expiry": block["expiry"], "expiry_ts": block["expiry_ts"]}
            for block in chain.get("data", {}).get("expiryData", [])
        ]
        return {"underlying": underlying, "expiries": expiries, "count": len(expiries)}

    if not registry.get_cache():
        await asyncio.to_thread(registry.refresh, client)
    symbol = _resolve_underlying_symbol(underlying, registry)
    service = OptionsDataService(client)
    expiries = await asyncio.to_thread(service.get_expiries, symbol)
    return {"underlying": symbol, "expiries": expiries, "count": len(expiries)}


@router.get("/options/chain/{underlying}")
async def get_option_chain_canonical(
    underlying: str,
    expiry_ts: Optional[int] = Query(default=None),
    strike_count: int = Query(default=20, ge=1, le=50),
    include_expiries: int = Query(default=3, ge=1, le=6),
    persist: bool = Query(default=True, description="Persist snapshot into option_chain"),
    client: FyersClient = Depends(get_fyers_client),
    registry: InstrumentRegistryService = Depends(get_instrument_registry),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    market = _underlying_market(underlying)
    if market == "US":
        chain = await _fetch_us_option_chain_public(
            underlying=underlying,
            strike_count=strike_count,
            include_expiries=include_expiries,
        )
        if expiry_ts:
            filtered = [
                block for block in chain.get("data", {}).get("expiryData", [])
                if int(block.get("expiry_ts") or 0) == int(expiry_ts)
            ]
            if filtered:
                chain["data"]["expiryData"] = filtered
                chain["quality"]["expiries_loaded"] = len(filtered)
        chain["persisted_rows"] = 0
        return chain
    if market == "CRYPTO":
        chain = await _fetch_crypto_option_chain_public(
            underlying=underlying,
            strike_count=strike_count,
            include_expiries=include_expiries,
        )
        if expiry_ts:
            filtered = [
                block for block in chain.get("data", {}).get("expiryData", [])
                if int(block.get("expiry_ts") or 0) == int(expiry_ts)
            ]
            if filtered:
                chain["data"]["expiryData"] = filtered
                chain["quality"]["expiries_loaded"] = len(filtered)
        chain["persisted_rows"] = 0
        return chain

    if not registry.get_cache():
        await asyncio.to_thread(registry.refresh, client)
    symbol = _resolve_underlying_symbol(underlying, registry)
    service = OptionsDataService(client)
    chain = await asyncio.to_thread(
        service.get_canonical_chain,
        symbol,
        strike_count,
        expiry_ts,
        include_expiries,
    )
    if persist:
        rows = await service.persist_canonical_chain(db, chain)
        chain["persisted_rows"] = rows
    return chain


@router.get("/options/chain/{underlying}/history")
async def get_option_chain_oi_history_api(
    underlying: str,
    expiry: str = Query(..., description="Expiry date in YYYY-MM-DD"),
    strike: float = Query(...),
    side: str = Query(..., pattern="^(CE|PE|ce|pe)$"),
    limit: int = Query(default=500, ge=10, le=5000),
    client: FyersClient = Depends(get_fyers_client),
    registry: InstrumentRegistryService = Depends(get_instrument_registry),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if not registry.get_cache():
        await asyncio.to_thread(registry.refresh, client)
    symbol = _resolve_underlying_symbol(underlying, registry)
    service = OptionsDataService(client)
    history = await service.get_oi_history(
        session=db,
        underlying=symbol,
        expiry_iso=expiry,
        strike=strike,
        side=side,
        limit=limit,
    )
    return {
        "underlying": symbol,
        "expiry": expiry,
        "strike": strike,
        "side": side.upper(),
        "count": len(history),
        "history": history,
    }


@router.get("/options/charts/{option_symbol:path}")
async def get_option_chart_data(
    option_symbol: str,
    interval: str = Query(default="15"),
    days: int = Query(default=7, ge=1, le=180),
    client: FyersClient = Depends(get_fyers_client),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    market = _underlying_market(option_symbol)
    if market in {"US", "CRYPTO"}:
        data = await _fetch_public_option_chart(option_symbol, interval, days)
        return {
            "symbol": option_symbol,
            "interval": interval,
            "count": len(data),
            "candles": data,
        }

    collector = OptionOHLCCollector(client)
    end = datetime.now(tz=IST).replace(tzinfo=None)
    start = end - timedelta(days=days)
    candles = await get_option_ohlc_candles(db, option_symbol, interval, start, end, limit=5000)

    if len(candles) < 10:
        inserted = await collector.collect_and_store(
            session=db,
            symbol=option_symbol,
            resolution=interval,
            days_back=days,
        )
        logger.info("option_chart_backfill", symbol=option_symbol, inserted=inserted)
        candles = await get_option_ohlc_candles(db, option_symbol, interval, start, end, limit=5000)

    # Filter out zero-price candles (far-OTM ghost candles from backfill)
    data = [
        {
            "timestamp": c.timestamp.isoformat(),
            "open": float(c.open),
            "high": float(c.high),
            "low": float(c.low),
            "close": float(c.close),
            "volume": int(c.volume),
        }
        for c in candles
        if float(c.close) >= 0.5  # drop OTM ghost candles with near-zero price
    ]
    return {
        "symbol": option_symbol,
        "interval": interval,
        "count": len(data),
        "candles": data,
    }


@router.get("/options/straddle/{underlying}")
async def get_atm_straddle_chart(
    underlying: str,
    expiry_ts: Optional[int] = Query(default=None),
    strike: Optional[float] = Query(default=None),
    interval: str = Query(default="15"),
    days: int = Query(default=7, ge=1, le=60),
    client: FyersClient = Depends(get_fyers_client),
    registry: InstrumentRegistryService = Depends(get_instrument_registry),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    market = _underlying_market(underlying)
    if market in {"US", "CRYPTO"}:
        chain = await (
            _fetch_us_option_chain_public(underlying, strike_count=80, include_expiries=6)
            if market == "US"
            else _fetch_crypto_option_chain_public(underlying, strike_count=80, include_expiries=6)
        )
        expiry_block = _select_expiry_block(chain, expiry_ts)
        strike_value, ce_symbol, pe_symbol, straddle = await _fetch_public_straddle_candles(
            expiry_block.get("strikes", []),
            _f(expiry_block.get("spot")),
            strike,
            interval,
            days,
        )
        return {
            "underlying": underlying,
            "expiry": expiry_block.get("expiry"),
            "strike": strike_value,
            "interval": interval,
            "ce_symbol": ce_symbol,
            "pe_symbol": pe_symbol,
            "candles": straddle,
            "count": len(straddle),
        }

    if not registry.get_cache():
        await asyncio.to_thread(registry.refresh, client)
    symbol = _resolve_underlying_symbol(underlying, registry)
    service = OptionsDataService(client)
    chain = await asyncio.to_thread(service.get_canonical_chain, symbol, 12, expiry_ts, 1)
    expiry_block = _select_expiry_block(chain, expiry_ts)
    strike_value, ce_symbol, pe_symbol = _select_strike_row(
        expiry_block.get("strikes", []),
        _f(expiry_block.get("spot")),
        strike,
    )

    collector = OptionOHLCCollector(client)
    await collector.collect_and_store(db, ce_symbol, interval, days, symbol, expiry_block.get("expiry"), strike_value, "CE")
    await collector.collect_and_store(db, pe_symbol, interval, days, symbol, expiry_block.get("expiry"), strike_value, "PE")

    end = datetime.now(tz=IST).replace(tzinfo=None)
    start = end - timedelta(days=days)
    ce_candles = await get_option_ohlc_candles(db, ce_symbol, interval, start, end, limit=5000)
    pe_candles = await get_option_ohlc_candles(db, pe_symbol, interval, start, end, limit=5000)

    straddle = _merge_straddle_candles(
        [
            {
                "timestamp": ce.timestamp.isoformat(),
                "open": float(ce.open),
                "high": float(ce.high),
                "low": float(ce.low),
                "close": float(ce.close),
                "volume": int(ce.volume),
            }
            for ce in ce_candles
        ],
        [
            {
                "timestamp": pe.timestamp.isoformat(),
                "open": float(pe.open),
                "high": float(pe.high),
                "low": float(pe.low),
                "close": float(pe.close),
                "volume": int(pe.volume),
            }
            for pe in pe_candles
        ],
    )

    return {
        "underlying": symbol,
        "expiry": expiry_block.get("expiry"),
        "strike": strike_value,
        "interval": interval,
        "ce_symbol": ce_symbol,
        "pe_symbol": pe_symbol,
        "candles": straddle,
        "count": len(straddle),
    }


@router.get("/options/analytics/{underlying}")
async def get_options_analytics(
    underlying: str,
    expiry_ts: Optional[int] = Query(default=None),
    strike_count: int = Query(default=20, ge=5, le=50),
    client: FyersClient = Depends(get_fyers_client),
    registry: InstrumentRegistryService = Depends(get_instrument_registry),
) -> dict[str, Any]:
    if not registry.get_cache():
        await asyncio.to_thread(registry.refresh, client)
    symbol = _resolve_underlying_symbol(underlying, registry)
    service = OptionsDataService(client)
    chain = await asyncio.to_thread(
        service.get_canonical_chain,
        symbol,
        strike_count,
        expiry_ts,
        3,
    )
    expiry_rows = chain.get("data", {}).get("expiryData", [])
    if not expiry_rows:
        raise HTTPException(status_code=404, detail="No chain available for analytics")

    block = expiry_rows[0]
    if expiry_ts is not None:
        matched = next((e for e in expiry_rows if int(e.get("expiry_ts") or 0) == int(expiry_ts)), None)
        if matched:
            block = matched

    spot = float(block.get("spot") or 0)
    expiry_iso = str(block.get("expiry") or "")
    try:
        expiry_date = datetime.fromisoformat(expiry_iso).date()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid expiry format: {expiry_iso}") from exc
    days_to_expiry = max((expiry_date - datetime.now(tz=IST).date()).days, 1)
    tte = days_to_expiry / 365.0
    lot_size = _resolve_lot_size(symbol, registry)

    exposures: list[dict[str, Any]] = []
    oi_buildup: list[dict[str, Any]] = []
    iv_smile: list[dict[str, Any]] = []
    dex_profile: list[dict[str, Any]] = []
    total_gamma = 0.0
    total_delta = 0.0
    total_theta = 0.0
    total_vega = 0.0
    total_vanna = 0.0
    total_charm = 0.0
    total_vomma = 0.0
    total_speed = 0.0

    strikes = block.get("strikes", [])
    atm_iv_candidates: list[float] = []
    if strikes and spot > 0:
        atm_row = min(strikes, key=lambda row: abs(float(row.get("strike") or 0) - spot))
        for side_name in ("ce", "pe"):
            side = atm_row.get(side_name, {})
            iv_value = _normalize_iv(side.get("iv"))
            if iv_value <= 0:
                iv_value = _infer_iv(
                    spot=spot,
                    strike=float(atm_row.get("strike") or 0),
                    time_to_expiry=tte,
                    premium=side.get("ltp"),
                    option_type=side_name.upper(),
                )
            if iv_value > 0:
                atm_iv_candidates.append(iv_value)
    fallback_iv = float(sum(atm_iv_candidates) / len(atm_iv_candidates)) if atm_iv_candidates else 0.2

    for row in strikes:
        strike_value = float(row["strike"])
        ce = row.get("ce", {})
        pe = row.get("pe", {})

        ce_gex = 0.0
        pe_gex = 0.0
        ce_dex = 0.0
        pe_dex = 0.0
        ce_thex = 0.0
        pe_thex = 0.0
        ce_vex = 0.0
        pe_vex = 0.0
        ce_vanna = 0.0
        pe_vanna = 0.0
        ce_charm = 0.0
        pe_charm = 0.0
        ce_vomma = 0.0
        pe_vomma = 0.0
        ce_speed = 0.0
        pe_speed = 0.0
        ce_iv = _normalize_iv(ce.get("iv"))
        pe_iv = _normalize_iv(pe.get("iv"))

        if ce_iv <= 0:
            ce_iv = _infer_iv(spot, strike_value, tte, ce.get("ltp"), option_type="CE")
        if pe_iv <= 0:
            pe_iv = _infer_iv(spot, strike_value, tte, pe.get("ltp"), option_type="PE")

        if ce_iv <= 0:
            ce_iv = fallback_iv
        if pe_iv <= 0:
            pe_iv = fallback_iv

        if ce.get("ltp", 0) > 0 and ce.get("oi", 0) > 0:
            ce_g = BlackScholes.calculate_greeks(spot, strike_value, tte, ce_iv, option_type="CE")
            ce_oi_lots = float(ce["oi"]) * lot_size
            ce_gex = ce_g.gamma * ce_oi_lots * (spot * spot) * 0.01
            ce_dex = ce_g.delta * ce_oi_lots
            ce_thex = ce_g.theta * ce_oi_lots
            ce_vex = ce_g.vega * ce_oi_lots
            ce_vanna = float(ce_g.vanna or 0.0) * ce_oi_lots
            ce_charm = float(ce_g.charm or 0.0) * ce_oi_lots
            ce_vomma = float(ce_g.vomma or 0.0) * ce_oi_lots
            ce_speed = _speed(spot, strike_value, tte, ce_iv, option_type="CE") * ce_oi_lots

        if pe.get("ltp", 0) > 0 and pe.get("oi", 0) > 0:
            pe_g = BlackScholes.calculate_greeks(spot, strike_value, tte, pe_iv, option_type="PE")
            pe_oi_lots = float(pe["oi"]) * lot_size
            pe_gex = pe_g.gamma * pe_oi_lots * (spot * spot) * 0.01
            pe_dex = pe_g.delta * pe_oi_lots
            pe_thex = pe_g.theta * pe_oi_lots
            pe_vex = pe_g.vega * pe_oi_lots
            pe_vanna = float(pe_g.vanna or 0.0) * pe_oi_lots
            pe_charm = float(pe_g.charm or 0.0) * pe_oi_lots
            pe_vomma = float(pe_g.vomma or 0.0) * pe_oi_lots
            pe_speed = _speed(spot, strike_value, tte, pe_iv, option_type="PE") * pe_oi_lots

        net_gamma = ce_gex + pe_gex
        net_delta = ce_dex + pe_dex
        net_theta = ce_thex + pe_thex
        net_vega = ce_vex + pe_vex
        net_vanna = ce_vanna + pe_vanna
        net_charm = ce_charm + pe_charm
        net_vomma = ce_vomma + pe_vomma
        net_speed = ce_speed + pe_speed
        ce_oi = float(ce.get("oi") or 0)
        pe_oi = float(pe.get("oi") or 0)
        ce_oich = float(ce.get("oich") or 0)
        pe_oich = float(pe.get("oich") or 0)

        buildup = "Mixed"
        if ce_oich > 0 and pe_oich > 0:
            buildup = "Long Build-up"
        elif ce_oich < 0 and pe_oich < 0:
            buildup = "Short Covering"
        elif ce_oich > 0 and pe_oich <= 0:
            buildup = "Call Build-up"
        elif pe_oich > 0 and ce_oich <= 0:
            buildup = "Put Build-up"

        exposures.append(
            {
                "strike": strike_value,
                "ce_gamma_exposure": ce_gex,
                "pe_gamma_exposure": pe_gex,
                "net_gamma_exposure": net_gamma,
                "ce_delta_exposure": ce_dex,
                "pe_delta_exposure": pe_dex,
                "net_delta_exposure": net_delta,
                "net_theta_exposure": net_theta,
                "net_vega_exposure": net_vega,
                "net_vanna_exposure": net_vanna,
                "net_charm_exposure": net_charm,
                "net_vomma_exposure": net_vomma,
                "net_speed_exposure": net_speed,
            }
        )
        dex_profile.append(
            {
                "strike": strike_value,
                "ce_delta_exposure": ce_dex,
                "pe_delta_exposure": pe_dex,
                "net_delta_exposure": net_delta,
            }
        )
        oi_buildup.append(
            {
                "strike": strike_value,
                "ce_oi": ce_oi,
                "pe_oi": pe_oi,
                "ce_oich": ce_oich,
                "pe_oich": pe_oich,
                "net_oich": ce_oich + pe_oich,
                "label": buildup,
            }
        )
        if ce_iv > 0 or pe_iv > 0:
            iv_smile.append(
                {
                    "strike": strike_value,
                    "ce_iv": ce_iv,
                    "pe_iv": pe_iv,
                    "ce_iv_pct": ce_iv * 100.0 if ce_iv > 0 else 0.0,
                    "pe_iv_pct": pe_iv * 100.0 if pe_iv > 0 else 0.0,
                }
            )
        total_gamma += net_gamma
        total_delta += net_delta
        total_theta += net_theta
        total_vega += net_vega
        total_vanna += net_vanna
        total_charm += net_charm
        total_vomma += net_vomma
        total_speed += net_speed

    exposures = sorted(exposures, key=lambda e: e["strike"])
    dex_profile = sorted(dex_profile, key=lambda e: e["strike"])
    iv_smile = sorted(iv_smile, key=lambda e: e["strike"])
    convexity = _convexity_points(exposures)

    max_abs_gamma = max((abs(e["net_gamma_exposure"]) for e in exposures), default=0.0) or 1.0
    gex_heatmap = [
        {
            "strike": e["strike"],
            "net_gamma_exposure": e["net_gamma_exposure"],
            "intensity": e["net_gamma_exposure"] / max_abs_gamma,
        }
        for e in exposures
    ]

    term_source = expiry_rows
    if expiry_ts is not None and len(expiry_rows) <= 1:
        # For explicit expiry analytics, still expose near/next/far context.
        full_chain = await asyncio.to_thread(service.get_canonical_chain, symbol, strike_count, None, 3)
        full_rows = full_chain.get("data", {}).get("expiryData", [])
        if full_rows:
            term_source = full_rows

    term_structure: list[dict[str, Any]] = []
    for exp in term_source:
        exp_spot = float(exp.get("spot") or 0)
        exp_expiry = str(exp.get("expiry") or "")
        if not exp_expiry:
            continue
        exp_date = datetime.fromisoformat(exp_expiry).date()
        exp_dte = max((exp_date - datetime.now(tz=IST).date()).days, 0)
        strikes = exp.get("strikes", [])
        atm_straddle = 0.0
        if strikes and exp_spot > 0:
            atm_row = min(strikes, key=lambda s: abs(float(s.get("strike") or 0) - exp_spot))
            atm_straddle = float(atm_row.get("ce", {}).get("ltp") or 0) + float(
                atm_row.get("pe", {}).get("ltp") or 0
            )
        term_structure.append(
            {
                "expiry": exp_expiry,
                "expiry_ts": int(exp.get("expiry_ts") or 0),
                "days_to_expiry": exp_dte,
                "pcr": float(exp.get("pcr") or 0),
                "total_call_oi": int(exp.get("total_call_oi") or 0),
                "total_put_oi": int(exp.get("total_put_oi") or 0),
                "atm_straddle": atm_straddle,
                "integrity_score": float(exp.get("quality", {}).get("integrity_score") or 0),
            }
        )
    term_structure.sort(key=lambda row: row.get("expiry_ts", 0))

    return {
        "underlying": symbol,
        "expiry": expiry_iso,
        "spot": spot,
        "lot_size": lot_size,
        "days_to_expiry": days_to_expiry,
        "total_pcr": float(block.get("pcr") or 0),
        "total_net_gex": total_gamma,
        "total_net_dex": total_delta,
        "total_net_gamma_exposure": total_gamma,
        "total_net_delta_exposure": total_delta,
        "total_net_theta_exposure": total_theta,
        "total_net_vega_exposure": total_vega,
        "total_net_vanna_exposure": total_vanna,
        "total_net_charm_exposure": total_charm,
        "total_net_vomma_exposure": total_vomma,
        "total_net_speed_exposure": total_speed,
        "exposures_by_strike": exposures,
        "dex_profile": dex_profile,
        "oi_buildup": oi_buildup,
        "iv_smile": iv_smile,
        "term_structure": term_structure,
        "gex_heatmap": gex_heatmap,
        "gamma_convexity": convexity,
    }


@router.post("/options/symbols/refresh")
async def refresh_instruments(
    client: FyersClient = Depends(get_fyers_client),
    registry: InstrumentRegistryService = Depends(get_instrument_registry),
) -> dict[str, Any]:
    refreshed = await asyncio.to_thread(registry.refresh, client)
    return {
        "success": True,
        "refreshed_at": datetime.now(tz=IST).isoformat(),
        "count": len(refreshed),
        "instruments": [item.to_dict() for item in refreshed.values()],
    }


@router.get("/system/data-quality")
async def get_data_quality(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    now = datetime.now(tz=IST).replace(tzinfo=None)
    summary_stmt = (
        select(
            OptionChain.underlying,
            func.max(OptionChain.timestamp).label("latest_ts"),
            func.avg(OptionChain.integrity_score).label("avg_integrity"),
            func.count().label("rows"),
        )
        .group_by(OptionChain.underlying)
    )
    result = await db.execute(summary_stmt)
    rows = result.all()

    quality = []
    for row in rows:
        latest_ts = row.latest_ts
        age_sec = (now - latest_ts).total_seconds() if latest_ts else None
        quality.append(
            {
                "underlying": row.underlying,
                "latest_snapshot": latest_ts.isoformat() if latest_ts else None,
                "snapshot_age_seconds": age_sec,
                "is_stale": bool(age_sec is not None and age_sec > 120),
                "average_integrity": float(row.avg_integrity or 0),
                "rows": int(row.rows or 0),
            }
        )
    return {"timestamp": now.isoformat(), "underlyings": quality}
