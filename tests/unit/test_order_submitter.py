"""Tests for the async order submitter."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from src.execution.order_manager import Order, OrderResult, OrderSide, OrderStatus, OrderType
from src.execution.order_submitter import OrderSubmitter


@pytest.mark.asyncio
async def test_order_submitter_publishes_success_result() -> None:
    order_manager = MagicMock()
    placed_order = Order(
        symbol="NSE:NIFTY",
        quantity=10,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
    )
    placed_order.order_id = "LIVE-1"
    placed_order.status = OrderStatus.PLACED
    order_manager.place_order.return_value = OrderResult(
        success=True,
        order_id="LIVE-1",
        message="ok",
        order=placed_order,
    )

    submitter = OrderSubmitter(order_manager=order_manager, max_queue_size=4)
    await submitter.start()
    queue = submitter.result_broker.subscribe("*")

    accepted = await submitter.submit(
        submission_id="sub-1",
        order=Order(
            symbol="NSE:NIFTY",
            quantity=10,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
        ),
        metadata={"kind": "entry"},
    )
    payload = await asyncio.wait_for(queue.get(), timeout=1.0)

    assert accepted is True
    assert payload["submission_id"] == "sub-1"
    assert payload["success"] is True
    assert payload["order_id"] == "LIVE-1"
    assert payload["status"] == OrderStatus.PLACED.value
    assert payload["metadata"]["kind"] == "entry"
    assert submitter.snapshot()["completed"] == 1

    submitter.result_broker.unsubscribe("*", queue)
    await submitter.stop()
