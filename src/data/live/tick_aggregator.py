"""Real-time tick → footprint bar aggregator.

Subscribes to TickStreamBroker and maintains per-symbol FootprintBar
state at configurable bar_minutes resolutions. Pushes update payloads
to registered asyncio.Queue subscribers (one per WS client).

Footprint bar: price → {bid_vol, ask_vol, delta} within each time bucket.
Direction heuristic: ltp >= ask → aggressive buy, ltp <= bid → aggressive sell.
"""

from __future__ import annotations

import asyncio
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from src.config.market_hours import IST
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ─── Price-level data ────────────────────────────────────────────────────────


class FootprintLevel:
    __slots__ = ("bid_vol", "ask_vol")

    def __init__(self) -> None:
        self.bid_vol: float = 0.0
        self.ask_vol: float = 0.0

    @property
    def delta(self) -> float:
        return self.ask_vol - self.bid_vol

    def to_dict(self) -> dict[str, float]:
        return {
            "bid": round(self.bid_vol),
            "ask": round(self.ask_vol),
            "delta": round(self.delta),
            "total": round(self.bid_vol + self.ask_vol),
        }


# ─── One time-bucket bar ─────────────────────────────────────────────────────


class FootprintBar:
    """Footprint candle for one time bucket (e.g., 5-minute bar)."""

    def __init__(
        self,
        symbol: str,
        open_time: datetime,
        bar_minutes: int,
        tick_size: float = 50.0,
    ) -> None:
        self.symbol = symbol
        self.open_time = open_time
        self.bar_minutes = bar_minutes
        self.tick_size = tick_size
        self.close_time = open_time + timedelta(minutes=bar_minutes)

        self.open: float | None = None
        self.high: float = -math.inf
        self.low: float = math.inf
        self.close: float | None = None
        self.volume: float = 0.0
        self.delta: float = 0.0

        self.levels: dict[float, FootprintLevel] = {}

    def _round_price(self, price: float) -> float:
        return round(price / self.tick_size) * self.tick_size

    def update(
        self,
        ltp: float,
        vol_delta: float,
        bid: float | None,
        ask: float | None,
    ) -> None:
        if self.open is None:
            self.open = ltp
        self.high = max(self.high, ltp)
        self.low = min(self.low, ltp)
        self.close = ltp
        self.volume += vol_delta

        rounded = self._round_price(ltp)
        level = self.levels.setdefault(rounded, FootprintLevel())

        if bid is not None and ask is not None:
            if ltp >= ask:          # aggressive buy
                level.ask_vol += vol_delta
                self.delta += vol_delta
            elif ltp <= bid:        # aggressive sell
                level.bid_vol += vol_delta
                self.delta -= vol_delta
            else:                   # inside spread — split evenly
                half = vol_delta / 2
                level.ask_vol += half
                level.bid_vol += half
                # delta stays neutral
        else:
            half = vol_delta / 2
            level.ask_vol += half
            level.bid_vol += half

    @property
    def is_expired(self) -> bool:
        return datetime.now(IST) >= self.close_time

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "open_time": self.open_time.isoformat(),
            "close_time": self.close_time.isoformat(),
            "bar_minutes": self.bar_minutes,
            "open": self.open,
            "high": self.high if self.high != -math.inf else None,
            "low": self.low if self.low != math.inf else None,
            "close": self.close,
            "volume": round(self.volume),
            "delta": round(self.delta),
            "levels": {
                str(p): lv.to_dict() for p, lv in sorted(self.levels.items())
            },
        }


# ─── Aggregator ──────────────────────────────────────────────────────────────


