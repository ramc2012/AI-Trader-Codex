"""Real-time tick data collector using Fyers WebSocket.

Streams live tick data for index symbols and:
- Publishes ticks to Redis for real-time consumers
- Batch-inserts ticks into TimescaleDB every N seconds
- Handles disconnections with automatic reconnection
- Validates incoming tick data
- Aggregates ticks into 1-minute candles
- Supports graceful shutdown
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from src.config.constants import INDEX_SYMBOLS
from src.config.market_hours import IST
from src.config.settings import get_settings
from src.utils.exceptions import DataValidationError
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Tick:
    """A single market tick."""

    symbol: str
    timestamp: datetime
    ltp: float
    bid: float | None = None
    ask: float | None = None
    volume: int = 0
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "ltp": self.ltp,
            "bid": self.bid,
            "ask": self.ask,
            "volume": self.volume,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
        }


@dataclass
class CandleAggregator:
    """Aggregates ticks into 1-minute OHLCV candles."""

    symbol: str
    interval_seconds: int = 60
    _current_minute: datetime | None = None
    _open: float | None = None
    _high: float = float("-inf")
    _low: float = float("inf")
    _close: float | None = None
    _volume: int = 0

    def add_tick(self, tick: Tick) -> dict[str, Any] | None:
        """Add a tick and return a completed candle dict if the minute rolled over.

        Args:
            tick: Incoming tick.

        Returns:
            Completed candle dict, or None if the current minute is still open.
        """
        tick_minute = tick.timestamp.replace(second=0, microsecond=0)
        completed_candle: dict[str, Any] | None = None

        if self._current_minute is not None and tick_minute > self._current_minute:
            # Minute rolled over — emit the completed candle
            completed_candle = self._emit_candle()

        if self._current_minute is None or tick_minute > self._current_minute:
            # Start a new minute
            self._current_minute = tick_minute
            self._open = tick.ltp
            self._high = tick.ltp
            self._low = tick.ltp
            self._close = tick.ltp
            self._volume = tick.volume
        else:
            # Update current minute
            self._high = max(self._high, tick.ltp)
            self._low = min(self._low, tick.ltp)
            self._close = tick.ltp
            self._volume += tick.volume

        return completed_candle

    def flush(self) -> dict[str, Any] | None:
        """Force-emit the current in-progress candle (e.g., on shutdown)."""
        if self._current_minute is not None and self._open is not None:
            return self._emit_candle()
        return None

    def _emit_candle(self) -> dict[str, Any]:
        candle = {
            "symbol": self.symbol,
            "timeframe": "1",
            "timestamp": self._current_minute,
            "open": self._open,
            "high": self._high,
            "low": self._low,
            "close": self._close,
            "volume": self._volume,
        }
        self._reset()
        return candle

    def _reset(self) -> None:
        self._current_minute = None
        self._open = None
        self._high = float("-inf")
        self._low = float("inf")
        self._close = None
        self._volume = 0


@dataclass
class TickCollectorStats:
    """Runtime statistics for the tick collector."""

    ticks_received: int = 0
    ticks_invalid: int = 0
    batches_flushed: int = 0
    candles_emitted: int = 0
    reconnections: int = 0
    errors: int = 0
    started_at: datetime | None = None

    @property
    def uptime_seconds(self) -> float:
        if self.started_at is None:
            return 0.0
        return (datetime.now(tz=IST) - self.started_at).total_seconds()


# Callback types
OnTickCallback = Callable[[Tick], None]
OnCandleCallback = Callable[[dict[str, Any]], None]
OnBatchCallback = Callable[[list[dict[str, Any]]], None]


class TickCollector:
    """Collects real-time ticks via Fyers WebSocket.

    This class manages the WebSocket lifecycle, tick validation,
    batching for database writes, and candle aggregation.

    Args:
        access_token: Fyers access token (format: 'client_id:token').
        symbols: Symbols to subscribe to. Defaults to INDEX_SYMBOLS.
        batch_interval: Seconds between batch flushes. Defaults to settings value.
        on_tick: Callback for each validated tick.
        on_candle: Callback when a 1-minute candle completes.
        on_batch: Callback when a tick batch is flushed.
    """

    def __init__(
        self,
        access_token: str,
        symbols: list[str] | None = None,
        batch_interval: int | None = None,
        on_tick: OnTickCallback | None = None,
        on_candle: OnCandleCallback | None = None,
        on_batch: OnBatchCallback | None = None,
    ) -> None:
        settings = get_settings()
        self._access_token = access_token
        self._symbols = symbols or list(INDEX_SYMBOLS)
        self._batch_interval = batch_interval or settings.tick_batch_insert_interval
        self._on_tick = on_tick
        self._on_candle = on_candle
        self._on_batch = on_batch

        self._ws = None  # FyersDataSocket instance
        self._running = False
        self._tick_buffer: list[dict[str, Any]] = []
        self._aggregators: dict[str, CandleAggregator] = {
            s: CandleAggregator(symbol=s) for s in self._symbols
        }
        self._last_flush_time: float = 0.0
        self.stats = TickCollectorStats()

    # =========================================================================
    # Lifecycle
    # =========================================================================

    def start(self) -> None:
        """Start the WebSocket connection and begin streaming.

        This is a blocking call — run in a thread or use start_async().
        """
        from fyers_apiv3.FyersWebsocket.data_ws import FyersDataSocket

        self._running = True
        self.stats.started_at = datetime.now(tz=IST)
        self._last_flush_time = time.monotonic()

        logger.info(
            "tick_collector_starting",
            symbols=self._symbols,
            batch_interval=self._batch_interval,
        )

        self._ws = FyersDataSocket(
            access_token=self._access_token,
            write_to_file=False,
            litemode=False,
            reconnect=True,
            on_message=self._handle_message,
            on_error=self._handle_error,
            on_connect=self._handle_connect,
            on_close=self._handle_close,
        )

        self._ws.connect()
        self._ws.subscribe(symbols=self._symbols)
        self._ws.keep_running()

    async def start_async(self) -> None:
        """Start the collector in an async context (runs blocking WS in thread)."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.start)

    def stop(self) -> None:
        """Gracefully stop the collector and flush remaining data."""
        logger.info("tick_collector_stopping")
        self._running = False

        # Flush remaining tick buffer
        self._flush_batch()

        # Flush in-progress candles
        for agg in self._aggregators.values():
            candle = agg.flush()
            if candle and self._on_candle:
                self._on_candle(candle)
                self.stats.candles_emitted += 1

        if self._ws:
            try:
                self._ws.close_connection()
            except Exception as exc:
                logger.warning("ws_close_error", error=str(exc))
            self._ws = None

        logger.info(
            "tick_collector_stopped",
            ticks=self.stats.ticks_received,
            candles=self.stats.candles_emitted,
            uptime=f"{self.stats.uptime_seconds:.0f}s",
        )

    # =========================================================================
    # WebSocket Callbacks
    # =========================================================================

    def _handle_message(self, message: Any) -> None:
        """Process an incoming WebSocket message."""
        try:
            tick = self._parse_tick(message)
            if tick is None:
                return

            self.stats.ticks_received += 1

            # Notify tick callback
            if self._on_tick:
                self._on_tick(tick)

            # Buffer for batch insert
            self._tick_buffer.append(tick.to_dict())

            # Aggregate into 1-min candles
            aggregator = self._aggregators.get(tick.symbol)
            if aggregator:
                candle = aggregator.add_tick(tick)
                if candle:
                    self.stats.candles_emitted += 1
                    if self._on_candle:
                        self._on_candle(candle)

            # Check if batch interval elapsed
            elapsed = time.monotonic() - self._last_flush_time
            if elapsed >= self._batch_interval:
                self._flush_batch()

        except Exception as exc:
            self.stats.errors += 1
            logger.error("tick_processing_error", error=str(exc))

    def _handle_error(self, error: Any) -> None:
        """Handle WebSocket errors."""
        self.stats.errors += 1
        logger.error("ws_error", error=str(error))

    def _handle_connect(self) -> None:
        """Handle successful WebSocket connection."""
        logger.info("ws_connected", symbols=self._symbols)

    def _handle_close(self) -> None:
        """Handle WebSocket disconnection."""
        self.stats.reconnections += 1
        logger.warning("ws_disconnected", reconnections=self.stats.reconnections)

    # =========================================================================
    # Tick Parsing & Validation
    # =========================================================================

    def _parse_tick(self, message: Any) -> Tick | None:
        """Parse a WebSocket message into a Tick, or None if invalid.

        Args:
            message: Raw message from FyersDataSocket.

        Returns:
            Validated Tick or None.
        """
        if not isinstance(message, dict):
            return None

        symbol = message.get("symbol")
        ltp = message.get("ltp")

        if not symbol or ltp is None:
            self.stats.ticks_invalid += 1
            return None

        if ltp <= 0:
            self.stats.ticks_invalid += 1
            logger.debug("invalid_tick_ltp", symbol=symbol, ltp=ltp)
            return None

        ts_raw = message.get("timestamp")
        if isinstance(ts_raw, (int, float)):
            timestamp = datetime.fromtimestamp(ts_raw, tz=IST)
        else:
            timestamp = datetime.now(tz=IST)

        return Tick(
            symbol=symbol,
            timestamp=timestamp,
            ltp=float(ltp),
            bid=message.get("bid"),
            ask=message.get("ask"),
            volume=int(message.get("vol_traded_today", 0)),
            open=message.get("open_price"),
            high=message.get("high_price"),
            low=message.get("low_price"),
            close=message.get("prev_close_price"),
        )

    # =========================================================================
    # Batch Flushing
    # =========================================================================

    def _flush_batch(self) -> None:
        """Flush the tick buffer to the batch callback."""
        if not self._tick_buffer:
            self._last_flush_time = time.monotonic()
            return

        batch = list(self._tick_buffer)
        self._tick_buffer.clear()
        self._last_flush_time = time.monotonic()
        self.stats.batches_flushed += 1

        logger.debug("batch_flushed", ticks=len(batch), batch_num=self.stats.batches_flushed)

        if self._on_batch:
            try:
                self._on_batch(batch)
            except Exception as exc:
                self.stats.errors += 1
                logger.error("batch_callback_error", error=str(exc))
