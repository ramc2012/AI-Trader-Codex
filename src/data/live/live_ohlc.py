"""Thread-safe bridge from live 1-minute candles into the shared OHLC cache."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from src.config.market_hours import IST
from src.data.ohlc_cache import OHLCCache, get_ohlc_cache


class LiveOHLCCacheBridge:
    """Aggregate live 1-minute candles into cache-backed higher timeframes."""

    def __init__(
        self,
        cache: OHLCCache | None = None,
        aggregate_timeframes: Tuple[str, ...] = ("1", "3", "5", "15", "60", "D"),
    ) -> None:
        self._cache = cache or get_ohlc_cache()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._aggregate_timeframes = tuple(str(tf).upper() for tf in aggregate_timeframes)
        self._current: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def ingest_candle(self, candle: Dict[str, Any]) -> None:
        """Schedule a candle ingestion from a non-async callback/thread."""
        if self._loop is None or not self._loop.is_running():
            return
        payload = dict(candle)
        self._loop.call_soon_threadsafe(
            lambda: asyncio.create_task(self._ingest_async(payload))
        )

    async def _ingest_async(self, candle: Dict[str, Any]) -> None:
        symbol = str(candle.get("symbol", "")).strip()
        if not symbol:
            return

        ts_ist = self._coerce_ist_timestamp(candle.get("timestamp"))
        if ts_ist is None:
            return

        minute = self._build_cache_candle(
            bucket_start=ts_ist.replace(second=0, microsecond=0),
            open_price=float(candle.get("open") or 0.0),
            high_price=float(candle.get("high") or 0.0),
            low_price=float(candle.get("low") or 0.0),
            close_price=float(candle.get("close") or 0.0),
            volume=int(candle.get("volume") or 0),
        )
        await self._cache.upsert(symbol, "1", [minute])

        for timeframe in self._aggregate_timeframes:
            if timeframe == "1":
                continue
            aggregate = self._update_aggregate(symbol, timeframe, minute, ts_ist)
            if aggregate is not None:
                await self._cache.upsert(symbol, timeframe, [aggregate])

    def _update_aggregate(
        self,
        symbol: str,
        timeframe: str,
        minute: Dict[str, Any],
        ts_ist: datetime,
    ) -> Dict[str, Any] | None:
        if timeframe == "D":
            bucket_start = ts_ist.replace(hour=0, minute=0, second=0, microsecond=0)
        elif timeframe.isdigit():
            minutes = max(int(timeframe), 1)
            bucket_start = ts_ist.replace(
                minute=(ts_ist.minute // minutes) * minutes,
                second=0,
                microsecond=0,
            )
        else:
            return None

        bucket_ts = self._to_cache_timestamp(bucket_start)
        key = (symbol, timeframe)
        current = self._current.get(key)
        if current is None or current["timestamp"] != bucket_ts:
            current = {
                "timestamp": bucket_ts,
                "open": float(minute["open"]),
                "high": float(minute["high"]),
                "low": float(minute["low"]),
                "close": float(minute["close"]),
                "volume": int(minute["volume"]),
            }
            self._current[key] = current
            return dict(current)

        current["high"] = max(float(current["high"]), float(minute["high"]))
        current["low"] = min(float(current["low"]), float(minute["low"]))
        current["close"] = float(minute["close"])
        current["volume"] = int(current["volume"]) + int(minute["volume"])
        return dict(current)

    @staticmethod
    def _build_cache_candle(
        *,
        bucket_start: datetime,
        open_price: float,
        high_price: float,
        low_price: float,
        close_price: float,
        volume: int,
    ) -> Dict[str, Any]:
        return {
            "timestamp": LiveOHLCCacheBridge._to_cache_timestamp(bucket_start),
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "volume": int(volume),
        }

    @staticmethod
    def _coerce_ist_timestamp(raw: Any) -> datetime | None:
        if isinstance(raw, datetime):
            ts = raw
        elif isinstance(raw, str):
            try:
                ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                return None
        else:
            return None

        if ts.tzinfo is None:
            return ts.replace(tzinfo=IST)
        return ts.astimezone(IST)

    @staticmethod
    def _to_cache_timestamp(ts_ist: datetime) -> str:
        return ts_ist.astimezone(timezone.utc).replace(tzinfo=None).isoformat()