class RealTimeAggregator:
    """Aggregates live ticks from TickStreamBroker into footprint bars.

    Call ``start()`` once after the runtime manager has authenticated and
    the tick broker is bound to the event loop.
    """

    _DEFAULT_RESOLUTIONS = (1, 3, 5, 15)

    def __init__(self, broker: Any) -> None:  # TickStreamBroker
        self._broker = broker
        self._running = False
        self._task: asyncio.Task | None = None  # type: ignore[type-arg]
        self._persist_task: asyncio.Task | None = None  # type: ignore[type-arg]

        # symbol → bar_minutes → current bar
        self._bars: dict[str, dict[int, FootprintBar]] = defaultdict(dict)
        # symbol → last cumulative volume seen
        self._last_vol: dict[str, float] = {}
        # (symbol, bar_minutes) → subscriber queues
        self._subs: dict[tuple[str, int], set[asyncio.Queue]] = defaultdict(set)
        # completed bar history: (symbol, bar_minutes) → list of bar dicts
        self._history: dict[tuple[str, int], list[dict]] = defaultdict(list)
        # Batched persistence of raw ticks into TimescaleDB.
        self._tick_buffer: list[dict[str, Any]] = []
        self._persist_batch_size = 1000
        self._persist_interval_seconds = 3.0
        self._session_factory: Any | None = None

    # ─── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        queue = self._broker.subscribe("*")
        self._task = asyncio.create_task(self._consume(queue))
        self._persist_task = asyncio.create_task(self._persist_loop())
        logger.info("realtime_aggregator_started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._persist_task:
            self._persist_task.cancel()
            try:
                await self._persist_task
            except asyncio.CancelledError:
                pass
        await self._flush_ticks(force=True)
        logger.info("realtime_aggregator_stopped")

    # ─── Subscription API (for WS endpoints) ────────────────────────────────

    def subscribe(self, symbol: str, bar_minutes: int) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=300)
        self._subs[(symbol, bar_minutes)].add(q)
        return q

    def unsubscribe(self, symbol: str, bar_minutes: int, q: asyncio.Queue) -> None:
        self._subs[(symbol, bar_minutes)].discard(q)

    def get_current_bar(self, symbol: str, bar_minutes: int) -> dict | None:
        bar = self._bars.get(symbol, {}).get(bar_minutes)
        return bar.to_dict() if bar else None

    def get_history(
        self, symbol: str, bar_minutes: int, count: int = 100
    ) -> list[dict]:
        hist = self._history[(symbol, bar_minutes)][-count:]
        current = self.get_current_bar(symbol, bar_minutes)
        return hist + ([current] if current else [])

    def prime_from_latest(self, symbol: str) -> bool:
        """Seed aggregator state from the broker's last tick for instant UI load."""
        latest = self._broker.latest(symbol)
        if not latest:
            return False
        self._process_tick(latest)
        return True

    # ─── Internal ────────────────────────────────────────────────────────────

    async def _consume(self, queue: asyncio.Queue) -> None:
        while self._running:
            try:
                tick = await asyncio.wait_for(queue.get(), timeout=5.0)
                self._process_tick(tick)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("aggregator_error", error=str(exc))

    def _process_tick(self, tick: dict) -> None:
        symbol: str = str(tick.get("symbol", ""))
        ltp = tick.get("ltp")
        if not symbol or ltp is None:
            return

        ltp = float(ltp)
        # Collector now publishes per-tick delta volume in `volume` and optional
        # cumulative day volume in `cumulative_volume`. Support both formats.
        cumulative = tick.get("cumulative_volume")
        if cumulative is not None:
            cum_vol = float(cumulative or 0)
            prev_vol = self._last_vol.get(symbol, cum_vol)
            vol_delta = max(0.0, cum_vol - prev_vol)
            self._last_vol[symbol] = cum_vol
        else:
            vol_delta = max(0.0, float(tick.get("volume", 0) or 0))

        bid: float | None = tick.get("bid")
        ask: float | None = tick.get("ask")
        if bid is not None:
            bid = float(bid)
        if ask is not None:
            ask = float(ask)

        self._enqueue_tick(
            tick=tick,
            symbol=symbol,
            ltp=ltp,
            bid=bid,
            ask=ask,
            volume=vol_delta,
        )

        # Determine which resolutions are active (subscribed + defaults)
        active = {bm for (sym, bm) in self._subs if sym == symbol}
        active.update(self._DEFAULT_RESOLUTIONS)

        for bm in active:
            bar = self._get_or_create_bar(symbol, bm)
            if bar.is_expired:
                completed = bar.to_dict()
                hist = self._history[(symbol, bm)]
                hist.append(completed)
                if len(hist) > 200:
                    self._history[(symbol, bm)] = hist[-200:]
                bar = self._create_bar(symbol, bm)

            if vol_delta > 0 or bar.open is None:
                bar.update(ltp, vol_delta, bid, ask)

            # Push to subscribers
            subs = self._subs.get((symbol, bm), set())
            if not subs:
                continue
            payload = {
                "type": "orderflow_update",
                "bar": bar.to_dict(),
            }
            for q in list(subs):
                if q.full():
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                q.put_nowait(payload)

    def _enqueue_tick(
        self,
        tick: dict[str, Any],
        symbol: str,
        ltp: float,
        bid: float | None,
        ask: float | None,
        volume: float,
    ) -> None:
        ts_raw = tick.get("timestamp")
        if isinstance(ts_raw, datetime):
            ts = ts_raw
        elif isinstance(ts_raw, str):
            try:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            except ValueError:
                ts = datetime.now(timezone.utc)
        else:
            ts = datetime.now(timezone.utc)

        if ts.tzinfo is not None:
            ts = ts.astimezone(timezone.utc).replace(tzinfo=None)

        self._tick_buffer.append(
            {
                "symbol": symbol,
                "timestamp": ts,
                "ltp": float(ltp),
                "bid": float(bid) if bid is not None else None,
                "ask": float(ask) if ask is not None else None,
                "volume": max(int(volume), 0),
                "open": float(ltp),
                "high": float(ltp),
                "low": float(ltp),
                "close": float(ltp),
            }
        )

    async def _persist_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._persist_interval_seconds)
                await self._flush_ticks()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("tick_persist_loop_error", error=str(exc))

    async def _flush_ticks(self, force: bool = False) -> None:
        if not self._tick_buffer:
            return

        if self._session_factory is None:
            from src.database.connection import get_session_factory
            self._session_factory = get_session_factory()
        from src.database.operations import insert_ticks

        while self._tick_buffer:
            size = self._persist_batch_size if len(self._tick_buffer) > self._persist_batch_size else len(self._tick_buffer)
            chunk = self._tick_buffer[:size]
            del self._tick_buffer[:size]
            session = self._session_factory()
            try:
                inserted = await insert_ticks(session, chunk)
                await session.commit()
                logger.debug("tick_batch_persisted", rows=inserted)
            except Exception as exc:
                await session.rollback()
                logger.warning("tick_batch_persist_failed", error=str(exc), rows=len(chunk))
            finally:
                await session.close()

    def _get_or_create_bar(self, symbol: str, bm: int) -> FootprintBar:
        bar = self._bars.get(symbol, {}).get(bm)
        if bar is None:
            bar = self._create_bar(symbol, bm)
        return bar

    def _create_bar(self, symbol: str, bm: int) -> FootprintBar:
        now = datetime.now(IST)
        total_min = now.hour * 60 + now.minute
        slot = (total_min // bm) * bm
        open_time = now.replace(
            hour=slot // 60, minute=slot % 60, second=0, microsecond=0
        )
        bar = FootprintBar(symbol, open_time, bm)
        self._bars.setdefault(symbol, {})[bm] = bar
        return bar
