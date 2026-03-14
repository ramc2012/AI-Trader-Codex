"""AI Trading Agent control endpoints.

Start, stop, pause, resume the autonomous trading agent and
retrieve status, events, and configuration.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import inspect
import math
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
import pandas as pd
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.analysis.fractal_profile import build_daily_fractal_context
from src.analysis.indicators import ATR, BollingerBands, EMA, MACD, RSI, Supertrend
from src.analysis.tpo_engine import compute_tpo_profile
from src.agent.trading_agent import AgentConfig, AgentState, STRATEGY_REGISTRY
from src.agent.events import AgentEvent, AgentEventType
from src.api.dependencies import (
    get_agent_event_bus,
    get_db,
    get_fyers_client,
    get_fractal_scan_notifier,
    get_ohlc_cache,          # used for simulate
    get_order_manager,
    get_position_manager,
    get_risk_manager,
    get_telegram_notifier,
    get_trading_agent,
    reset_trading_agent,
)
from src.api.routes.trading import _build_currency_aware_portfolio, _refresh_open_position_marks
from src.api.schemas import AgentConfigRequest, AgentEventResponse, AgentStatusResponse
from src.config.settings import get_settings
from src.database.operations import get_ohlc_candles
from src.utils.logger import get_logger
from src.config.constants import DEFAULT_AGENT_NSE_SYMBOLS

logger = get_logger(__name__)

router = APIRouter(prefix="/agent", tags=["AI Agent"])


def _total_allocated_capital_inr(body: AgentConfigRequest) -> float:
    usd_inr_rate = float(get_settings().usd_inr_reference_rate)
    return round(
        float(body.india_capital) + (float(body.us_capital) + float(body.crypto_capital)) * usd_inr_rate,
        2,
    )


def _sync_risk_manager_config(body: AgentConfigRequest) -> None:
    risk_manager = get_risk_manager()
    usd_inr_rate = float(get_settings().usd_inr_reference_rate)
    total_capital_inr = _total_allocated_capital_inr(body)
    india_cap_inr = float(body.india_capital)
    us_cap_inr = float(body.us_capital) * usd_inr_rate
    crypto_cap_inr = float(body.crypto_capital) * usd_inr_rate
    max_position_size_inr = max(
        india_cap_inr * (float(body.india_max_instrument_pct) / 100.0),
        us_cap_inr * (float(body.us_max_instrument_pct) / 100.0),
        crypto_cap_inr * (float(body.crypto_max_instrument_pct) / 100.0),
        1.0,
    )
    risk_manager.config.capital = total_capital_inr
    risk_manager.config.max_daily_loss_pct = max(float(body.max_daily_loss_pct), 0.0) / 100.0
    risk_manager.config.max_daily_loss = total_capital_inr * risk_manager.config.max_daily_loss_pct
    risk_manager.config.max_position_size = max_position_size_inr
    risk_manager.config.max_concentration_pct = max_position_size_inr / max(total_capital_inr, 1.0)


def _json_safe(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    elif hasattr(value, "item") and not isinstance(value, (str, bytes, bytearray)):
        try:
            value = value.item()
        except Exception:
            pass

    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, float):
        return round(value, 4) if math.isfinite(value) else None
    if isinstance(value, (int, str, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _normalize_timestamp_key(value: Any) -> datetime | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    ts = parsed.to_pydatetime()
    if ts.tzinfo is None or ts.tzinfo.utcoffset(ts) is None:
        return ts
    return ts.astimezone(timezone.utc).replace(tzinfo=None)


def _last_valid(series: pd.Series) -> float | None:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return None
    value = float(clean.iloc[-1])
    return round(value, 4) if math.isfinite(value) else None


def _serialize_bar(row: pd.Series) -> dict[str, Any]:
    return {
        "timestamp": _json_safe(row.get("timestamp")),
        "open": _json_safe(row.get("open")),
        "high": _json_safe(row.get("high")),
        "low": _json_safe(row.get("low")),
        "close": _json_safe(row.get("close")),
        "volume": _json_safe(row.get("volume", 0)),
    }


def _prepare_inspection_frame(
    df: pd.DataFrame,
    symbol: str,
    lookback_bars: int,
) -> pd.DataFrame:
    frame = df.copy()
    if "timestamp" not in frame.columns:
        frame = frame.reset_index()
        if "timestamp" not in frame.columns and "index" in frame.columns:
            frame = frame.rename(columns={"index": "timestamp"})

    frame["timestamp"] = pd.to_datetime(frame.get("timestamp"), errors="coerce")
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame.get(column), errors="coerce")
    if "volume" in frame.columns:
        frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce").fillna(0.0)
    else:
        frame["volume"] = 0.0

    frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close"])
    frame = frame.sort_values("timestamp").tail(max(int(lookback_bars), 1)).reset_index(drop=True)
    frame["symbol"] = symbol
    return frame


def _history_lookback_days(timeframe: str) -> int:
    return {
        "1": 14,
        "3": 21,
        "5": 30,
        "15": 60,
        "30": 90,
        "60": 180,
        "D": 730,
        "W": 1825,
        "M": 3650,
    }.get(str(timeframe or "").strip().upper(), 90)


def _inspection_timeframe_candidates(agent: Any, requested: str) -> list[str]:
    ordered: list[str] = []
    for timeframe in [
        requested,
        *agent.get_execution_timeframes(),
        *agent.get_reference_timeframes(),
        "D",
    ]:
        token = str(timeframe or "").strip().upper()
        if token and token not in ordered:
            ordered.append(token)
    return ordered


def _db_rows_to_frame(rows: list[Any], symbol: str) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "timestamp": row.timestamp,
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": int(row.volume),
                "symbol": symbol,
            }
            for row in rows
        ]
    )


async def _load_inspection_frame(
    agent: Any,
    db: AsyncSession,
    symbol: str,
    requested_timeframe: str,
    lookback_bars: int,
) -> tuple[pd.DataFrame, str, dict[str, Any]]:
    requested_token = str(requested_timeframe or "").strip().upper()
    requested_error: str | None = None
    candidates = _inspection_timeframe_candidates(agent, requested_token)
    stale_requested_payload: tuple[pd.DataFrame, str, dict[str, Any]] | None = None

    for candidate in candidates:
        frame_raw = await agent._fetch_market_data(symbol, timeframe=candidate)
        if frame_raw is not None and not frame_raw.empty:
            frame = _prepare_inspection_frame(frame_raw, symbol, lookback_bars)
            if not frame.empty:
                last_ts = pd.to_datetime(frame["timestamp"].iloc[-1], errors="coerce")
                payload = (
                    frame,
                    candidate,
                    {
                        "fallback_used": candidate != requested_token,
                        "source": "live_fetch",
                        "requested_timeframe": requested_token,
                        "resolved_timeframe": candidate,
                        "reason": None if candidate == requested_token else "requested_timeframe_unavailable",
                        "last_session_date": None if pd.isna(last_ts) else last_ts.date().isoformat(),
                    },
                )
                fresh, _ = agent._data_freshness(frame, candidate)
                if candidate == requested_token and not fresh:
                    stale_requested_payload = payload
                    continue
                return payload
        elif candidate == requested_token:
            requested_error = f"No market data available for {symbol} on {requested_token}."

    if stale_requested_payload is not None:
        return stale_requested_payload

    now = datetime.now(tz=timezone.utc)
    for candidate in candidates:
        window_days = _history_lookback_days(candidate)
        start = (now - timedelta(days=window_days)).replace(tzinfo=None)
        end = now.replace(tzinfo=None)
        rows = await get_ohlc_candles(
            db,
            symbol,
            candidate,
            start,
            end,
            limit=max(int(lookback_bars) * 3, 600),
        )
        frame = _prepare_inspection_frame(_db_rows_to_frame(list(rows), symbol), symbol, lookback_bars)
        if frame.empty:
            continue
        last_ts = pd.to_datetime(frame["timestamp"].iloc[-1], errors="coerce")
        return (
            frame,
            candidate,
            {
                "fallback_used": True,
                "source": "database_last_session",
                "requested_timeframe": requested_token,
                "resolved_timeframe": candidate,
                "reason": "using_last_tradable_session",
                "last_session_date": None if pd.isna(last_ts) else last_ts.date().isoformat(),
            },
        )

    raise HTTPException(
        status_code=404,
        detail=requested_error or f"No historical market data available for {symbol}.",
    )


def _serialize_strategy_params(strategy: Any) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for key, value in vars(strategy).items():
        if key.startswith("_") or callable(value):
            continue
        params[key] = _json_safe(value)
    return params


def _strategy_algorithm_summary(strategy_name: str) -> str:
    cls = STRATEGY_REGISTRY.get(strategy_name)
    if cls is None:
        return ""
    doc = inspect.getdoc(cls) or ""
    if not doc:
        return ""
    return " ".join(part.strip() for part in doc.splitlines() if part.strip())


def _strategy_field_type(annotation: Any, value: Any) -> str:
    if annotation is bool or isinstance(value, bool):
        return "boolean"
    if annotation is int or (isinstance(value, int) and not isinstance(value, bool)):
        return "integer"
    if annotation is float or isinstance(value, float):
        return "number"
    return "text"


def _strategy_constructor_params(strategy_name: str, strategy: Any) -> dict[str, Any]:
    cls = STRATEGY_REGISTRY.get(strategy_name)
    if cls is None:
        return {}

    signature = inspect.signature(cls.__init__)
    params: dict[str, Any] = {}
    for param_name, parameter in signature.parameters.items():
        if param_name == "self":
            continue
        if hasattr(strategy, param_name):
            params[param_name] = getattr(strategy, param_name)
        elif parameter.default is not inspect.Signature.empty:
            params[param_name] = parameter.default
    return params


def _strategy_settings_schema(strategy_name: str, strategy: Any) -> list[dict[str, Any]]:
    cls = STRATEGY_REGISTRY.get(strategy_name)
    if cls is None:
        return []

    signature = inspect.signature(cls.__init__)
    current_params = _strategy_constructor_params(strategy_name, strategy)
    fields: list[dict[str, Any]] = []
    for param_name, parameter in signature.parameters.items():
        if param_name == "self":
            continue
        default = None if parameter.default is inspect.Signature.empty else parameter.default
        current_value = current_params.get(param_name, default)
        fields.append(
            {
                "name": param_name,
                "type": _strategy_field_type(parameter.annotation, current_value),
                "required": parameter.default is inspect.Signature.empty,
                "default": _json_safe(default),
                "value": _json_safe(current_value),
            }
        )
    return fields


def _coerce_strategy_param(name: str, value: Any, field_type: str) -> Any:
    if field_type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off"}:
                return False
        if isinstance(value, (int, float)):
            return bool(value)
        raise HTTPException(status_code=400, detail=f"Invalid boolean value for '{name}'.")

    if field_type == "integer":
        if isinstance(value, bool):
            raise HTTPException(status_code=400, detail=f"Invalid integer value for '{name}'.")
        try:
            return int(float(value))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"Invalid integer value for '{name}'.") from None

    if field_type == "number":
        if isinstance(value, bool):
            raise HTTPException(status_code=400, detail=f"Invalid number value for '{name}'.")
        try:
            return float(value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"Invalid number value for '{name}'.") from None

    if value is None:
        raise HTTPException(status_code=400, detail=f"'{name}' cannot be empty.")
    return str(value)


def _strategy_min_bars(strategy: Any) -> int:
    name = getattr(strategy, "name", "")
    if name == "EMA_Crossover":
        return int(getattr(strategy, "slow_period", 21)) + 1
    if name == "RSI_Reversal":
        return int(getattr(strategy, "rsi_period", 14)) + 2
    if name == "MACD_RSI":
        return int(getattr(strategy, "macd_slow", 26)) + int(getattr(strategy, "macd_signal", 9)) + 1
    if name == "Bollinger_MeanReversion":
        return max(
            int(getattr(strategy, "bb_period", 20)),
            int(getattr(strategy, "rsi_period", 14)),
            int(getattr(strategy, "atr_period", 14)),
        ) + 2
    if name == "Supertrend_Breakout":
        return max(int(getattr(strategy, "st_period", 10)), int(getattr(strategy, "atr_period", 14))) + 2
    if name == "MP_OrderFlow_Breakout":
        return max(int(getattr(strategy, "atr_period", 14)) + 5, int(getattr(strategy, "profile_lookback", 90)) // 2)
    if name == "Fractal_Profile_Breakout":
        return int(getattr(strategy, "min_bars", 60))
    if name == "ML_Ensemble":
        return 50
    return 30


def _common_indicator_snapshot(agent: Any, frame: pd.DataFrame) -> dict[str, Any]:
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    volume = frame["volume"].astype(float)
    macd_df = MACD(fast_period=12, slow_period=26, signal_period=9).calculate(close)
    trend, _, ema20 = agent._infer_trend(frame)

    return {
        "close": _last_valid(close),
        "ema_9": _last_valid(EMA(period=9).calculate(close)),
        "ema_21": _last_valid(EMA(period=21).calculate(close)),
        "ema_50": _last_valid(EMA(period=50).calculate(close)),
        "ema_20_bias": round(ema20, 4) if math.isfinite(ema20) else None,
        "rsi_14": _last_valid(RSI(period=14).calculate(close)),
        "atr_14": _last_valid(ATR(period=14).calculate(close, high=high, low=low)),
        "macd": _last_valid(macd_df["macd"]),
        "macd_signal": _last_valid(macd_df["signal"]),
        "macd_histogram": _last_valid(macd_df["macd"] - macd_df["signal"]),
        "avg_volume_20": _last_valid(volume.rolling(window=20).mean()),
        "trend": trend,
    }


async def _reference_bias_snapshot(agent: Any, symbol: str) -> dict[str, Any]:
    timeframes: dict[str, Any] = {}
    bullish_votes = 0
    bearish_votes = 0

    for timeframe in agent.get_reference_timeframes():
        df = await agent._fetch_market_data(symbol, timeframe=timeframe)
        if df is None or df.empty:
            timeframes[timeframe] = {"trend": "missing"}
            continue

        frame = _prepare_inspection_frame(df, symbol, 300)
        fresh, freshness = agent._data_freshness(frame, timeframe)
        trend, close, ema20 = agent._infer_trend(frame)
        payload = {
            "trend": trend if fresh else "stale",
            "fresh": fresh,
            "close": round(close, 4) if math.isfinite(close) else None,
            "ema20": round(ema20, 4) if math.isfinite(ema20) else None,
            **_json_safe(freshness),
        }
        timeframes[timeframe] = payload
        if fresh:
            if trend == "bullish":
                bullish_votes += 1
            elif trend == "bearish":
                bearish_votes += 1

    dominant_trend = "neutral"
    if bullish_votes > bearish_votes:
        dominant_trend = "bullish"
    elif bearish_votes > bullish_votes:
        dominant_trend = "bearish"

    return {
        "timeframes": timeframes,
        "bullish_votes": bullish_votes,
        "bearish_votes": bearish_votes,
        "dominant_trend": dominant_trend,
    }


def _serialize_signal(signal: Any, frame: pd.DataFrame) -> dict[str, Any]:
    signal_key = _normalize_timestamp_key(getattr(signal, "timestamp", None))
    latest_key = _normalize_timestamp_key(frame["timestamp"].iloc[-1]) if not frame.empty else None
    bars_ago: int | None = None
    if signal_key is not None:
        matches = [
            idx
            for idx, value in enumerate(frame["timestamp"])
            if _normalize_timestamp_key(value) == signal_key
        ]
        if matches:
            bars_ago = len(frame) - 1 - matches[-1]

    return {
        "timestamp": _json_safe(getattr(signal, "timestamp", None)),
        "signal_type": getattr(getattr(signal, "signal_type", None), "value", None),
        "strength": getattr(getattr(signal, "strength", None), "value", None),
        "price": _json_safe(getattr(signal, "price", None)),
        "stop_loss": _json_safe(getattr(signal, "stop_loss", None)),
        "target": _json_safe(getattr(signal, "target", None)),
        "metadata": _json_safe(getattr(signal, "metadata", {})),
        "on_latest_bar": signal_key is not None and latest_key is not None and signal_key == latest_key,
        "bars_ago": bars_ago,
    }


def _ema_snapshot(strategy: Any, frame: pd.DataFrame) -> dict[str, Any]:
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    fast = EMA(period=int(strategy.fast_period)).calculate(close)
    slow = EMA(period=int(strategy.slow_period)).calculate(close)
    atr = ATR(period=int(strategy.atr_period)).calculate(close, high=high, low=low)
    fast_now = _last_valid(fast)
    slow_now = _last_valid(slow)

    setup = "flat"
    if fast_now is not None and slow_now is not None:
        if fast_now > slow_now:
            setup = "bullish"
        elif fast_now < slow_now:
            setup = "bearish"

    return {
        "fast_ema": fast_now,
        "slow_ema": slow_now,
        "ema_spread": None if fast_now is None or slow_now is None else round(fast_now - slow_now, 4),
        "atr": _last_valid(atr),
        "setup": setup,
    }


def _rsi_snapshot(strategy: Any, frame: pd.DataFrame) -> dict[str, Any]:
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    rsi = RSI(period=int(strategy.rsi_period)).calculate(close)
    atr = ATR(period=int(strategy.atr_period)).calculate(close, high=high, low=low)
    clean_rsi = pd.to_numeric(rsi, errors="coerce").dropna()
    current = float(clean_rsi.iloc[-1]) if not clean_rsi.empty else None
    previous = float(clean_rsi.iloc[-2]) if len(clean_rsi) >= 2 else None
    zone = "neutral"
    if current is not None:
        if current <= float(strategy.oversold):
            zone = "oversold"
        elif current >= float(strategy.overbought):
            zone = "overbought"

    return {
        "rsi": _json_safe(current),
        "prev_rsi": _json_safe(previous),
        "atr": _last_valid(atr),
        "zone": zone,
    }


def _macd_snapshot(strategy: Any, frame: pd.DataFrame) -> dict[str, Any]:
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    macd_df = MACD(
        fast_period=int(strategy.macd_fast),
        slow_period=int(strategy.macd_slow),
        signal_period=int(strategy.macd_signal),
    ).calculate(close)
    rsi = RSI(period=int(strategy.rsi_period)).calculate(close)
    atr = ATR(period=int(strategy.atr_period)).calculate(close, high=high, low=low)
    macd_value = _last_valid(macd_df["macd"])
    signal_value = _last_valid(macd_df["signal"])
    histogram = None
    if macd_value is not None and signal_value is not None:
        histogram = round(macd_value - signal_value, 4)

    return {
        "macd": macd_value,
        "macd_signal": signal_value,
        "histogram": histogram,
        "rsi": _last_valid(rsi),
        "atr": _last_valid(atr),
        "bias": "bullish" if histogram and histogram > 0 else "bearish" if histogram and histogram < 0 else "neutral",
    }


def _bollinger_snapshot(strategy: Any, frame: pd.DataFrame) -> dict[str, Any]:
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    bands = BollingerBands(period=int(strategy.bb_period), std_dev=float(strategy.bb_std)).calculate(close)
    rsi = RSI(period=int(strategy.rsi_period)).calculate(close)
    atr = ATR(period=int(strategy.atr_period)).calculate(close, high=high, low=low)
    upper = _last_valid(bands["upper"])
    lower = _last_valid(bands["lower"])
    middle = _last_valid(bands["middle"])
    price = _last_valid(close)
    band_width_pct = None
    if upper is not None and lower is not None and middle not in (None, 0):
        band_width_pct = round(((upper - lower) / middle) * 100.0, 4)

    zone = "inside_bands"
    if price is not None and upper is not None and price >= upper:
        zone = "above_upper_band"
    elif price is not None and lower is not None and price <= lower:
        zone = "below_lower_band"

    return {
        "upper_band": upper,
        "middle_band": middle,
        "lower_band": lower,
        "rsi": _last_valid(rsi),
        "atr": _last_valid(atr),
        "band_width_pct": band_width_pct,
        "zone": zone,
    }


def _supertrend_snapshot(strategy: Any, frame: pd.DataFrame) -> dict[str, Any]:
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    supertrend_df = Supertrend(
        period=int(strategy.st_period),
        multiplier=float(strategy.st_multiplier),
    ).calculate(frame)
    atr = ATR(period=int(strategy.atr_period)).calculate(close, high=high, low=low)
    direction_series = pd.to_numeric(supertrend_df.get("direction"), errors="coerce").dropna()
    current_direction = int(direction_series.iloc[-1]) if not direction_series.empty else None
    prev_direction = int(direction_series.iloc[-2]) if len(direction_series) >= 2 else None
    price = _last_valid(close)
    trend_value = _last_valid(supertrend_df.get("supertrend", pd.Series(dtype=float)))
    distance_pct = None
    if price not in (None, 0) and trend_value is not None:
        distance_pct = round(((price - trend_value) / price) * 100.0, 4)

    return {
        "supertrend": trend_value,
        "direction": current_direction,
        "prev_direction": prev_direction,
        "atr": _last_valid(atr),
        "distance_from_supertrend_pct": distance_pct,
    }


def _orderflow_snapshot(strategy: Any, frame: pd.DataFrame) -> dict[str, Any]:
    recent = frame.tail(int(getattr(strategy, "profile_lookback", 90))).copy()
    candles = [
        SimpleNamespace(
            timestamp=row.timestamp.to_pydatetime() if hasattr(row.timestamp, "to_pydatetime") else row.timestamp,
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=int(row.volume),
        )
        for row in recent.itertuples(index=False)
    ]
    profile = compute_tpo_profile(candles, tick_size=None, value_area_pct=0.70) if len(candles) >= 2 else None
    closes = recent["close"].astype(float)
    opens = recent["open"].astype(float)
    highs = recent["high"].astype(float)
    lows = recent["low"].astype(float)
    volumes = recent["volume"].astype(float).clip(lower=0.0)
    body_sign = (closes - opens).apply(lambda x: 1.0 if x > 0 else (-1.0 if x < 0 else 0.0))
    delta_proxy = body_sign * volumes
    delta_bias = float(delta_proxy.tail(int(getattr(strategy, "delta_lookback", 10))).sum())
    total_recent_volume = float(volumes.tail(int(getattr(strategy, "delta_lookback", 10))).sum())
    flow_pressure = delta_bias / max(total_recent_volume, 1.0)
    vwap = float((closes * volumes).sum() / max(float(volumes.sum()), 1.0)) if not recent.empty else 0.0
    atr = ATR(period=int(getattr(strategy, "atr_period", 14))).calculate(closes, high=highs, low=lows)

    return {
        "poc": _json_safe(profile.poc if profile is not None else None),
        "vah": _json_safe(profile.vah if profile is not None else None),
        "val": _json_safe(profile.val if profile is not None else None),
        "ib_high": _json_safe(profile.ib_high if profile is not None else None),
        "ib_low": _json_safe(profile.ib_low if profile is not None else None),
        "vwap": round(vwap, 4) if math.isfinite(vwap) else None,
        "delta_bias": round(delta_bias, 4) if math.isfinite(delta_bias) else None,
        "flow_pressure": round(flow_pressure, 4) if math.isfinite(flow_pressure) else None,
        "atr": _last_valid(atr),
    }


def _fractal_snapshot(strategy: Any, frame: pd.DataFrame) -> dict[str, Any]:
    normalized = strategy._normalize_frame(frame)
    if normalized is None or normalized.empty:
        return {"reason": "invalid_frame"}

    symbol, market = strategy._infer_symbol_and_market(normalized)
    if not symbol or market not in {"NSE", "US", "CRYPTO"}:
        return {"reason": "unsupported_market", "market": market or None}

    median_minutes = strategy._median_bar_minutes(normalized)
    if median_minutes > float(strategy.max_bar_minutes):
        return {
            "reason": "timeframe_too_wide",
            "median_bar_minutes": round(float(median_minutes), 4),
            "max_bar_minutes": _json_safe(strategy.max_bar_minutes),
        }

    session_date, current_session, prev_session = strategy._split_sessions(normalized, market)
    if session_date is None:
        return {"reason": "missing_session"}

    orderflow_summary = strategy._build_orderflow_summary(current_session)
    context = build_daily_fractal_context(
        symbol=symbol,
        market=market,
        session_date=session_date,
        current_day_candles=current_session.to_dict("records"),
        prev_day_candles=prev_session.to_dict("records"),
        orderflow_summary=orderflow_summary,
    )
    if context is None:
        return {"reason": "context_unavailable"}

    active_hour = context.hourly_profiles[-1] if context.hourly_profiles else None
    selected = strategy._select_candidate(context, orderflow_summary)
    candidate = selected.candidate.to_dict() if selected is not None else None

    return {
        "session_date": session_date.isoformat(),
        "market": market,
        "assessment": None if context.assessment is None else context.assessment.to_dict(),
        "daily_profile": {
            "shape": context.daily_profile.shape,
            "poc": round(float(context.daily_profile.poc), 4),
            "vah": round(float(context.daily_profile.vah), 4),
            "val": round(float(context.daily_profile.val), 4),
            "ib_high": round(float(context.daily_profile.ib_high), 4),
            "ib_low": round(float(context.daily_profile.ib_low), 4),
        },
        "hourly_profiles_count": len(context.hourly_profiles),
        "current_hour": None if active_hour is None else {
            "start": active_hour.start.isoformat(),
            "shape": active_hour.shape,
            "poc": round(float(active_hour.poc), 4),
            "vah": round(float(active_hour.vah), 4),
            "val": round(float(active_hour.val), 4),
            "va_migration_vs_prev": active_hour.va_migration_vs_prev,
            "consecutive_direction_hours": int(active_hour.consecutive_direction_hours),
        },
        "candidate": candidate,
        "orderflow_summary": _json_safe(orderflow_summary),
    }


def _ml_snapshot(strategy: Any, frame: pd.DataFrame, latest_signal: dict[str, Any] | None) -> dict[str, Any]:
    strategy._ensure_loaded()
    snapshot: dict[str, Any] = {
        "models_loaded": len(getattr(strategy, "_models", [])),
        "confidence_threshold": _json_safe(getattr(strategy, "confidence_threshold", None)),
        "model_paths": _json_safe(getattr(strategy, "model_paths", [])),
    }

    generator = getattr(strategy, "_signal_generator", None)
    if generator is not None:
        try:
            snapshot["feature_metadata"] = _json_safe(generator.feature_extractor.metadata())
        except Exception:
            snapshot["feature_metadata"] = None

    if latest_signal is not None:
        metadata = latest_signal.get("metadata", {})
        if isinstance(metadata, dict):
            snapshot["confidence"] = metadata.get("confidence")
            snapshot["probabilities"] = metadata.get("probabilities")
            snapshot["weights"] = metadata.get("weights")
    return snapshot


def _strategy_indicator_snapshot(
    strategy: Any,
    frame: pd.DataFrame,
    latest_signal: dict[str, Any] | None,
) -> dict[str, Any]:
    name = getattr(strategy, "name", "")
    if frame.empty:
        return {"reason": "no_data"}
    if name == "EMA_Crossover":
        return _ema_snapshot(strategy, frame)
    if name == "RSI_Reversal":
        return _rsi_snapshot(strategy, frame)
    if name == "MACD_RSI":
        return _macd_snapshot(strategy, frame)
    if name == "Bollinger_MeanReversion":
        return _bollinger_snapshot(strategy, frame)
    if name == "Supertrend_Breakout":
        return _supertrend_snapshot(strategy, frame)
    if name == "MP_OrderFlow_Breakout":
        return _orderflow_snapshot(strategy, frame)
    if name == "Fractal_Profile_Breakout":
        return _fractal_snapshot(strategy, frame)
    if name == "ML_Ensemble":
        return _ml_snapshot(strategy, frame, latest_signal)
    return {}


async def _build_strategy_inspection(
    agent: Any,
    symbol: str,
    timeframe: str,
    frame: pd.DataFrame,
    strategy_name: str,
    options_analytics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    strategy = agent.get_strategy_instance(strategy_name)
    if strategy is None:
        raise HTTPException(status_code=400, detail=f"Unknown strategy '{strategy_name}'")

    min_bars_required = _strategy_min_bars(strategy)
    enabled = strategy_name in set(agent.config.strategies)
    latest_signal_payload: dict[str, Any] | None = None
    indicator_snapshot: dict[str, Any] = {}
    error: str | None = None

    try:
        signals = strategy.generate_signals(frame.copy())
        latest_signal = signals[-1] if signals else None
        latest_signal_payload = _serialize_signal(latest_signal, frame) if latest_signal is not None else None
        if latest_signal_payload is not None and options_analytics is not None:
            metadata = latest_signal_payload.setdefault("metadata", {})
            if isinstance(metadata, dict):
                selected_side = (
                    options_analytics.get("bullish_call")
                    if latest_signal_payload.get("signal_type") == "BUY"
                    else options_analytics.get("bearish_put")
                    if latest_signal_payload.get("signal_type") == "SELL"
                    else None
                )
                metadata["options_analytics"] = options_analytics
                metadata["selected_option_candidate"] = selected_side
        indicator_snapshot = _strategy_indicator_snapshot(strategy, frame, latest_signal_payload)
    except Exception as exc:
        error = str(exc)

    ready = len(frame) >= min_bars_required and error is None
    if strategy_name == "ML_Ensemble":
        ready = ready and bool(getattr(strategy, "_signal_generator", None))

    return {
        "name": strategy_name,
        "enabled": enabled,
        "timeframe": timeframe,
        "preferred_timeframes": agent.STRATEGY_TIMEFRAMES.get(strategy_name, []),
        "algorithm_summary": _strategy_algorithm_summary(strategy_name),
        "ready": ready,
        "bars_available": len(frame),
        "min_bars_required": min_bars_required,
        "params": _serialize_strategy_params(strategy),
        "settings_schema": _strategy_settings_schema(strategy_name, strategy),
        "indicator_snapshot": _json_safe(indicator_snapshot),
        "latest_signal": latest_signal_payload,
        "error": error,
    }


async def _close_all_positions_for_kill_switch(reason: str) -> Dict[str, Any]:
    """Flatten all open positions and cancel open orders after kill-switch activation."""
    agent = get_trading_agent()
    position_manager = get_position_manager()
    order_manager = get_order_manager()
    risk_manager = get_risk_manager()
    closed_positions: list[dict[str, Any]] = []
    cancelled_orders: list[str] = []

    try:
        open_symbols = [position.symbol for position in position_manager.get_all_positions()]
        if open_symbols:
            await agent.refresh_position_marks(open_symbols)
    except Exception as exc:
        logger.warning("kill_switch_mark_refresh_failed", error=str(exc))

    for order in order_manager.get_open_orders():
        result = order_manager.cancel_order(order.order_id)
        if result.success:
            cancelled_orders.append(order.order_id)

    for position in list(position_manager.get_all_positions()):
        mark = float(position.current_price or position.avg_price or 0.0)
        if mark <= 0:
            continue
        await agent._close_position(
            symbol=position.symbol,
            short_name=position.symbol.split(":")[-1].split("-")[0],
            current_price=mark,
            reason=reason,
            plan=agent._display_exit_plan(position.symbol),
        )
        risk_manager.sync_position_value(position.symbol, 0.0)
        closed_positions.append(
            {
                "symbol": position.symbol,
                "quantity": int(position.quantity),
                "mark_price": mark,
            }
        )

    return {
        "closed_positions": closed_positions,
        "cancelled_orders": cancelled_orders,
    }


@router.post("/start")
async def start_agent(body: AgentConfigRequest) -> Dict[str, Any]:
    """Start the AI trading agent with the given configuration."""
    risk_manager = get_risk_manager()
    if risk_manager.emergency_stop:
        return {
            "success": False,
            "message": "Kill switch is active. Clear it before restarting the agent.",
            "state": get_trading_agent().state.value,
            "emergency_stop": True,
        }

    total_capital_inr = _total_allocated_capital_inr(body)
    config = AgentConfig(
        symbols=body.symbols,
        us_symbols=body.us_symbols,
        crypto_symbols=body.crypto_symbols,
        trade_nse_when_open=body.trade_nse_when_open,
        trade_us_when_open=body.trade_us_when_open,
        trade_us_options=body.trade_us_options,
        trade_crypto_24x7=body.trade_crypto_24x7,
        strategies=body.strategies,
        scan_interval_seconds=body.scan_interval_seconds,
        paper_mode=body.paper_mode,
        capital=total_capital_inr,
        india_capital=body.india_capital,
        us_capital=body.us_capital,
        crypto_capital=body.crypto_capital,
        india_max_instrument_pct=body.india_max_instrument_pct,
        us_max_instrument_pct=body.us_max_instrument_pct,
        crypto_max_instrument_pct=body.crypto_max_instrument_pct,
        max_daily_loss_pct=body.max_daily_loss_pct,
        timeframe=body.timeframe,
        execution_timeframes=body.execution_timeframes,
        reference_timeframes=body.reference_timeframes,
        liberal_bootstrap_enabled=body.liberal_bootstrap_enabled,
        bootstrap_cycles=body.bootstrap_cycles,
        bootstrap_size_multiplier=body.bootstrap_size_multiplier,
        bootstrap_max_concentration_pct=body.bootstrap_max_concentration_pct,
        bootstrap_max_open_positions=body.bootstrap_max_open_positions,
        bootstrap_risk_per_trade_pct=body.bootstrap_risk_per_trade_pct,
        option_time_exit_minutes=body.option_time_exit_minutes,
        option_default_stop_loss_pct=body.option_default_stop_loss_pct,
        option_default_target_pct=body.option_default_target_pct,
        reinforcement_enabled=body.reinforcement_enabled,
        reinforcement_alpha=body.reinforcement_alpha,
        reinforcement_size_boost_pct=body.reinforcement_size_boost_pct,
        strategy_capital_bucket_enabled=body.strategy_capital_bucket_enabled,
        strategy_max_concurrent_positions=body.strategy_max_concurrent_positions,
        telegram_status_interval_minutes=body.telegram_status_interval_minutes,
    )

    # Validate strategy names
    invalid = [s for s in config.strategies if s not in STRATEGY_REGISTRY]
    if invalid:
        raise HTTPException(
            status_code=400,
        detail=f"Unknown strategies: {invalid}. Available: {list(STRATEGY_REGISTRY.keys())}",
        )

    # Resolve existing singleton first, then replace if configuration differs.
    agent = get_trading_agent()
    if agent.state == AgentState.RUNNING:
        return {"success": False, "message": "Agent is already running. Stop it first."}

    if agent.config != config or agent.state in (AgentState.STOPPED, AgentState.ERROR):
        reset_trading_agent()
        _sync_risk_manager_config(body)
        agent = get_trading_agent(config)
    else:
        _sync_risk_manager_config(body)

    # Start Telegram notifier
    notifier = get_telegram_notifier()
    if notifier.is_configured:
        await notifier.start()

    await agent.start()
    return {"success": True, "message": "Agent started", "state": agent.state.value}


@router.post("/stop")
async def stop_agent() -> Dict[str, Any]:
    """Stop the AI trading agent gracefully."""
    agent = get_trading_agent()
    if agent.state not in (AgentState.RUNNING, AgentState.PAUSED):
        return {"success": False, "message": f"Agent is not running (state: {agent.state.value})"}

    await agent.stop()

    # Stop Telegram notifier
    notifier = get_telegram_notifier()
    await notifier.stop()

    return {"success": True, "message": "Agent stopped", "state": agent.state.value}


@router.post("/pause")
async def pause_agent() -> Dict[str, Any]:
    """Activate kill switch, flatten portfolio, and block further trading."""
    agent = get_trading_agent()
    risk_manager = get_risk_manager()
    risk_manager.trigger_emergency_stop("manual_kill_switch")

    if agent.state not in (AgentState.STOPPED, AgentState.IDLE):
        await agent.stop()

    flatten_result = await _close_all_positions_for_kill_switch("kill_switch")
    notifier = get_telegram_notifier()
    await notifier.stop()
    await get_agent_event_bus().emit(AgentEvent(
        event_type=AgentEventType.AGENT_PAUSED,
        title="Kill Switch Activated",
        message=(
            f"Closed {len(flatten_result['closed_positions'])} position(s) and "
            f"cancelled {len(flatten_result['cancelled_orders'])} open order(s). "
            "Agent remains blocked until the kill switch is cleared."
        ),
        severity="error",
        metadata=flatten_result,
    ))
    return {
        "success": True,
        "message": (
            f"Kill switch activated. Closed {len(flatten_result['closed_positions'])} position(s) and "
            f"cancelled {len(flatten_result['cancelled_orders'])} open order(s)."
        ),
        "state": agent.state.value,
        "emergency_stop": True,
        **flatten_result,
    }


@router.post("/resume")
async def resume_agent() -> Dict[str, Any]:
    """Clear the kill switch. Starting remains a separate explicit action."""
    risk_manager = get_risk_manager()
    if not risk_manager.emergency_stop:
        return {
            "success": True,
            "message": "Kill switch is already cleared.",
            "state": get_trading_agent().state.value,
            "emergency_stop": False,
        }

    risk_manager.clear_emergency_stop("manual_clear")
    await get_agent_event_bus().emit(AgentEvent(
        event_type=AgentEventType.AGENT_RESUMED,
        title="Kill Switch Cleared",
        message="Trading remains stopped until you start the agent again.",
        severity="success",
    ))
    agent = get_trading_agent()
    return {
        "success": True,
        "message": "Kill switch cleared. Use Start to resume trading.",
        "state": agent.state.value,
        "emergency_stop": False,
    }


@router.get("/status", response_model=AgentStatusResponse)
async def get_agent_status() -> Dict[str, Any]:
    """Get current agent status and metrics."""
    agent = get_trading_agent()
    await _refresh_open_position_marks(get_position_manager(), agent)
    return agent.get_status()


@router.get("/readiness")
async def get_agent_readiness() -> Dict[str, Any]:
    """Get market readiness breakdown used by the agent loop."""
    agent = get_trading_agent()
    status = agent.get_status()
    return {
        "state": status.get("state"),
        "active_sessions": status.get("active_sessions", []),
        "market_readiness": status.get("market_readiness", {}),
    }


@router.get("/events", response_model=List[AgentEventResponse])
async def get_agent_events(limit: int = 50) -> List[Dict[str, Any]]:
    """Get recent agent events from the in-memory log."""
    bus = get_agent_event_bus()
    return bus.get_recent_events(limit=min(limit, 500))


@router.get("/strategies")
async def list_available_strategies() -> Dict[str, Any]:
    """List all available strategy names."""
    return {
        "strategies": list(STRATEGY_REGISTRY.keys()),
    }


@router.get("/strategy-controls")
async def get_strategy_controls() -> Dict[str, Any]:
    """Get enabled/disabled runtime state for each strategy."""
    agent = get_trading_agent()
    return {"controls": agent.get_strategy_controls()}


class StrategyToggleRequest(BaseModel):
    strategy: str
    enabled: bool = True


class StrategyParamsUpdateRequest(BaseModel):
    params: Dict[str, Any] = Field(default_factory=dict)


@router.post("/strategy-controls")
async def set_strategy_control(body: StrategyToggleRequest) -> Dict[str, Any]:
    """Enable or disable one strategy at runtime without restarting agent."""
    agent = get_trading_agent()
    strategy_name = str(body.strategy or "").strip()
    if strategy_name not in STRATEGY_REGISTRY:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown strategy '{strategy_name}'. Available: {list(STRATEGY_REGISTRY.keys())}",
        )

    ok = agent.set_strategy_enabled(strategy_name, bool(body.enabled))
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update strategy state.")
    return {
        "success": True,
        "strategy": strategy_name,
        "enabled": bool(body.enabled),
        "active_strategies": list(agent.config.strategies),
    }


@router.post("/strategy-parameters/{strategy_name}")
async def update_strategy_parameters(
    strategy_name: str,
    body: StrategyParamsUpdateRequest,
) -> Dict[str, Any]:
    """Update runtime parameters for one strategy."""
    agent = get_trading_agent()
    strategy_name = str(strategy_name or "").strip()
    if strategy_name not in STRATEGY_REGISTRY:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown strategy '{strategy_name}'.",
        )

    strategy = agent.get_strategy_instance(strategy_name)
    if strategy is None:
        raise HTTPException(status_code=404, detail=f"Strategy '{strategy_name}' is unavailable.")

    current_params = _strategy_constructor_params(strategy_name, strategy)
    schema = {field["name"]: field for field in _strategy_settings_schema(strategy_name, strategy)}
    unknown = [key for key in body.params.keys() if key not in schema]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown parameter(s) for {strategy_name}: {unknown}",
        )

    merged_params = dict(current_params)
    for key, raw_value in body.params.items():
        merged_params[key] = _coerce_strategy_param(key, raw_value, str(schema[key]["type"]))

    try:
        updated = agent.apply_strategy_params(strategy_name, merged_params)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "success": True,
        "strategy": strategy_name,
        "algorithm_summary": _strategy_algorithm_summary(strategy_name),
        "params": _serialize_strategy_params(updated),
        "settings_schema": _strategy_settings_schema(strategy_name, updated),
    }


@router.get("/inspector")
async def get_agent_inspector(
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    lookback_bars: int = 240,
    strategies: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Expose the exact candle/indicator context the agent is using."""
    agent = get_trading_agent()
    selected_symbol = (
        symbol
        or (agent.config.symbols[0] if agent.config.symbols else "")
        or (agent.config.us_symbols[0] if agent.config.us_symbols else "")
        or (agent.config.crypto_symbols[0] if agent.config.crypto_symbols else "")
    )
    if not selected_symbol:
        raise HTTPException(status_code=400, detail="No symbol configured for AI agent inspection.")

    selected_timeframe = str(timeframe or agent.config.timeframe or "5").strip().upper()
    frame, resolved_timeframe, data_source = await _load_inspection_frame(
        agent=agent,
        db=db,
        symbol=selected_symbol,
        requested_timeframe=selected_timeframe,
        lookback_bars=lookback_bars,
    )

    selected_strategies = [
        item.strip()
        for item in (strategies.split(",") if strategies else list(agent.config.strategies))
        if item and item.strip()
    ]
    invalid = [item for item in selected_strategies if item not in STRATEGY_REGISTRY]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown strategies: {invalid}. Available: {list(STRATEGY_REGISTRY.keys())}",
        )

    fresh, freshness = agent._data_freshness(frame, resolved_timeframe)
    reference_bias = await _reference_bias_snapshot(agent, selected_symbol)
    options_analytics = await agent.get_options_trade_analytics(selected_symbol, None, float(frame["close"].iloc[-1]))
    strategy_details = [
        await _build_strategy_inspection(
            agent=agent,
            symbol=selected_symbol,
            timeframe=resolved_timeframe,
            frame=frame,
            strategy_name=name,
            options_analytics=options_analytics,
        )
        for name in selected_strategies
    ]

    return {
        "symbol": selected_symbol,
        "market": agent._symbol_market(selected_symbol),
        "timeframe": selected_timeframe,
        "resolved_timeframe": resolved_timeframe,
        "lookback_bars": int(lookback_bars),
        "requested_at": datetime.now(tz=timezone.utc).isoformat(),
        "timeframe_active": resolved_timeframe in agent.get_execution_timeframes(),
        "execution_timeframes": agent.get_execution_timeframes(),
        "reference_timeframes": agent.get_reference_timeframes(),
        "data_source": _json_safe(data_source),
        "data_window": {
            "start": _json_safe(frame["timestamp"].iloc[0]),
            "end": _json_safe(frame["timestamp"].iloc[-1]),
            "bars": len(frame),
        },
        "freshness": {
            "fresh": fresh,
            **_json_safe(freshness),
        },
        "latest_bar": _serialize_bar(frame.iloc[-1]),
        "recent_bars": [_serialize_bar(row) for _, row in frame.tail(20).iterrows()],
        "common_indicators": _json_safe(_common_indicator_snapshot(agent, frame)),
        "reference_bias": _json_safe(reference_bias),
        "options_analytics": _json_safe(options_analytics),
        "strategies": strategy_details,
    }


