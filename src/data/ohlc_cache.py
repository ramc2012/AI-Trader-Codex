"""In-memory OHLC cache for sub-millisecond API responses.

Populated from the database and/or Fyers REST API on startup; updated
by the market-data API on every Fyers fallback fetch.  The API reads from
here first, bypassing per-request DB round-trips entirely.

Candles are stored as plain dicts::

    {
        "timestamp": "2026-03-03T09:15:00",   # naive UTC ISO-8601 string
        "open":   24500.0,
        "high":   24520.0,
        "low":    24490.0,
        "close":  24510.0,
        "volume": 1_000_000,
    }

sorted ascending by timestamp within each (symbol, timeframe) slot.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Maximum bars to keep per (symbol, timeframe) slot
_CAPS: dict[str, int] = {
    "1":  2_000,
    "3":  1_000,
    "5":  1_000,
    "15":   600,
    "30":   400,
    "60":   300,
    "D":    500,
    "W":    260,
    "M":    120,
}
_DEFAULT_CAP = 500


class OHLCCache:
    """Thread-safe in-memory candle store."""

    def __init__(self) -> None:
        # { symbol: { timeframe: [candle_dict, ...] } }  sorted ascending by ts
        self._store: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self._lock = asyncio.Lock()
        self._ready = False

    # ── Populate ──────────────────────────────────────────────────────────────

    async def warm_up(
        self, data: dict[str, dict[str, list[dict[str, Any]]]]
    ) -> None:
        """Bulk-load candle dicts at startup (from DB + optional Fyers fill)."""
        async with self._lock:
            for symbol, tfs in data.items():
                for tf, rows in tfs.items():
                    if rows:
                        cap = _CAPS.get(tf, _DEFAULT_CAP)
                        self._store[symbol][tf] = list(rows[-cap:])
            self._ready = True

        total = sum(len(r) for tfs in data.values() for r in tfs.values())
        symbols_with_data = sum(
            1 for tfs in data.values() if any(tfs.values())
        )
        logger.info(
            "ohlc_cache_warmed",
            symbols_with_data=symbols_with_data,
            total_symbols=len(data),
            total_bars=total,
        )

    async def upsert(
        self,
        symbol: str,
        timeframe: str,
        new_candles: list[dict[str, Any]],
    ) -> None:
        """Merge new candles into cache (called after any Fyers fetch)."""
        if not new_candles:
            return
        cap = _CAPS.get(timeframe, _DEFAULT_CAP)
        async with self._lock:
            existing = self._store[symbol][timeframe]
            if not existing:
                self._store[symbol][timeframe] = list(new_candles[-cap:])
                return
            # O(1) lookup on tail for update-vs-append detection
            tail_ts: set[str] = {c["timestamp"] for c in existing[-50:]}
            for c in new_candles:
                ts: str = c["timestamp"]
                if ts in tail_ts:
                    start_index = max(len(existing) - 50, 0)
                    for i, e in enumerate(existing[start_index:], start=start_index):
                        if e["timestamp"] == ts:
                            existing[i] = c
                            break
                else:
                    existing.append(c)
            if len(existing) > cap:
                self._store[symbol][timeframe] = existing[-cap:]

    # ── Read ──────────────────────────────────────────────────────────────────

    def get(
        self, symbol: str, timeframe: str, limit: int = 500
    ) -> list[dict[str, Any]]:
        """Return the most recent *limit* candles (ascending timestamp)."""
        rows = self._store.get(symbol, {}).get(timeframe, [])
        return rows[-limit:] if rows else []

    def has(self, symbol: str, timeframe: str) -> bool:
        return bool(self._store.get(symbol, {}).get(timeframe))

    def as_dataframe(self, symbol: str, timeframe: str, limit: int = 500):
        """Return candles as a pandas DataFrame (for strategy consumption)."""
        import pandas as pd  # lazy import — not always needed

        rows = self.get(symbol, timeframe, limit)
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp").sort_index()
        for col in ("open", "high", "low", "close"):
            df[col] = df[col].astype(float)
        df["volume"] = df["volume"].astype(int)
        return df

    @property
    def is_ready(self) -> bool:
        return self._ready

    def stats(self) -> dict[str, Any]:
        return {
            sym: {tf: len(rows) for tf, rows in tfs.items()}
            for sym, tfs in self._store.items()
        }


# ── Module-level singleton ─────────────────────────────────────────────────────

_cache: OHLCCache | None = None


def get_ohlc_cache() -> OHLCCache:
    """Return the global OHLCCache instance (created on first call)."""
    global _cache
    if _cache is None:
        _cache = OHLCCache()
    return _cache
