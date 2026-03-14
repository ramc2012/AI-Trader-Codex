"""Live broker order/trade socket collector."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from src.config.market_hours import IST
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class OrderSocketCollectorStats:
    """Runtime statistics for broker order socket ingestion."""

    orders_received: int = 0
    trades_received: int = 0
    positions_received: int = 0
    general_received: int = 0
    errors: int = 0
    started_at: datetime | None = None

    @property
    def uptime_seconds(self) -> float:
        if self.started_at is None:
            return 0.0
        return (datetime.now(tz=IST) - self.started_at).total_seconds()


OnOrderSocketEvent = Callable[[dict[str, Any]], None]


class OrderSocketCollector:
    """Collect broker order/trade events via the FYERS order socket."""

    def __init__(
        self,
        access_token: str,
        *,
        subscriptions: str = "OnOrders,OnTrades,OnPositions",
        on_event: OnOrderSocketEvent | None = None,
    ) -> None:
        self._access_token = access_token
        self._subscriptions = subscriptions
        self._on_event = on_event
        self._ws: Any = None
        self._running = False
        self.stats = OrderSocketCollectorStats()

    def start(self) -> None:
        """Start the blocking broker socket collector."""
        from fyers_apiv3.FyersWebsocket.order_ws import FyersOrderSocket

        self._running = True
        self.stats.started_at = datetime.now(tz=IST)
        logger.info("order_socket_collector_starting", subscriptions=self._subscriptions)
        while self._running:
            try:
                self._ws = FyersOrderSocket(
                    access_token=self._access_token,
                    write_to_file=False,
                    on_trades=lambda payload: self._handle_event("trade", payload),
                    on_positions=lambda payload: self._handle_event("position", payload),
                    on_orders=lambda payload: self._handle_event("order", payload),
                    on_general=lambda payload: self._handle_event("general", payload),
                    on_error=self._handle_error,
                    on_connect=self._handle_connect,
                    on_close=self._handle_close,
                    reconnect=True,
                    reconnect_retry=50,
                )
                self._ws.connect()
                self._ws.keep_running()

                while self._running:
                    time.sleep(0.5)
            except Exception as exc:
                self._handle_error(exc)
                if self._running:
                    time.sleep(2)
            finally:
                self._ws = None

    async def start_async(self) -> None:
        """Run the blocking collector on a worker thread."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.start)

    def stop(self) -> None:
        """Stop the collector and close the broker socket."""
        logger.info("order_socket_collector_stopping")
        self._running = False
        if self._ws is not None:
            try:
                self._ws.stop_running()
            except Exception as exc:
                logger.debug("order_socket_stop_running_failed", error=str(exc))
            try:
                self._ws.close_connection()
            except Exception as exc:
                logger.debug("order_socket_close_failed", error=str(exc))
            self._ws = None
        logger.info(
            "order_socket_collector_stopped",
            orders=self.stats.orders_received,
            trades=self.stats.trades_received,
            uptime=f"{self.stats.uptime_seconds:.0f}s",
        )

    def _handle_connect(self) -> None:
        if self._ws is None:
            return
        try:
            self._ws.subscribe(self._subscriptions)
            logger.info("order_socket_connected", subscriptions=self._subscriptions)
        except Exception as exc:
            self._handle_error(exc)

    def _handle_close(self, payload: dict[str, Any]) -> None:
        logger.info("order_socket_closed", payload=payload)

    def _handle_error(self, error: Any) -> None:
        self.stats.errors += 1
        logger.warning("order_socket_error", error=str(error))

    def _handle_event(self, event_kind: str, payload: Any) -> None:
        if not isinstance(payload, dict):
            payload = {"payload": payload}

        if event_kind == "order":
            self.stats.orders_received += 1
        elif event_kind == "trade":
            self.stats.trades_received += 1
        elif event_kind == "position":
            self.stats.positions_received += 1
        else:
            self.stats.general_received += 1

        normalized = self._normalize_event(event_kind, payload)
        if self._on_event is not None:
            self._on_event(normalized)

    @staticmethod
    def _normalize_event(event_kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        inner_key = {
            "order": "orders",
            "trade": "trades",
            "position": "positions",
        }.get(event_kind)
        inner = payload.get(inner_key) if inner_key else payload
        if not isinstance(inner, dict):
            inner = {}

        symbol = str(inner.get("symbol") or "__broker__")
        return {
            "type": "broker_event",
            "event_kind": event_kind,
            "symbol": symbol,
            "timestamp": datetime.now(tz=IST).isoformat(),
            "order_id": str(inner.get("id") or inner.get("orderNumber") or ""),
            "trade_id": str(inner.get("tradeNumber") or ""),
            "status": inner.get("status"),
            "payload": payload,
        }