class SimulateRequest(BaseModel):
    symbols: List[str] = list(DEFAULT_AGENT_NSE_SYMBOLS)
    strategies: List[str] = [
        "EMA_Crossover",
        "RSI_Reversal",
        "Supertrend_Breakout",
        "MP_OrderFlow_Breakout",
        "Fractal_Profile_Breakout",
    ]
    timeframe: str = "15"
    lookback_days: int = 30
    capital: float = 250_000.0
    step_bars: int = 5          # analyse every N bars (walk-forward stride)
    risk_per_trade_pct: float = Field(default=0.75, ge=0.05, le=5.0)
    slippage_bps: float = Field(default=2.0, ge=0.0, le=100.0)
    commission_per_trade: float = Field(default=20.0, ge=0.0)
    max_hold_bars: int = Field(default=12, ge=1, le=500)
    allow_signal_flip_exit: bool = True


class SimulateSignal(BaseModel):
    timestamp: str
    symbol: str
    strategy: str
    direction: str              # BUY / SELL
    strength: str               # strong / moderate / weak
    price: float
    stop_loss: Optional[float]
    target: Optional[float]
    message: str


class SimulateTrade(BaseModel):
    entry_time: str
    exit_time: str
    symbol: str
    strategy: str
    side: str
    quantity: int
    entry_price: float
    exit_price: float
    pnl: float
    pnl_pct: float
    exit_reason: str
    hold_bars: int


