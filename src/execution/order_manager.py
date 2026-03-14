"""Order management system for trade execution.

Handles order lifecycle including placement, tracking, modification,
and cancellation. Supports both paper trading (simulated) and live
trading through the Fyers API.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.config.settings import get_settings
from src.config.market_hours import IST
from src.utils.exceptions import OrderError
from src.utils.logger import get_logger

logger = get_logger(__name__)


class OrderSide(Enum):
    """Side of an order."""

    BUY = 1
    SELL = -1


class OrderType(Enum):
    """Type of order."""

    MARKET = 1
    LIMIT = 2
    STOP = 3
    STOP_LIMIT = 4


class ProductType(Enum):
    """Product type for the order."""

    INTRADAY = "INTRADAY"
    CNC = "CNC"  # Cash and Carry (delivery)
    MARGIN = "MARGIN"


class OrderStatus(Enum):
    """Current status of an order."""

    PENDING = "pending"
    PLACED = "placed"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass
class Order:
    """Represents a trading order.

    Attributes:
        symbol: Trading symbol (e.g., 'NSE:NIFTY50-INDEX').
        quantity: Number of units to trade.
        side: Buy or sell.
        order_type: Market, limit, stop, or stop-limit.
        product_type: Intraday, CNC, or margin.
        limit_price: Limit price for limit/stop-limit orders.
        stop_price: Trigger price for stop/stop-limit orders.
        tag: Strategy tag for tracking which strategy placed this order.
        order_id: Unique identifier assigned after placement.
        status: Current order status.
        fill_price: Average fill price once executed.
        fill_quantity: Number of units filled so far.
        placed_at: Timestamp when order was placed.
        filled_at: Timestamp when order was fully filled.
        rejection_reason: Reason if the order was rejected.
    """

    symbol: str
    quantity: int
    side: OrderSide
    order_type: OrderType
    product_type: ProductType = ProductType.INTRADAY
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    market_price_hint: Optional[float] = None
    tag: str = ""

    # Set after placement
    order_id: Optional[str] = None
    status: OrderStatus = OrderStatus.PENDING
    fill_price: Optional[float] = None
    fill_quantity: int = 0
    placed_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None

    @property
    def is_buy(self) -> bool:
        """Whether this is a buy order."""
        return self.side == OrderSide.BUY

    @property
    def is_complete(self) -> bool:
        """Whether the order has reached a terminal state."""
        return self.status in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.FAILED,
        )

    @property
    def value(self) -> float:
        """Estimated or actual value of the order."""
        price = self.fill_price or self.limit_price or 0.0
        return price * self.quantity

    def to_fyers_params(self) -> Dict[str, Any]:
        """Convert to Fyers API order parameters.

        Returns:
            Dictionary of parameters suitable for FyersClient.place_order().
        """
        params: Dict[str, Any] = {
            "symbol": self.symbol,
            "qty": self.quantity,
            "type": self.order_type.value,
            "side": self.side.value,
            "productType": self.product_type.value,
        }
        if self.limit_price is not None:
            params["limitPrice"] = self.limit_price
        if self.stop_price is not None:
            params["stopPrice"] = self.stop_price
        return params


@dataclass
class OrderResult:
    """Result of an order operation.

    Attributes:
        success: Whether the operation succeeded.
        order_id: Order identifier if applicable.
        message: Human-readable result message.
        order: The Order object if applicable.
    """

    success: bool
    order_id: Optional[str] = None
    message: str = ""
    order: Optional[Order] = None


@dataclass
class BrokerOrderUpdateResult:
    """Delta returned after reconciling a broker order/trade event."""

    updated: bool
    order: Optional[Order] = None
    message: str = ""
    fill_delta_quantity: int = 0
    fill_delta_price: Optional[float] = None
    status_changed: bool = False


class OrderManager:
    """Manage order lifecycle -- placement, tracking, modification, cancellation.

    Supports paper mode (simulated execution) and live mode (Fyers API).
    Paper mode is the default for safe development and testing.

    Args:
        paper_mode: If True, simulate orders without hitting broker API.
    """

    def __init__(self, paper_mode: bool = True, state_path: Path | str | None = None) -> None:
        self.paper_mode = paper_mode
        self._orders: Dict[str, Order] = {}
        self._order_counter: int = 0
        self._fyers_client: Any = None
        self._seen_trade_ids: set[str] = set()
        if state_path is not None:
            self._state_path: Path | None = Path(state_path)
        elif os.environ.get("PYTEST_CURRENT_TEST"):
            self._state_path = None
        else:
            self._state_path = get_settings().data_path / "order_manager_state.json"
        self._load_state()
        logger.info(
            "order_manager_initialized",
            paper_mode=paper_mode,
        )

    def set_client(self, client: Any) -> None:
        """Set the Fyers client for live trading.

        Args:
            client: An instance of FyersClient.
        """
        self._fyers_client = client
        logger.info("fyers_client_set")

    # =========================================================================
    # Order Placement
    # =========================================================================

    def place_order(self, order: Order) -> OrderResult:
        """Place an order (paper or live).

        In paper mode, market orders are immediately filled at a simulated
        price. Limit and stop orders are set to 'placed' status and can be
        filled later via simulate_fill().

        In live mode, the order is sent to the Fyers API.

        Args:
            order: The Order to place.

        Returns:
            OrderResult indicating success or failure.

        Raises:
            OrderError: If live mode is used without a Fyers client set.
        """
        if order.quantity <= 0:
            return OrderResult(
                success=False,
                message="Order quantity must be positive.",
            )

        if self.paper_mode:
            return self._paper_place(order)

        return self._live_place(order)

    # =========================================================================
    # Order Cancellation
    # =========================================================================

    def cancel_order(self, order_id: str) -> OrderResult:
        """Cancel a pending or placed order.

        Filled, cancelled, rejected, and failed orders cannot be cancelled.

        Args:
            order_id: The unique order identifier.

        Returns:
            OrderResult indicating success or failure.
        """
        order = self._orders.get(order_id)
        if order is None:
            return OrderResult(
                success=False,
                message=f"Order {order_id} not found.",
            )

        if order.is_complete:
            return OrderResult(
                success=False,
                order_id=order_id,
                message=f"Cannot cancel order in '{order.status.value}' state.",
                order=order,
            )

        if self.paper_mode:
            return self._paper_cancel(order_id)

        return self._live_cancel(order_id)

    # =========================================================================
    # Order Modification
    # =========================================================================

    def modify_order(
        self,
        order_id: str,
        new_quantity: Optional[int] = None,
        new_limit_price: Optional[float] = None,
        new_stop_price: Optional[float] = None,
    ) -> OrderResult:
        """Modify an existing non-complete order.

        At least one modification parameter must be provided.

        Args:
            order_id: The unique order identifier.
            new_quantity: New order quantity if changing.
            new_limit_price: New limit price if changing.
            new_stop_price: New stop price if changing.

        Returns:
            OrderResult indicating success or failure.
        """
        order = self._orders.get(order_id)
        if order is None:
            return OrderResult(
                success=False,
                message=f"Order {order_id} not found.",
            )

        if order.is_complete:
            return OrderResult(
                success=False,
                order_id=order_id,
                message=f"Cannot modify order in '{order.status.value}' state.",
                order=order,
            )

        if new_quantity is None and new_limit_price is None and new_stop_price is None:
            return OrderResult(
                success=False,
                order_id=order_id,
                message="No modification parameters provided.",
                order=order,
            )

        if new_quantity is not None:
            if new_quantity <= 0:
                return OrderResult(
                    success=False,
                    order_id=order_id,
                    message="New quantity must be positive.",
                    order=order,
                )
            order.quantity = new_quantity

        if new_limit_price is not None:
            order.limit_price = new_limit_price

        if new_stop_price is not None:
            order.stop_price = new_stop_price

        logger.info(
            "order_modified",
            order_id=order_id,
            new_quantity=new_quantity,
            new_limit_price=new_limit_price,
            new_stop_price=new_stop_price,
        )
        self._persist_state()

        return OrderResult(
            success=True,
            order_id=order_id,
            message="Order modified successfully.",
            order=order,
        )

    # =========================================================================
    # Order Queries
    # =========================================================================

    def get_order(self, order_id: str) -> Optional[Order]:
        """Get an order by its unique identifier.

        Args:
            order_id: The unique order identifier.

        Returns:
            The Order if found, otherwise None.
        """
        return self._orders.get(order_id)

    def get_open_orders(self) -> List[Order]:
        """Get all orders that are not in a terminal state.

        Returns:
            List of non-complete orders.
        """
        return [o for o in self._orders.values() if not o.is_complete]

    def get_all_orders(self) -> List[Order]:
        """Get all orders (open and closed).

        Returns:
            List of all tracked orders.
        """
        return list(self._orders.values())

    def get_orders_by_symbol(self, symbol: str) -> List[Order]:
        """Get all orders for a specific symbol.

        Args:
            symbol: The trading symbol to filter by.

        Returns:
            List of orders matching the symbol.
        """
        return [o for o in self._orders.values() if o.symbol == symbol]

    def get_orders_by_tag(self, tag: str) -> List[Order]:
        """Get all orders with a specific strategy tag.

        Args:
            tag: The strategy tag to filter by.

        Returns:
            List of orders matching the tag.
        """
        return [o for o in self._orders.values() if o.tag == tag]

    def apply_broker_order_update(self, payload: Dict[str, Any]) -> BrokerOrderUpdateResult:
        """Reconcile a live broker order-status update against the local order book."""
        raw = payload.get("orders") if isinstance(payload, dict) else None
        if not isinstance(raw, dict):
            raw = payload
        if not isinstance(raw, dict):
            return BrokerOrderUpdateResult(updated=False, message="Invalid broker order payload.")

        order_id = str(raw.get("id") or raw.get("orderNumber") or "").strip()
        if not order_id:
            return BrokerOrderUpdateResult(updated=False, message="Broker order update missing order id.")

        order = self._orders.get(order_id)
        if order is None:
            return BrokerOrderUpdateResult(updated=False, message=f"Unknown order id: {order_id}.")

        previous_status = order.status
        previous_fill_quantity = int(order.fill_quantity or 0)
        previous_avg_fill_price = float(order.fill_price or 0.0)

        broker_quantity = self._safe_int(raw.get("qty"), fallback=order.quantity)
        if broker_quantity > 0:
            order.quantity = broker_quantity

        broker_filled_quantity = min(
            max(self._safe_int(raw.get("filledQty"), fallback=previous_fill_quantity), previous_fill_quantity),
            max(int(order.quantity or 0), previous_fill_quantity),
        )
        cumulative_avg_fill_price = self._safe_float(raw.get("tradedPrice"), fallback=order.fill_price)
        fill_delta_quantity = max(broker_filled_quantity - previous_fill_quantity, 0)
        fill_delta_price: Optional[float] = None

        if fill_delta_quantity > 0 and cumulative_avg_fill_price is not None and cumulative_avg_fill_price > 0:
            if previous_fill_quantity > 0 and previous_avg_fill_price > 0:
                fill_delta_value = (
                    float(cumulative_avg_fill_price) * broker_filled_quantity
                ) - (previous_avg_fill_price * previous_fill_quantity)
                fill_delta_price = fill_delta_value / max(fill_delta_quantity, 1)
            else:
                fill_delta_price = float(cumulative_avg_fill_price)

        if broker_filled_quantity > 0:
            order.fill_quantity = broker_filled_quantity
        if cumulative_avg_fill_price is not None and cumulative_avg_fill_price > 0:
            order.fill_price = float(cumulative_avg_fill_price)

        mapped_status = self._map_broker_status(
            raw_status=raw.get("status"),
            filled_quantity=order.fill_quantity,
            total_quantity=order.quantity,
            message=raw.get("message"),
        )
        if mapped_status is not None:
            order.status = mapped_status

        broker_message = str(raw.get("message") or "").strip()
        if order.status == OrderStatus.REJECTED:
            order.rejection_reason = broker_message or order.rejection_reason or "Broker rejected order."
        elif order.status == OrderStatus.CANCELLED and broker_message:
            order.rejection_reason = broker_message

        if order.fill_quantity >= int(order.quantity or 0) > 0:
            order.status = OrderStatus.FILLED
            if order.filled_at is None:
                order.filled_at = datetime.now(tz=IST)
        elif order.fill_quantity > 0 and order.status not in (OrderStatus.CANCELLED, OrderStatus.REJECTED):
            order.status = OrderStatus.PARTIALLY_FILLED

        status_changed = order.status != previous_status
        updated = status_changed or fill_delta_quantity > 0 or (
            broker_message and broker_message != str(order.rejection_reason or "")
        )
        if updated:
            self._persist_state()
            logger.info(
                "broker_order_reconciled",
                order_id=order_id,
                status=order.status.value,
                fill_quantity=order.fill_quantity,
                fill_delta_quantity=fill_delta_quantity,
            )

        return BrokerOrderUpdateResult(
            updated=updated,
            order=order,
            message=broker_message or f"Order status is {order.status.value}.",
            fill_delta_quantity=fill_delta_quantity,
            fill_delta_price=fill_delta_price,
            status_changed=status_changed,
        )

    def apply_broker_trade_update(self, payload: Dict[str, Any]) -> BrokerOrderUpdateResult:
        """Reconcile a live broker trade/fill event against the local order book."""
        raw = payload.get("trades") if isinstance(payload, dict) else None
        if not isinstance(raw, dict):
            raw = payload
        if not isinstance(raw, dict):
            return BrokerOrderUpdateResult(updated=False, message="Invalid broker trade payload.")

        order_id = str(raw.get("orderNumber") or raw.get("id") or "").strip()
        if not order_id:
            return BrokerOrderUpdateResult(updated=False, message="Broker trade update missing order id.")

        order = self._orders.get(order_id)
        if order is None:
            return BrokerOrderUpdateResult(updated=False, message=f"Unknown order id: {order_id}.")

        trade_id = str(raw.get("tradeNumber") or "").strip()
        if trade_id and trade_id in self._seen_trade_ids:
            return BrokerOrderUpdateResult(updated=False, order=order, message="Duplicate trade update ignored.")

        traded_quantity = self._safe_int(raw.get("tradedQty"), fallback=0)
        traded_price = self._safe_float(raw.get("tradePrice"), fallback=order.fill_price)
        if traded_quantity <= 0 or traded_price is None or traded_price <= 0:
            return BrokerOrderUpdateResult(updated=False, order=order, message="Trade payload missing quantity/price.")

        previous_fill_quantity = int(order.fill_quantity or 0)
        previous_avg_fill_price = float(order.fill_price or 0.0)
        applied_fill_quantity = min(
            traded_quantity,
            max(int(order.quantity or traded_quantity) - previous_fill_quantity, 0),
        )
        if trade_id:
            self._seen_trade_ids.add(trade_id)

        if applied_fill_quantity <= 0:
            return BrokerOrderUpdateResult(
                updated=False,
                order=order,
                message="Trade update was already reflected in cumulative fill quantity.",
            )

        new_fill_quantity = previous_fill_quantity + applied_fill_quantity
        if previous_fill_quantity > 0 and previous_avg_fill_price > 0:
            total_value = (previous_avg_fill_price * previous_fill_quantity) + (float(traded_price) * applied_fill_quantity)
            order.fill_price = total_value / max(new_fill_quantity, 1)
        else:
            order.fill_price = float(traded_price)
        order.fill_quantity = new_fill_quantity
        if order.fill_quantity >= int(order.quantity or 0) > 0:
            order.status = OrderStatus.FILLED
            order.filled_at = order.filled_at or datetime.now(tz=IST)
        else:
            order.status = OrderStatus.PARTIALLY_FILLED

        self._persist_state()
        logger.info(
            "broker_trade_reconciled",
            order_id=order_id,
            trade_id=trade_id or None,
            fill_quantity=order.fill_quantity,
            fill_delta_quantity=applied_fill_quantity,
            fill_delta_price=traded_price,
            status=order.status.value,
        )
        return BrokerOrderUpdateResult(
            updated=True,
            order=order,
            message="Trade update applied.",
            fill_delta_quantity=applied_fill_quantity,
            fill_delta_price=float(traded_price),
            status_changed=True,
        )

    # =========================================================================
    # Paper Trading Simulation
    # =========================================================================

    def _paper_place(self, order: Order) -> OrderResult:
        """Simulate order placement in paper mode.

        Market orders are immediately filled. Limit, stop, and stop-limit
        orders are placed but not filled until simulate_fill() is called.

        Args:
            order: The Order to simulate placing.

        Returns:
            OrderResult with the simulated outcome.
        """
        order_id = self._generate_order_id()
        order.order_id = order_id
        order.placed_at = datetime.now(tz=IST)

        if order.order_type == OrderType.MARKET:
            # Market orders fill immediately in paper mode using available price hints.
            fill_price = (
                order.market_price_hint
                if order.market_price_hint is not None
                else order.limit_price
            )
            if fill_price is None or fill_price <= 0:
                order.status = OrderStatus.REJECTED
                order.rejection_reason = (
                    "Market order requires market_price_hint or limit_price in paper mode."
                )
                logger.warning(
                    "paper_market_order_rejected_no_price",
                    order_id=order_id,
                    symbol=order.symbol,
                    side=order.side.name,
                )
            else:
                order.status = OrderStatus.FILLED
                order.fill_price = float(fill_price)
                order.fill_quantity = order.quantity
                order.filled_at = datetime.now(tz=IST)
                logger.info(
                    "paper_order_filled",
                    order_id=order_id,
                    symbol=order.symbol,
                    side=order.side.name,
                    quantity=order.quantity,
                    fill_price=order.fill_price,
                )
        else:
            # Limit/stop orders stay in placed status
            order.status = OrderStatus.PLACED
            logger.info(
                "paper_order_placed",
                order_id=order_id,
                symbol=order.symbol,
                side=order.side.name,
                order_type=order.order_type.name,
                quantity=order.quantity,
                limit_price=order.limit_price,
                stop_price=order.stop_price,
            )

        self._orders[order_id] = order
        self._persist_state()

        return OrderResult(
            success=True,
            order_id=order_id,
            message=f"Paper order {order.status.value}: {order.symbol}",
            order=order,
        )

    def _paper_cancel(self, order_id: str) -> OrderResult:
        """Simulate order cancellation in paper mode.

        Args:
            order_id: The order to cancel.

        Returns:
            OrderResult confirming cancellation.
        """
        order = self._orders[order_id]
        order.status = OrderStatus.CANCELLED
        self._persist_state()

        logger.info("paper_order_cancelled", order_id=order_id)

        return OrderResult(
            success=True,
            order_id=order_id,
            message=f"Paper order cancelled: {order_id}",
            order=order,
        )

    def simulate_fill(
        self,
        order_id: str,
        fill_price: float,
        fill_quantity: Optional[int] = None,
    ) -> OrderResult:
        """Manually simulate a fill for a paper-trading limit/stop order.

        Args:
            order_id: The order to fill.
            fill_price: The simulated fill price.
            fill_quantity: The quantity to fill. Defaults to the full order quantity.

        Returns:
            OrderResult indicating success or failure.
        """
        order = self._orders.get(order_id)
        if order is None:
            return OrderResult(
                success=False,
                message=f"Order {order_id} not found.",
            )

        if order.is_complete:
            return OrderResult(
                success=False,
                order_id=order_id,
                message=f"Cannot fill order in '{order.status.value}' state.",
                order=order,
            )

        qty = fill_quantity if fill_quantity is not None else order.quantity

        if qty <= 0:
            return OrderResult(
                success=False,
                order_id=order_id,
                message="Fill quantity must be positive.",
                order=order,
            )

        order.fill_price = fill_price
        order.fill_quantity = min(order.fill_quantity + qty, order.quantity)
        order.filled_at = datetime.now(tz=IST)

        if order.fill_quantity >= order.quantity:
            order.status = OrderStatus.FILLED
        else:
            order.status = OrderStatus.PARTIALLY_FILLED

        logger.info(
            "paper_order_simulated_fill",
            order_id=order_id,
            fill_price=fill_price,
            fill_quantity=qty,
            total_filled=order.fill_quantity,
            status=order.status.value,
        )
        self._persist_state()

        return OrderResult(
            success=True,
            order_id=order_id,
            message=f"Order {order.status.value} at {fill_price}",
            order=order,
        )

    # =========================================================================
    # Live Trading
    # =========================================================================

    def _live_place(self, order: Order) -> OrderResult:
        """Place an order via the Fyers API.

        Args:
            order: The Order to place.

        Returns:
            OrderResult with the broker response.

        Raises:
            OrderError: If no Fyers client is configured.
        """
        if self._fyers_client is None:
            raise OrderError(
                "Fyers client not set. Call set_client() before live trading."
            )

        order_id = self._generate_order_id()
        order.order_id = order_id
        order.placed_at = datetime.now(tz=IST)

        try:
            params = order.to_fyers_params()
            response = self._fyers_client.place_order(params)

            if response.get("s") == "ok":
                broker_id = response.get("id", order_id)
                order.order_id = str(broker_id)
                order.status = OrderStatus.PLACED
                self._orders[order.order_id] = order

                logger.info(
                    "live_order_placed",
                    order_id=order.order_id,
                    symbol=order.symbol,
                    side=order.side.name,
                )
                self._persist_state()

                return OrderResult(
                    success=True,
                    order_id=order.order_id,
                    message=f"Order placed: {order.symbol}",
                    order=order,
                )
            else:
                msg = response.get("message", "Unknown error")
                order.status = OrderStatus.REJECTED
                order.rejection_reason = msg
                self._orders[order_id] = order

                logger.warning(
                    "live_order_rejected",
                    order_id=order_id,
                    reason=msg,
                )
                self._persist_state()

                return OrderResult(
                    success=False,
                    order_id=order_id,
                    message=f"Order rejected: {msg}",
                    order=order,
                )

        except Exception as exc:
            order.status = OrderStatus.FAILED
            order.rejection_reason = str(exc)
            self._orders[order_id] = order

            logger.error(
                "live_order_failed",
                order_id=order_id,
                error=str(exc),
            )
            self._persist_state()

            return OrderResult(
                success=False,
                order_id=order_id,
                message=f"Order failed: {exc}",
                order=order,
            )

    def _live_cancel(self, order_id: str) -> OrderResult:
        """Cancel an order via the Fyers API.

        Args:
            order_id: The order to cancel.

        Returns:
            OrderResult with the broker response.

        Raises:
            OrderError: If no Fyers client is configured.
        """
        if self._fyers_client is None:
            raise OrderError(
                "Fyers client not set. Call set_client() before live trading."
            )

        order = self._orders[order_id]

        try:
            response = self._fyers_client.cancel_order(order_id)

            if response.get("s") == "ok":
                order.status = OrderStatus.CANCELLED
                logger.info("live_order_cancelled", order_id=order_id)
                self._persist_state()
                return OrderResult(
                    success=True,
                    order_id=order_id,
                    message=f"Order cancelled: {order_id}",
                    order=order,
                )
            else:
                msg = response.get("message", "Cancel failed")
                logger.warning(
                    "live_cancel_failed",
                    order_id=order_id,
                    reason=msg,
                )
                return OrderResult(
                    success=False,
                    order_id=order_id,
                    message=f"Cancel failed: {msg}",
                    order=order,
                )

        except Exception as exc:
            logger.error(
                "live_cancel_error",
                order_id=order_id,
                error=str(exc),
            )
            return OrderResult(
                success=False,
                order_id=order_id,
                message=f"Cancel error: {exc}",
                order=order,
            )

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    def _generate_order_id(self) -> str:
        """Generate a unique paper order ID.

        Returns:
            A unique string identifier like 'PAPER-001'.
        """
        self._order_counter += 1
        return f"PAPER-{self._order_counter:04d}"

    @staticmethod
    def _safe_int(value: Any, fallback: int = 0) -> int:
        try:
            if value in (None, ""):
                return int(fallback)
            return int(float(value))
        except (TypeError, ValueError):
            return int(fallback)

    @staticmethod
    def _safe_float(value: Any, fallback: Optional[float] = None) -> Optional[float]:
        try:
            if value in (None, ""):
                return fallback
            return float(value)
        except (TypeError, ValueError):
            return fallback

    def _map_broker_status(
        self,
        *,
        raw_status: Any,
        filled_quantity: int,
        total_quantity: int,
        message: Any,
    ) -> Optional[OrderStatus]:
        if total_quantity > 0 and filled_quantity >= total_quantity:
            return OrderStatus.FILLED
        if filled_quantity > 0:
            return OrderStatus.PARTIALLY_FILLED

        token = str(raw_status or "").strip()
        token_upper = token.upper()
        message_upper = str(message or "").strip().upper()

        if "REJECT" in token_upper or "REJECT" in message_upper:
            return OrderStatus.REJECTED
        if "CANCEL" in token_upper or "CANCEL" in message_upper:
            return OrderStatus.CANCELLED
        if any(keyword in token_upper for keyword in ("FILL", "TRADE", "COMPLETE", "EXECUT")):
            return OrderStatus.FILLED
        if "PART" in token_upper:
            return OrderStatus.PARTIALLY_FILLED
        if any(keyword in token_upper for keyword in ("PEND", "TRANSIT", "OPEN")):
            return OrderStatus.PLACED

        numeric_map = {
            "1": OrderStatus.CANCELLED,
            "2": OrderStatus.FILLED,
            "4": OrderStatus.PLACED,
            "5": OrderStatus.REJECTED,
            "6": OrderStatus.PLACED,
            "7": OrderStatus.CANCELLED,
            "8": OrderStatus.REJECTED,
            "9": OrderStatus.PARTIALLY_FILLED,
        }
        if token in numeric_map:
            return numeric_map[token]

        return None

    def _persist_state(self) -> None:
        if self._state_path is None:
            return
        try:
            payload = {
                "order_counter": int(self._order_counter),
                "orders": [self._serialize_order(order) for order in self.get_all_orders()],
            }
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._state_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
            tmp_path.replace(self._state_path)
        except Exception as exc:
            logger.warning("order_manager_persist_failed", error=str(exc))

    def _load_state(self) -> None:
        if self._state_path is None or not self._state_path.exists():
            return
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
            self._order_counter = int(payload.get("order_counter", 0) or 0)
            self._orders = {}
            for raw in payload.get("orders", []):
                order = self._deserialize_order(raw)
                if order.order_id:
                    self._orders[order.order_id] = order
            logger.info("order_manager_state_loaded", orders=len(self._orders))
        except Exception as exc:
            logger.warning("order_manager_state_load_failed", error=str(exc))

    @staticmethod
    def _serialize_order(order: Order) -> dict[str, Any]:
        return {
            "symbol": order.symbol,
            "quantity": int(order.quantity),
            "side": order.side.name,
            "order_type": order.order_type.name,
            "product_type": order.product_type.value,
            "limit_price": order.limit_price,
            "stop_price": order.stop_price,
            "market_price_hint": order.market_price_hint,
            "tag": order.tag,
            "order_id": order.order_id,
            "status": order.status.value,
            "fill_price": order.fill_price,
            "fill_quantity": int(order.fill_quantity),
            "placed_at": order.placed_at.isoformat() if order.placed_at else None,
            "filled_at": order.filled_at.isoformat() if order.filled_at else None,
            "rejection_reason": order.rejection_reason,
        }

    @staticmethod
    def _deserialize_order(payload: dict[str, Any]) -> Order:
        return Order(
            symbol=str(payload.get("symbol") or ""),
            quantity=int(payload.get("quantity") or 0),
            side=OrderSide[str(payload.get("side") or "BUY")],
            order_type=OrderType[str(payload.get("order_type") or "MARKET")],
            product_type=ProductType(str(payload.get("product_type") or ProductType.INTRADAY.value)),
            limit_price=payload.get("limit_price"),
            stop_price=payload.get("stop_price"),
            market_price_hint=payload.get("market_price_hint"),
            tag=str(payload.get("tag") or ""),
            order_id=payload.get("order_id"),
            status=OrderStatus(str(payload.get("status") or OrderStatus.PENDING.value)),
            fill_price=payload.get("fill_price"),
            fill_quantity=int(payload.get("fill_quantity") or 0),
            placed_at=(
                datetime.fromisoformat(str(payload["placed_at"]))
                if payload.get("placed_at")
                else None
            ),
            filled_at=(
                datetime.fromisoformat(str(payload["filled_at"]))
                if payload.get("filled_at")
                else None
            ),
            rejection_reason=payload.get("rejection_reason"),
        )
