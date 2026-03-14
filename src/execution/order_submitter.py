"""Async gateway for serialized live order submission."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import time
from typing import Any, Dict, Optional

from src.config.market_hours import IST
from src.data.live.tick_stream import TickStreamBroker
from src.execution.order_manager import Order, OrderManager, OrderResult
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class _SubmissionRequest:
    submission_id: str
    order: Order
    submitted_at: datetime
    metadata: Dict[str, Any]


@dataclass
class OrderSubmitterStats:
    enqueued: int = 0
    completed: int = 0
    rejected: int = 0
    errors: int = 0
    queue_depth: int = 0
    started_at: Optional[datetime] = None


class OrderSubmitter:
    """Serialize live broker submissions through a dedicated async queue."""

    def __init__(
        self,
        order_manager: OrderManager,
        *,
        max_queue_size: int = 128,
        result_broker: TickStreamBroker | None = None,
    ) -> None:
        self._order_manager = order_manager
        self._max_queue_size = max(int(max_queue_size), 1)
        self._queue: asyncio.Queue[_SubmissionRequest] = asyncio.Queue(maxsize=self._max_queue_size)
        self._result_broker = result_broker or TickStreamBroker()
        self._worker_task: asyncio.Task[None] | None = None
        self._running = False
        self.stats = OrderSubmitterStats()

    @property
    def result_broker(self) -> TickStreamBroker:
        return self._result_broker

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.stats.started_at = datetime.now(tz=IST)
        self._result_broker.bind_loop(asyncio.get_running_loop())
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("order_submitter_started", max_queue_size=self._max_queue_size)

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._worker_task is not None and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        self._worker_task = None
        self.stats.queue_depth = int(self._queue.qsize())
        logger.info(
            "order_submitter_stopped",
            enqueued=self.stats.enqueued,
            completed=self.stats.completed,
            rejected=self.stats.rejected,
            errors=self.stats.errors,
        )

    async def submit(
        self,
        *,
        submission_id: str,
        order: Order,
        metadata: Dict[str, Any] | None = None,
    ) -> bool:
        if not self._running:
            await self.start()
        request = _SubmissionRequest(
            submission_id=str(submission_id or "").strip(),
            order=order,
            submitted_at=datetime.now(tz=IST),
            metadata=dict(metadata or {}),
        )
        if not request.submission_id:
            request.submission_id = f"submit-{int(time.time() * 1000)}"

        if self._queue.full():
            self.stats.rejected += 1
            self.stats.queue_depth = int(self._queue.qsize())
            logger.warning("order_submitter_queue_full", symbol=order.symbol, queue_depth=self.stats.queue_depth)
            return False

        self._queue.put_nowait(request)
        self.stats.enqueued += 1
        self.stats.queue_depth = int(self._queue.qsize())
        return True

    def snapshot(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "max_queue_size": self._max_queue_size,
            "queue_depth": int(self._queue.qsize()),
            "enqueued": self.stats.enqueued,
            "completed": self.stats.completed,
            "rejected": self.stats.rejected,
            "errors": self.stats.errors,
        }

    async def _worker_loop(self) -> None:
        while self._running:
            request = await self._queue.get()
            self.stats.queue_depth = int(self._queue.qsize())
            started = time.perf_counter()
            try:
                result = await asyncio.to_thread(self._order_manager.place_order, request.order)
                if result.success:
                    self.stats.completed += 1
                else:
                    self.stats.rejected += 1
                self._publish_result(request, result, latency_ms=(time.perf_counter() - started) * 1000.0)
            except Exception as exc:
                self.stats.errors += 1
                logger.error(
                    "order_submitter_worker_failed",
                    submission_id=request.submission_id,
                    symbol=request.order.symbol,
                    error=str(exc),
                )
                self._publish_result(
                    request,
                    OrderResult(success=False, message=f"Order submit failed: {exc}", order=request.order),
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                )

    def _publish_result(
        self,
        request: _SubmissionRequest,
        result: OrderResult,
        *,
        latency_ms: float,
    ) -> None:
        order = result.order or request.order
        self._result_broker.publish(
            {
                "type": "order_submission_result",
                "symbol": order.symbol,
                "timestamp": datetime.now(tz=IST).isoformat(),
                "submission_id": request.submission_id,
                "success": bool(result.success),
                "message": result.message,
                "latency_ms": round(float(latency_ms), 3),
                "metadata": request.metadata,
                "order_id": str(result.order_id or order.order_id or ""),
                "status": getattr(order.status, "value", ""),
                "fill_price": order.fill_price,
                "fill_quantity": int(order.fill_quantity or 0),
                "rejection_reason": order.rejection_reason,
                "order_snapshot": {
                    "symbol": order.symbol,
                    "quantity": int(order.quantity),
                    "side": order.side.name,
                    "order_type": order.order_type.name,
                    "product_type": order.product_type.value,
                    "limit_price": order.limit_price,
                    "stop_price": order.stop_price,
                    "market_price_hint": order.market_price_hint,
                    "tag": order.tag,
                    "order_id": str(order.order_id or ""),
                    "status": getattr(order.status, "value", ""),
                    "fill_price": order.fill_price,
                    "fill_quantity": int(order.fill_quantity or 0),
                    "rejection_reason": order.rejection_reason,
                    "placed_at": order.placed_at.isoformat() if order.placed_at is not None else None,
                    "filled_at": order.filled_at.isoformat() if order.filled_at is not None else None,
                },
            }
        )