class SimulateResponse(BaseModel):
    signals: List[SimulateSignal]
    trades: List[SimulateTrade] = Field(default_factory=list)
    summary: Dict[str, Any]


@router.post("/simulate", response_model=SimulateResponse)
async def simulate_agent(body: SimulateRequest) -> Dict[str, Any]:
    """Run configured strategies against historical OHLC data.

    Walk-forwards through each symbol's recent history (step_bars stride)
    and records every actionable signal.  Returns the full signal log plus
    a summary.  No real orders are placed.
    """
    from src.data.auto_collector import collect_symbol_data
    from src.database.connection import get_session
    from src.database.operations import get_ohlc_candles
    from src.execution.strategy_executor import StrategyExecutor
    from src.strategies.base import Signal

    # Validate
    invalid = [s for s in body.strategies if s not in STRATEGY_REGISTRY]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown strategies: {invalid}. Available: {list(STRATEGY_REGISTRY.keys())}",
        )
    if body.timeframe not in ("1", "3", "5", "15", "30", "60", "D"):
        raise HTTPException(status_code=400, detail="Unsupported timeframe for simulation")

    if body.capital <= 0:
        raise HTTPException(status_code=400, detail="capital must be > 0")

    cache = get_ohlc_cache()
    fyers_client = get_fyers_client()

    # Build a strategy executor for simulation (paper mode, no order tracking)
    executor = StrategyExecutor(paper_mode=True)
    for strat_name in body.strategies:
        executor.register_strategy(strat_name, STRATEGY_REGISTRY[strat_name](), enabled=True)
    executor.start()

    signals_out: List[Dict[str, Any]] = []
    trades_out: List[Dict[str, Any]] = []
    bars_scanned = 0
    no_data_symbols = []
    data_sources: Dict[str, str] = {}
    running_capital = float(body.capital)

    async def _load_simulation_df(symbol: str):
        """Load lookback candles from cache, DB, then broker backfill."""
        utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
        cutoff_naive = utc_now - timedelta(days=body.lookback_days)
        cutoff_aware_utc = cutoff_naive.replace(tzinfo=timezone.utc)

        def _clip_lookback(frame):
            """Clip with tz-safe cutoff to avoid aware/naive comparison errors."""
            if frame is None or frame.empty:
                return frame
            idx_tz = getattr(frame.index, "tz", None)
            cutoff = cutoff_aware_utc if idx_tz is not None else cutoff_naive
            return frame[frame.index >= cutoff]

        # 1) Cache first
        df = cache.as_dataframe(symbol, body.timeframe, limit=5000)
        if not df.empty:
            clipped = _clip_lookback(df)
            if len(clipped) >= 50:
                return clipped, "cache"

        # 2) DB fallback
        start_naive = cutoff_naive
        end_naive = utc_now
        try:
            async with get_session() as session:
                rows = await get_ohlc_candles(
                    session,
                    symbol,
                    body.timeframe,
                    start_naive,
                    end_naive,
                    limit=5000,
                )
            if rows:
                candles = [
                    {
                        "timestamp": r.timestamp.isoformat(),
                        "open": float(r.open),
                        "high": float(r.high),
                        "low": float(r.low),
                        "close": float(r.close),
                        "volume": int(r.volume),
                    }
                    for r in rows
                ]
                await cache.upsert(symbol, body.timeframe, candles)
                df = cache.as_dataframe(symbol, body.timeframe, limit=5000)
                if not df.empty:
                    clipped = _clip_lookback(df)
                    if len(clipped) >= 50:
                        return clipped, "database"
        except Exception as exc:
            logger.warning("simulate_db_load_failed", symbol=symbol, tf=body.timeframe, error=str(exc))

        # 3) Broker backfill + persistence fallback
        if fyers_client.is_authenticated:
            try:
                await collect_symbol_data(
                    fyers_client,
                    symbol,
                    body.timeframe,
                    days_back=max(body.lookback_days, 30),
                    force=False,
                )
                async with get_session() as session:
                    rows = await get_ohlc_candles(
                        session,
                        symbol,
                        body.timeframe,
                        start_naive,
                        end_naive,
                        limit=5000,
                    )
                if rows:
                    candles = [
                        {
                            "timestamp": r.timestamp.isoformat(),
                            "open": float(r.open),
                            "high": float(r.high),
                            "low": float(r.low),
                            "close": float(r.close),
                            "volume": int(r.volume),
                        }
                        for r in rows
                    ]
                    await cache.upsert(symbol, body.timeframe, candles)
                    df = cache.as_dataframe(symbol, body.timeframe, limit=5000)
                    if not df.empty:
                        clipped = _clip_lookback(df)
                        if len(clipped) >= 50:
                            return clipped, "broker_backfill"
            except Exception as exc:
                logger.warning("simulate_backfill_failed", symbol=symbol, tf=body.timeframe, error=str(exc))

        return df.iloc[0:0], "none"

    for symbol in body.symbols:
        df, source = await _load_simulation_df(symbol)
        data_sources[symbol] = source
        if df.empty or len(df) < 50:
            no_data_symbols.append(symbol)
            logger.warning("simulate_no_data", symbol=symbol, tf=body.timeframe)
            continue

        # Strategies expect an explicit `timestamp` column in addition to index.
        if "timestamp" not in df.columns:
            df = df.copy()
            df["timestamp"] = df.index

        # Minimum warmup period before running strategies
        min_warmup = 30
        open_position: Optional[Dict[str, Any]] = None

        # Walk-forward: slide window over history
        for bar_idx in range(min_warmup, len(df), max(body.step_bars, 1)):
            window = df.iloc[: bar_idx + 1]
            bars_scanned += 1
            row = df.iloc[bar_idx]
            bar_time = df.index[bar_idx]
            bar_high = float(row["high"])
            bar_low = float(row["low"])
            bar_close = float(row["close"])

            # Manage open position first (SL/Target/Time exits)
            if open_position is not None:
                side = open_position["side"]
                entry = open_position["entry_price"]
                qty = open_position["quantity"]
                stop = open_position["stop_loss"]
                target = open_position["target"]
                hold_bars = bar_idx - open_position["entry_bar"]
                exit_price: Optional[float] = None
                exit_reason: Optional[str] = None

                if side == "BUY":
                    if bar_low <= stop:
                        exit_price = stop * (1.0 - body.slippage_bps / 10_000.0)
                        exit_reason = "stop_loss"
                    elif bar_high >= target:
                        exit_price = target * (1.0 - body.slippage_bps / 10_000.0)
                        exit_reason = "target"
                else:
                    if bar_high >= stop:
                        exit_price = stop * (1.0 + body.slippage_bps / 10_000.0)
                        exit_reason = "stop_loss"
                    elif bar_low <= target:
                        exit_price = target * (1.0 + body.slippage_bps / 10_000.0)
                        exit_reason = "target"

                if exit_price is None and hold_bars >= body.max_hold_bars:
                    if side == "BUY":
                        exit_price = bar_close * (1.0 - body.slippage_bps / 10_000.0)
                    else:
                        exit_price = bar_close * (1.0 + body.slippage_bps / 10_000.0)
                    exit_reason = "time_exit"

                if exit_price is not None and exit_reason is not None:
                    gross = (exit_price - entry) * qty if side == "BUY" else (entry - exit_price) * qty
                    net = gross - (body.commission_per_trade * 2.0)
                    running_capital += net
                    pnl_pct = (net / (entry * qty) * 100.0) if entry > 0 and qty > 0 else 0.0
                    trades_out.append(
                        {
                            "entry_time": open_position["entry_time"].isoformat(),
                            "exit_time": bar_time.isoformat() if hasattr(bar_time, "isoformat") else str(bar_time),
                            "symbol": symbol,
                            "strategy": open_position["strategy"],
                            "side": side,
                            "quantity": qty,
                            "entry_price": round(entry, 2),
                            "exit_price": round(float(exit_price), 2),
                            "pnl": round(float(net), 2),
                            "pnl_pct": round(float(pnl_pct), 2),
                            "exit_reason": exit_reason,
                            "hold_bars": hold_bars,
                        }
                    )
                    open_position = None

            try:
                results = executor.process_data(window, symbol)
            except Exception as exc:
                logger.warning("simulate_strategy_error", symbol=symbol, error=str(exc))
                continue

            for result in results:
                strat_name = result.get("strategy", "")
                signal: Any = result.get("signal")
                if not isinstance(signal, Signal) or not signal.is_actionable:
                    continue

                ts = df.index[bar_idx]
                signals_out.append(
                    {
                        "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                        "symbol": symbol,
                        "strategy": strat_name,
                        "direction": signal.signal_type.value,
                        "strength": signal.strength.value if signal.strength else "moderate",
                        "price": round(float(signal.price or window["close"].iloc[-1]), 2),
                        "stop_loss": round(float(signal.stop_loss), 2) if signal.stop_loss else None,
                        "target": round(float(signal.target), 2) if signal.target else None,
                        "message": (
                            f"{strat_name}: {signal.signal_type.value} on "
                            f"{symbol.split(':')[-1].split('-')[0]} @ "
                            f"{signal.price or window['close'].iloc[-1]:,.1f}"
                        ),
                    }
                )

                # Exit on opposite signal if enabled.
                if (
                    body.allow_signal_flip_exit
                    and open_position is not None
                    and open_position["side"] != signal.signal_type.value
                ):
                    exit_price = bar_close * (
                        (1.0 - body.slippage_bps / 10_000.0)
                        if open_position["side"] == "BUY"
                        else (1.0 + body.slippage_bps / 10_000.0)
                    )
                    hold_bars = bar_idx - open_position["entry_bar"]
                    gross = (
                        (exit_price - open_position["entry_price"]) * open_position["quantity"]
                        if open_position["side"] == "BUY"
                        else (open_position["entry_price"] - exit_price) * open_position["quantity"]
                    )
                    net = gross - (body.commission_per_trade * 2.0)
                    running_capital += net
                    pnl_pct = (
                        net / (open_position["entry_price"] * open_position["quantity"]) * 100.0
                        if open_position["entry_price"] > 0 and open_position["quantity"] > 0
                        else 0.0
                    )
                    trades_out.append(
                        {
                            "entry_time": open_position["entry_time"].isoformat(),
                            "exit_time": bar_time.isoformat() if hasattr(bar_time, "isoformat") else str(bar_time),
                            "symbol": symbol,
                            "strategy": open_position["strategy"],
                            "side": open_position["side"],
                            "quantity": open_position["quantity"],
                            "entry_price": round(float(open_position["entry_price"]), 2),
                            "exit_price": round(float(exit_price), 2),
                            "pnl": round(float(net), 2),
                            "pnl_pct": round(float(pnl_pct), 2),
                            "exit_reason": "signal_flip",
                            "hold_bars": hold_bars,
                        }
                    )
                    open_position = None

                # Entry simulation: one open position per symbol.
                if open_position is not None:
                    continue

                entry_raw = float(signal.price or bar_close)
                side = signal.signal_type.value
                entry_fill = entry_raw * (
                    (1.0 + body.slippage_bps / 10_000.0)
                    if side == "BUY"
                    else (1.0 - body.slippage_bps / 10_000.0)
                )

                if signal.stop_loss is not None:
                    stop_loss = float(signal.stop_loss)
                elif side == "BUY":
                    stop_loss = entry_fill * 0.99
                else:
                    stop_loss = entry_fill * 1.01

                if signal.target is not None:
                    target = float(signal.target)
                else:
                    risk = max(abs(entry_fill - stop_loss), entry_fill * 0.005)
                    target = entry_fill + (risk * 1.5) if side == "BUY" else entry_fill - (risk * 1.5)

                unit_risk = max(abs(entry_fill - stop_loss), entry_fill * 0.001, 1e-6)
                risk_budget = max(running_capital * (body.risk_per_trade_pct / 100.0), 1.0)
                qty_risk = int(math.floor(risk_budget / unit_risk))
                qty_notional_cap = int(max((running_capital * 1.5) / max(entry_fill, 1e-6), 1))
                quantity = max(min(qty_risk, qty_notional_cap), 1)

                open_position = {
                    "entry_time": bar_time,
                    "entry_bar": bar_idx,
                    "symbol": symbol,
                    "strategy": strat_name,
                    "side": side,
                    "quantity": quantity,
                    "entry_price": float(entry_fill),
                    "stop_loss": float(stop_loss),
                    "target": float(target),
                }

        # Force-close remaining open position at final close.
        if open_position is not None:
            final_close = float(df["close"].iloc[-1])
            final_time = df.index[-1]
            side = open_position["side"]
            exit_price = final_close * (
                (1.0 - body.slippage_bps / 10_000.0)
                if side == "BUY"
                else (1.0 + body.slippage_bps / 10_000.0)
            )
            gross = (
                (exit_price - open_position["entry_price"]) * open_position["quantity"]
                if side == "BUY"
                else (open_position["entry_price"] - exit_price) * open_position["quantity"]
            )
            net = gross - (body.commission_per_trade * 2.0)
            running_capital += net
            hold_bars = (len(df) - 1) - open_position["entry_bar"]
            pnl_pct = (
                net / (open_position["entry_price"] * open_position["quantity"]) * 100.0
                if open_position["entry_price"] > 0 and open_position["quantity"] > 0
                else 0.0
            )
            trades_out.append(
                {
                    "entry_time": open_position["entry_time"].isoformat(),
                    "exit_time": final_time.isoformat() if hasattr(final_time, "isoformat") else str(final_time),
                    "symbol": symbol,
                    "strategy": open_position["strategy"],
                    "side": side,
                    "quantity": open_position["quantity"],
                    "entry_price": round(float(open_position["entry_price"]), 2),
                    "exit_price": round(float(exit_price), 2),
                    "pnl": round(float(net), 2),
                    "pnl_pct": round(float(pnl_pct), 2),
                    "exit_reason": "end_of_test",
                    "hold_bars": hold_bars,
                }
            )

    executor.stop()

    total_trades = len(trades_out)
    wins = sum(1 for t in trades_out if t["pnl"] > 0)
    losses = sum(1 for t in trades_out if t["pnl"] < 0)
    net_pnl = round(sum(float(t["pnl"]) for t in trades_out), 2)
    win_rate = round((wins / total_trades * 100.0), 1) if total_trades > 0 else 0.0

    summary = {
        "symbols_scanned": len(body.symbols),
        "symbols_with_data": len(body.symbols) - len(no_data_symbols),
        "no_data_symbols": no_data_symbols,
        "data_sources": data_sources,
        "timeframe": body.timeframe,
        "lookback_days": body.lookback_days,
        "bars_scanned": bars_scanned,
        "total_signals": len(signals_out),
        "buy_signals": sum(1 for s in signals_out if s["direction"] == "BUY"),
        "sell_signals": sum(1 for s in signals_out if s["direction"] == "SELL"),
        "total_trades": total_trades,
        "winning_trades": wins,
        "losing_trades": losses,
        "win_rate": win_rate,
        "net_pnl": net_pnl,
        "starting_capital": round(float(body.capital), 2),
        "ending_capital": round(float(running_capital), 2),
        "risk_per_trade_pct": body.risk_per_trade_pct,
        "slippage_bps": body.slippage_bps,
        "commission_per_trade": body.commission_per_trade,
        "max_hold_bars": body.max_hold_bars,
        "strategies_used": body.strategies,
        "ran_at": datetime.now(timezone.utc).isoformat(),
    }

    return {"signals": signals_out, "trades": trades_out, "summary": summary}


