"""Public crypto websocket collector backed by Binance combined streams."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import websockets

from src.config.market_hours import IST
from src.utils.logger import get_logger

logger = get_logger(__name__)


OnCryptoTickCallback = Callable[[dict[str, Any]], None]
OnCryptoCandleCallback = Callable[[dict[str, Any]], None]


@dataclass
class CryptoTickCollectorStats:
    """Runtime statistics for the public crypto market-data collector."""

    ticks_received: int = 0
    candles_emitted: int = 0
    reconnections: int = 0
    errors: int = 0
    started_at: datetime | None = None

    @property
    def uptime_seconds(self) -> float:
        if self.started_at is None:
            return 0.0
        return (datetime.now(tz=IST) - self.started_at).total_seconds()


class CryptoTickCollector:
    """Collect public crypto ticks and 1m candle-close events from Binance."""

    def __init__(
        self,
        symbols: list[str] | None = None,
        *,
        on_tick: OnCryptoTickCallback | None = None,
        on_candle: OnCryptoCandleCallback | None = None,
        ws_url: str = "wss://stream.binance.com:9443/stream",
        reconnect_delay_seconds: float = 2.0,
    ) -> None:
        self._pairs = self._normalize_pairs(symbols or [])
        self._on_tick = on_tick
        self._on_candle = on_candle
        self._ws_url = ws_url
        self._reconnect_delay_seconds = max(float(reconnect_delay_seconds), 0.5)
        self._running = False
        self._ws: Any = None
        self.stats = CryptoTickCollectorStats()

    async def start_async(self) -> None:
        """Run the combined websocket collector until stopped."""
        if self._running or not self._pairs:
            return

        self._running = True
        self.stats.started_at = datetime.now(tz=IST)
        logger.info("crypto_tick_collector_starting", symbols=self._pairs)

        while self._running:
            try:
                async with websockets.connect(
                    self._combined_stream_url(),
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_size=2**20,
                ) as websocket:
                    self._ws = websocket
                    logger.info("crypto_tick_collector_connected", symbols=self._pairs)
                    async for raw_message in websocket:
                        if not self._running:
                            break
                        self._handle_message(raw_message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.stats.errors += 1
                logger.warning("crypto_tick_collector_error", error=str(exc))
                if self._running:
                    self.stats.reconnections += 1
                    await asyncio.sleep(self._reconnect_delay_seconds)
            finally:
                self._ws = None

        logger.info(
            "crypto_tick_collector_stopped",
            ticks=self.stats.ticks_received,
            candles=self.stats.candles_emitted,
            uptime=f"{self.stats.uptime_seconds:.0f}s",
        )

    def stop(self) -> None:
        """Request shutdown and close the active websocket if needed."""
        self._running = False
        websocket = self._ws
        if websocket is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(websocket.close())

    def _combined_stream_url(self) -> str:
        streams: list[str] = []
        for pair in self._pairs:
            lower_pair = pair.lower()
            streams.append(f"{lower_pair}@trade")
            streams.append(f"{lower_pair}@kline_1m")
        return f"{self._ws_url}?streams={'/'.join(streams)}"

    def _handle_message(self, raw_message: str) -> None:
        try:
            payload = json.loads(raw_message)
        except json.JSONDecodeError:
            self.stats.errors += 1
            return

        if not isinstance(payload, dict):
            return
        data = payload.get("data")
        if not isinstance(data, dict):
            return

        event_type = str(data.get("e") or "").strip().lower()
        if event_type == "trade":
            tick = self._normalize_trade(data)
            if tick is None:
                return
            self.stats.ticks_received += 1
            if self._on_tick is not None:
                self._on_tick(tick)
            return

        if event_type == "kline":
            candle = self._normalize_closed_candle(data)
            if candle is None:
                return
            self.stats.candles_emitted += 1
            if self._on_candle is not None:
                self._on_candle(candle)

    @classmethod
    def _normalize_pairs(cls, symbols: list[str]) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for symbol in symbols:
            pair = cls._normalize_pair(symbol)
            if not pair or pair in seen:
                continue
            seen.add(pair)
            ordered.append(pair)
        return ordered

    @staticmethod
    def _normalize_pair(symbol: str) -> str:
        pair = str(symbol or "").split(":")[-1].strip().upper()
        pair = pair.replace("/", "").replace("-", "")
        if pair.endswith("USD") and not pair.endswith("USDT"):
            pair = f"{pair}T"
        if pair.isalpha() and len(pair) <= 6:
            pair = f"{pair}USDT"
        return pair

    @staticmethod
    def _normalize_trade(payload: dict[str, Any]) -> dict[str, Any] | None:
        symbol = str(payload.get("s") or "").strip().upper()
        if not symbol:
            return None
        try:
            price = float(payload.get("p"))
        except (TypeError, ValueError):
            return None
        if price <= 0:
            return None
        try:
            trade_time_ms = int(payload.get("T"))
        except (TypeError, ValueError):
            trade_time_ms = 0
        timestamp = datetime.fromtimestamp(trade_time_ms / 1000.0, tz=timezone.utc).astimezone(IST)
        return {
            "type": "tick",
            "symbol": f"CRYPTO:{symbol}",
            "timestamp": timestamp.isoformat(),
            "ltp": price,
            "bid": None,
            "ask": None,
            "volume": 0,
            "cumulative_volume": None,
            "source": "binance_ws",
        }

    @staticmethod
    def _normalize_closed_candle(payload: dict[str, Any]) -> dict[str, Any] | None:
        kline = payload.get("k")
        if not isinstance(kline, dict) or not bool(kline.get("x")):
            return None

        symbol = str(kline.get("s") or payload.get("s") or "").strip().upper()
        if not symbol:
            return None
        try:
            bucket_start_ms = int(kline.get("t"))
            open_price = float(kline.get("o"))
            high_price = float(kline.get("h"))
            low_price = float(kline.get("l"))
            close_price = float(kline.get("c"))
            raw_volume = float(kline.get("v") or 0.0)
        except (TypeError, ValueError):
            return None

        bucket_start = datetime.fromtimestamp(bucket_start_ms / 1000.0, tz=timezone.utc).astimezone(IST)
        volume = int(raw_volume)
        if volume <= 0 and raw_volume > 0:
            volume = 1
        return {
            "type": "candle",
            "symbol": f"CRYPTO:{symbol}",
            "timeframe": "1",
            "timestamp": bucket_start.isoformat(),
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "volume": volume,
            "source": "binance_ws",
        }
