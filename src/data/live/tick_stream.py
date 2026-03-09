"""In-memory tick stream broker for WebSocket consumers."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any


class TickStreamBroker:
    """Thread-safe in-memory publish/subscribe broker for tick payloads."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subs: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._latest: dict[str, dict[str, Any]] = {}

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def latest(self, symbol: str) -> dict[str, Any] | None:
        return self._latest.get(symbol)

    def subscribe(self, symbol: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=500)
        self._subs[symbol].add(queue)
        return queue

    def unsubscribe(self, symbol: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        if symbol in self._subs and queue in self._subs[symbol]:
            self._subs[symbol].remove(queue)
            if not self._subs[symbol]:
                self._subs.pop(symbol, None)

    def publish(self, tick: dict[str, Any]) -> None:
        symbol = str(tick.get("symbol", ""))
        if not symbol:
            return
        self._latest[symbol] = tick
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._fanout, symbol, tick)

    def _fanout(self, symbol: str, tick: dict[str, Any]) -> None:
        for topic in (symbol, "*"):
            for queue in list(self._subs.get(topic, set())):
                if queue.full():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                queue.put_nowait(tick)