@router.post("/test-telegram")
async def test_telegram() -> Dict[str, Any]:
    """Send a test message to the configured Telegram chat."""
    notifier = get_telegram_notifier()
    if not notifier.is_configured:
        return {
            "success": False,
            "message": "Telegram not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env.",
        }

    success = await notifier.send_test_message()
    if success:
        return {"success": True, "message": "Test message sent to Telegram"}
    detail = notifier.last_error or "Check token and chat ID."
    return {"success": False, "message": f"Failed to send Telegram message. {detail}"}


@router.post("/notify-status")
async def notify_status_telegram() -> Dict[str, Any]:
    """Send an on-demand Telegram status snapshot for trades/positions."""
    notifier = get_telegram_notifier()
    if not notifier.is_configured:
        return {
            "success": False,
            "message": "Telegram not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env.",
        }

    agent = get_trading_agent()
    pm = get_position_manager()
    await _refresh_open_position_marks(pm, agent)
    status = agent.get_status()
    settings = get_settings()
    portfolio = _build_currency_aware_portfolio(
        pm=pm,
        usd_inr_rate=float(settings.usd_inr_reference_rate),
        capital_allocations=agent.get_capital_allocations(),
    )

    last_scan = status.get("last_scan_time")
    last_scan_ist = "—"
    if isinstance(last_scan, str) and last_scan:
        try:
            parsed = datetime.fromisoformat(last_scan.replace("Z", "+00:00"))
            last_scan_ist = parsed.astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%H:%M:%S IST")
        except Exception:
            last_scan_ist = last_scan

    text = (
        "<b>Nifty AI Trader — Status Snapshot</b>\n"
        f"State: <b>{str(status.get('state', 'unknown')).upper()}</b>\n"
        f"Cycle: {int(status.get('current_cycle', 0))}\n"
        f"Signals: {int(status.get('total_signals', 0))} | Trades: {int(status.get('total_trades', 0))}\n"
        f"Open Positions: {int(status.get('positions_count', 0))}\n"
        f"Daily P&L: {float(status.get('daily_pnl', 0.0)):+,.2f}\n"
        f"Portfolio P&L: {float(portfolio.get('total_pnl', 0.0)):+,.2f}\n"
        f"Sessions: {', '.join(status.get('active_sessions', []) or ['NONE'])}\n"
        f"Last Scan: {last_scan_ist}\n"
        f"Positions:\n{pm.format_position_summary(max_items=5)}"
    )

    success = await notifier.send_message(text, force=True)
    if success:
        return {"success": True, "message": "Status snapshot sent to Telegram."}
    return {"success": False, "message": "Failed to send status snapshot to Telegram."}


