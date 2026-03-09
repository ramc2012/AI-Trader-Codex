"""Agent event system — event types, dataclass, and async pub/sub bus.

Every decision point in the trading agent emits an AgentEvent.
The AgentEventBus distributes events to all subscribers (WebSocket,
Telegram, in-memory log) concurrently via asyncio queues.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Deque, Dict, List

from src.config.market_hours import IST


class AgentEventType(str, Enum):
    """All event types the trading agent can emit."""

    # Lifecycle
    AGENT_STARTED = "agent_started"
    AGENT_STOPPED = "agent_stopped"
    AGENT_PAUSED = "agent_paused"
    AGENT_RESUMED = "agent_resumed"
    AGENT_ERROR = "agent_error"

    # Market observation
    MARKET_SCAN = "market_scan"
    MARKET_DATA_RECEIVED = "market_data_received"
    MARKET_CLOSED = "market_closed"

    # Strategy analysis
    STRATEGY_ANALYZING = "strategy_analyzing"
    SIGNAL_GENERATED = "signal_generated"
    NO_SIGNAL = "no_signal"

    # Risk
    RISK_CHECK_PASSED = "risk_check_passed"
    RISK_CHECK_FAILED = "risk_check_failed"
    CIRCUIT_BREAKER = "circuit_breaker"

    # Execution
    ORDER_PLACING = "order_placing"
    ORDER_PLACED = "order_placed"
    ORDER_FILLED = "order_filled"
    ORDER_REJECTED = "order_rejected"

    # Position
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"
    POSITION_UPDATE = "position_update"

    # Summary
    DAILY_SUMMARY = "daily_summary"
    THINKING = "thinking"
    FRACTAL_SCAN_SUMMARY = "fractal_scan_summary"
    FRACTAL_CANDIDATE = "fractal_candidate"


@dataclass
class AgentEvent:
    """A single event emitted by the trading agent."""

    event_type: AgentEventType
    title: str
    message: str
    severity: str = "info"  # info | success | warning | error
    metadata: Dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: f"evt-{uuid.uuid4().hex[:12]}")
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=IST))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "title": self.title,
            "message": self.message,
            "severity": self.severity,
            "metadata": self.metadata,
        }

    def to_ws_payload(self) -> Dict[str, Any]:
        return {"type": "agent_event", **self.to_dict()}

    def to_telegram_text(self) -> str:
        """Format as Telegram HTML message."""
        if self.event_type == AgentEventType.FRACTAL_CANDIDATE:
            symbol = str(self.metadata.get("symbol", "UNKNOWN"))
            direction = str(self.metadata.get("direction", "")).upper()
            conviction = int(self.metadata.get("conviction", 0) or 0)
            shape = str(self.metadata.get("hourly_shape", ""))
            migration = int(self.metadata.get("consecutive_migration_hours", 0) or 0)
            entry = self.metadata.get("entry_trigger")
            stop = self.metadata.get("stop_reference")
            target = self.metadata.get("target_reference")
            contract = self.metadata.get("suggested_contract")
            rationale = str(self.metadata.get("rationale", "")).strip()

            lines = [f"\U0001f9ed <b>{symbol} {direction} fractal candidate</b>"]
            lines.append(f"Conviction: <b>{conviction}/100</b>")
            if shape:
                lines.append(f"Structure: {shape} · {migration}h migration")
            if entry is not None:
                lines.append(f"Entry: {entry}")
            if stop is not None:
                lines.append(f"Stop: {stop}")
            if target not in (None, ""):
                lines.append(f"Target: {target}")
            if contract:
                lines.append(f"Contract: {contract}")
            if rationale:
                lines.append(rationale)
            return "\n".join(lines)

        if self.event_type == AgentEventType.FRACTAL_SCAN_SUMMARY:
            scan_date = str(self.metadata.get("scan_date", ""))
            candidates_found = int(self.metadata.get("candidates_found", 0) or 0)
            symbols_scanned = int(self.metadata.get("symbols_scanned", 0) or 0)
            top_symbols = str(self.metadata.get("top_symbols", "")).strip()
            lines = ["\U0001f4ca <b>Fractal watchlist scan</b>"]
            if scan_date:
                lines.append(f"Date: {scan_date}")
            lines.append(f"Universe: {symbols_scanned}")
            lines.append(f"Candidates: <b>{candidates_found}</b>")
            if top_symbols:
                lines.append(f"Leaders: {top_symbols}")
            return "\n".join(lines)

        icon = {
            "info": "\u2139\ufe0f",
            "success": "\u2705",
            "warning": "\u26a0\ufe0f",
            "error": "\u274c",
        }.get(self.severity, "")
        lines = [f"{icon} <b>{self.title}</b>"]
        if self.message:
            lines.append(self.message)
        # Add key metadata pairs
        for key in (
            "market",
            "symbol",
            "underlying_symbol",
            "strategy",
            "side",
            "quantity",
            "price",
            "entry_price",
            "exit_price",
            "pnl",
            "reason",
        ):
            if key in self.metadata:
                label = key.replace("_", " ").title()
                lines.append(f"{label}: {self.metadata[key]}")
        return "\n".join(lines)


class AgentEventBus:
    """Async pub/sub bus for agent events.

    Subscribers receive events via asyncio.Queue instances.
    The bus also maintains an in-memory event log (bounded deque).
    """

    def __init__(self, max_history: int = 500) -> None:
        self._subscribers: List[asyncio.Queue[AgentEvent]] = []
        self._history: Deque[AgentEvent] = deque(maxlen=max_history)

    async def emit(self, event: AgentEvent) -> None:
        """Broadcast event to all subscribers and store in history."""
        self._history.append(event)
        for queue in self._subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Drop oldest to make room
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                queue.put_nowait(event)

    def subscribe(self, maxsize: int = 256) -> asyncio.Queue[AgentEvent]:
        """Create and return a new subscriber queue."""
        queue: asyncio.Queue[AgentEvent] = asyncio.Queue(maxsize=maxsize)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[AgentEvent]) -> None:
        """Remove a subscriber queue."""
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    def get_recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return the most recent events from history as dicts."""
        events = list(self._history)
        return [e.to_dict() for e in events[-limit:]]

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
