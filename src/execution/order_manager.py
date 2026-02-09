"""Order management system for trade execution.

Handles order lifecycle including placement, tracking, modification,
and cancellation. Supports both paper trading (simulated) and live
trading through the Fyers API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

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


class OrderManager:
    """Manage order lifecycle -- placement, tracking, modification, cancellation.

    Supports paper mode (simulated execution) and live mode (Fyers API).
    Paper mode is the default for safe development and testing.

    Args:
        paper_mode: If True, simulate orders without hitting broker API.
    """

    def __init__(self, paper_mode: bool = True) -> None:
        self.paper_mode = paper_mode
        self._orders: Dict[str, Order] = {}
        self._order_counter: int = 0
        self._fyers_client: Any = None
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
        order.placed_at = datetime.now()

        if order.order_type == OrderType.MARKET:
            # Market orders fill immediately in paper mode
            order.status = OrderStatus.FILLED
            order.fill_price = order.limit_price or 0.0
            order.fill_quantity = order.quantity
            order.filled_at = datetime.now()
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
        order.filled_at = datetime.now()

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
        order.placed_at = datetime.now()

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