@router.post("/notify-fractal-scan")
async def notify_fractal_scan_telegram() -> Dict[str, Any]:
    """Run a watchlist fractal scan and forward candidate events to Telegram."""
    notifier = get_telegram_notifier()
    if not notifier.is_configured:
        return {
            "success": False,
            "message": "Telegram not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env.",
        }

    service = get_fractal_scan_notifier()
    bus = get_agent_event_bus()
    queue = bus.subscribe(maxsize=64)
    try:
        payload = await service.notify_once()
        await asyncio.sleep(0)
        events: list[AgentEvent] = []
        while not queue.empty():
            event = queue.get_nowait()
            if event.event_type in {
                AgentEventType.FRACTAL_SCAN_SUMMARY,
                AgentEventType.FRACTAL_CANDIDATE,
            }:
                events.append(event)
    finally:
        bus.unsubscribe(queue)

    delivered = 0
    for event in events:
        if await notifier.send_message(event.to_telegram_text(), force=True):
            delivered += 1

    final_count = int(payload.get("stages", {}).get("final", 0) or 0)
    return {
        "success": delivered == len(events),
        "message": f"Fractal watchlist scan sent to Telegram with {final_count} candidate(s).",
        "candidates": final_count,
        "delivered_messages": delivered,
        "date": payload.get("date"),
    }
