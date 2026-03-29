"""Lightweight async pub/sub bus for internal state change signaling."""

import asyncio
from typing import Any, Dict, List, Set


class StateChangeBus:
    """Async bus for signaling high-level state changes.
    
    Used to trigger WebSocket broadcasts when data in managers changes,
    eliminating the need for interval-based polling.
    """

    def __init__(self) -> None:
        self._subscribers: Set[asyncio.Queue[str]] = set()

    def subscribe(self) -> asyncio.Queue[str]:
        """Create a new subscriber queue."""
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=10)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str]) -> None:
        """Remove a subscriber queue."""
        self._subscribers.discard(queue)

    def notify(self, topic: str) -> None:
        """Notify all subscribers that a topic has changed.
        
        Topics can be: 'portfolio', 'positions', 'risk', 'alerts', etc.
        """
        for queue in self._subscribers:
            try:
                queue.put_nowait(topic)
            except asyncio.QueueFull:
                # Clear oldest if full
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                queue.put_nowait(topic)


# Global singleton for the API process
_global_bus = StateChangeBus()


def get_state_change_bus() -> StateChangeBus:
    """Returns the process-wide state change bus."""
    return _global_bus
