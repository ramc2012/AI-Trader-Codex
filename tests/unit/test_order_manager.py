"""Tests for the order management system."""

from unittest.mock import MagicMock

import pytest

from src.execution.order_manager import (
    Order,
    OrderManager,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    ProductType,
)
from src.utils.exceptions import OrderError


# =========================================================================
# Order dataclass tests
# =========================================================================


class TestOrder:
    def test_order_creation(self) -> None:
        order = Order(
            symbol="NSE:NIFTY50-INDEX",
            quantity=50,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
        )
        assert order.symbol == "NSE:NIFTY50-INDEX"
        assert order.quantity == 50
        assert order.side == OrderSide.BUY
        assert order.order_type == OrderType.MARKET
        assert order.product_type == ProductType.INTRADAY
        assert order.status == OrderStatus.PENDING
        assert order.order_id is None

    def test_is_buy(self) -> None:
        buy = Order(symbol="X", quantity=1, side=OrderSide.BUY, order_type=OrderType.MARKET)
        sell = Order(symbol="X", quantity=1, side=OrderSide.SELL, order_type=OrderType.MARKET)
        assert buy.is_buy is True
        assert sell.is_buy is False

    def test_is_complete(self) -> None:
        order = Order(symbol="X", quantity=1, side=OrderSide.BUY, order_type=OrderType.MARKET)
        assert order.is_complete is False

        for terminal in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.FAILED):
            order.status = terminal
            assert order.is_complete is True

        for non_terminal in (OrderStatus.PENDING, OrderStatus.PLACED, OrderStatus.PARTIALLY_FILLED):
            order.status = non_terminal
            assert order.is_complete is False

    def test_value_with_fill_price(self) -> None:
        order = Order(symbol="X", quantity=50, side=OrderSide.BUY, order_type=OrderType.MARKET)
        order.fill_price = 100.0
        assert order.value == 5000.0

    def test_value_with_limit_price(self) -> None:
        order = Order(symbol="X", quantity=50, side=OrderSide.BUY,
                      order_type=OrderType.LIMIT, limit_price=200.0)
        assert order.value == 10000.0

    def test_value_no_price(self) -> None:
        order = Order(symbol="X", quantity=50, side=OrderSide.BUY, order_type=OrderType.MARKET)
        assert order.value == 0.0

    def test_to_fyers_params_market(self) -> None:
        order = Order(symbol="NSE:NIFTY", quantity=50, side=OrderSide.BUY,
                      order_type=OrderType.MARKET)
        params = order.to_fyers_params()
        assert params == {
            "symbol": "NSE:NIFTY",
            "qty": 50,
            "type": 1,
            "side": 1,
            "productType": "INTRADAY",
        }

    def test_to_fyers_params_limit_with_prices(self) -> None:
        order = Order(symbol="NSE:NIFTY", quantity=50, side=OrderSide.SELL,
                      order_type=OrderType.STOP_LIMIT, limit_price=100.0, stop_price=95.0)
        params = order.to_fyers_params()
        assert params["limitPrice"] == 100.0
        assert params["stopPrice"] == 95.0
        assert params["side"] == -1
        assert params["type"] == 4


# =========================================================================
# OrderManager — Paper Mode
# =========================================================================


class TestOrderManagerPaper:
    def test_default_paper_mode(self) -> None:
        om = OrderManager()
        assert om.paper_mode is True

    def test_place_market_order_fills_immediately(self) -> None:
        om = OrderManager(paper_mode=True)
        order = Order(symbol="NIFTY", quantity=50, side=OrderSide.BUY,
                      order_type=OrderType.MARKET, limit_price=100.0)
        result = om.place_order(order)

        assert result.success is True
        assert result.order_id is not None
        assert result.order.status == OrderStatus.FILLED
        assert result.order.fill_price == 100.0
        assert result.order.fill_quantity == 50
        assert result.order.filled_at is not None

    def test_place_limit_order_stays_placed(self) -> None:
        om = OrderManager(paper_mode=True)
        order = Order(symbol="NIFTY", quantity=50, side=OrderSide.BUY,
                      order_type=OrderType.LIMIT, limit_price=100.0)
        result = om.place_order(order)

        assert result.success is True
        assert result.order.status == OrderStatus.PLACED
        assert result.order.fill_price is None

    def test_place_order_zero_quantity_rejected(self) -> None:
        om = OrderManager()
        order = Order(symbol="NIFTY", quantity=0, side=OrderSide.BUY,
                      order_type=OrderType.MARKET)
        result = om.place_order(order)
        assert result.success is False

    def test_cancel_placed_order(self) -> None:
        om = OrderManager()
        order = Order(symbol="NIFTY", quantity=50, side=OrderSide.BUY,
                      order_type=OrderType.LIMIT, limit_price=100.0)
        place_result = om.place_order(order)
        cancel_result = om.cancel_order(place_result.order_id)

        assert cancel_result.success is True
        assert cancel_result.order.status == OrderStatus.CANCELLED

    def test_cancel_filled_order_fails(self) -> None:
        om = OrderManager()
        order = Order(symbol="NIFTY", quantity=50, side=OrderSide.BUY,
                      order_type=OrderType.MARKET, limit_price=100.0)
        place_result = om.place_order(order)
        cancel_result = om.cancel_order(place_result.order_id)

        assert cancel_result.success is False
        assert "cannot cancel" in cancel_result.message.lower() or "filled" in cancel_result.message.lower()

    def test_cancel_nonexistent_order(self) -> None:
        om = OrderManager()
        result = om.cancel_order("FAKE-ID")
        assert result.success is False

    def test_modify_order(self) -> None:
        om = OrderManager()
        order = Order(symbol="NIFTY", quantity=50, side=OrderSide.BUY,
                      order_type=OrderType.LIMIT, limit_price=100.0)
        place_result = om.place_order(order)
        oid = place_result.order_id

        mod_result = om.modify_order(oid, new_quantity=100, new_limit_price=105.0)
        assert mod_result.success is True
        assert mod_result.order.quantity == 100
        assert mod_result.order.limit_price == 105.0

    def test_modify_filled_order_fails(self) -> None:
        om = OrderManager()
        order = Order(symbol="NIFTY", quantity=50, side=OrderSide.BUY,
                      order_type=OrderType.MARKET, limit_price=100.0)
        place_result = om.place_order(order)
        mod_result = om.modify_order(place_result.order_id, new_quantity=100)
        assert mod_result.success is False

    def test_modify_no_params_fails(self) -> None:
        om = OrderManager()
        order = Order(symbol="NIFTY", quantity=50, side=OrderSide.BUY,
                      order_type=OrderType.LIMIT, limit_price=100.0)
        place_result = om.place_order(order)
        mod_result = om.modify_order(place_result.order_id)
        assert mod_result.success is False

    def test_modify_zero_quantity_fails(self) -> None:
        om = OrderManager()
        order = Order(symbol="NIFTY", quantity=50, side=OrderSide.BUY,
                      order_type=OrderType.LIMIT, limit_price=100.0)
        place_result = om.place_order(order)
        mod_result = om.modify_order(place_result.order_id, new_quantity=0)
        assert mod_result.success is False

    def test_simulate_fill(self) -> None:
        om = OrderManager()
        order = Order(symbol="NIFTY", quantity=50, side=OrderSide.BUY,
                      order_type=OrderType.LIMIT, limit_price=100.0)
        place_result = om.place_order(order)
        fill_result = om.simulate_fill(place_result.order_id, fill_price=99.5)

        assert fill_result.success is True
        assert fill_result.order.status == OrderStatus.FILLED
        assert fill_result.order.fill_price == 99.5

    def test_simulate_partial_fill(self) -> None:
        om = OrderManager()
        order = Order(symbol="NIFTY", quantity=100, side=OrderSide.BUY,
                      order_type=OrderType.LIMIT, limit_price=100.0)
        place_result = om.place_order(order)
        fill_result = om.simulate_fill(place_result.order_id, fill_price=99.5, fill_quantity=30)

        assert fill_result.success is True
        assert fill_result.order.status == OrderStatus.PARTIALLY_FILLED
        assert fill_result.order.fill_quantity == 30

    def test_simulate_fill_nonexistent(self) -> None:
        om = OrderManager()
        result = om.simulate_fill("FAKE", fill_price=100.0)
        assert result.success is False

    def test_simulate_fill_complete_order(self) -> None:
        om = OrderManager()
        order = Order(symbol="NIFTY", quantity=50, side=OrderSide.BUY,
                      order_type=OrderType.MARKET, limit_price=100.0)
        place_result = om.place_order(order)
        fill_result = om.simulate_fill(place_result.order_id, fill_price=99.5)
        assert fill_result.success is False


# =========================================================================
# OrderManager — Queries
# =========================================================================


class TestOrderManagerQueries:
    def test_get_order(self) -> None:
        om = OrderManager()
        order = Order(symbol="NIFTY", quantity=50, side=OrderSide.BUY,
                      order_type=OrderType.MARKET, limit_price=100.0)
        result = om.place_order(order)
        fetched = om.get_order(result.order_id)
        assert fetched is not None
        assert fetched.symbol == "NIFTY"

    def test_get_order_not_found(self) -> None:
        om = OrderManager()
        assert om.get_order("FAKE") is None

    def test_get_all_orders(self) -> None:
        om = OrderManager()
        for i in range(3):
            om.place_order(Order(symbol=f"S{i}", quantity=10, side=OrderSide.BUY,
                                 order_type=OrderType.MARKET, limit_price=100.0))
        assert len(om.get_all_orders()) == 3

    def test_get_open_orders(self) -> None:
        om = OrderManager()
        om.place_order(Order(symbol="A", quantity=10, side=OrderSide.BUY,
                             order_type=OrderType.MARKET, limit_price=100.0))  # filled
        om.place_order(Order(symbol="B", quantity=10, side=OrderSide.BUY,
                             order_type=OrderType.LIMIT, limit_price=100.0))  # placed

        open_orders = om.get_open_orders()
        assert len(open_orders) == 1
        assert open_orders[0].symbol == "B"

    def test_get_orders_by_symbol(self) -> None:
        om = OrderManager()
        om.place_order(Order(symbol="NIFTY", quantity=10, side=OrderSide.BUY,
                             order_type=OrderType.MARKET, limit_price=100.0))
        om.place_order(Order(symbol="BANKNIFTY", quantity=10, side=OrderSide.BUY,
                             order_type=OrderType.MARKET, limit_price=100.0))
        om.place_order(Order(symbol="NIFTY", quantity=20, side=OrderSide.SELL,
                             order_type=OrderType.MARKET, limit_price=100.0))

        nifty_orders = om.get_orders_by_symbol("NIFTY")
        assert len(nifty_orders) == 2

    def test_get_orders_by_tag(self) -> None:
        om = OrderManager()
        om.place_order(Order(symbol="A", quantity=10, side=OrderSide.BUY,
                             order_type=OrderType.MARKET, limit_price=100.0, tag="ema"))
        om.place_order(Order(symbol="B", quantity=10, side=OrderSide.BUY,
                             order_type=OrderType.MARKET, limit_price=100.0, tag="rsi"))
        om.place_order(Order(symbol="C", quantity=10, side=OrderSide.BUY,
                             order_type=OrderType.MARKET, limit_price=100.0, tag="ema"))

        ema_orders = om.get_orders_by_tag("ema")
        assert len(ema_orders) == 2

    def test_order_id_uniqueness(self) -> None:
        om = OrderManager()
        ids = set()
        for _ in range(10):
            result = om.place_order(Order(symbol="X", quantity=1, side=OrderSide.BUY,
                                          order_type=OrderType.MARKET, limit_price=1.0))
            ids.add(result.order_id)
        assert len(ids) == 10


# =========================================================================
# OrderManager — Live Mode
# =========================================================================


class TestOrderManagerLive:
    def test_live_without_client_raises(self) -> None:
        om = OrderManager(paper_mode=False)
        order = Order(symbol="X", quantity=10, side=OrderSide.BUY,
                      order_type=OrderType.MARKET)
        with pytest.raises(OrderError):
            om.place_order(order)

    def test_set_client(self) -> None:
        om = OrderManager(paper_mode=False)
        om.set_client("mock_client")
        assert om._fyers_client == "mock_client"

    def test_apply_broker_order_update_tracks_cumulative_fill_delta(self) -> None:
        om = OrderManager(paper_mode=False)
        client = MagicMock()
        client.place_order.return_value = {"s": "ok", "id": "FY123"}
        om.set_client(client)

        placed = om.place_order(
            Order(symbol="NSE:NIFTY", quantity=10, side=OrderSide.BUY, order_type=OrderType.MARKET)
        )
        assert placed.success is True

        partial = om.apply_broker_order_update(
            {
                "orders": {
                    "id": "FY123",
                    "qty": 10,
                    "filledQty": 4,
                    "tradedPrice": 100.0,
                    "status": "OPEN",
                    "message": "open",
                }
            }
        )
        assert partial.updated is True
        assert partial.order is not None
        assert partial.order.status == OrderStatus.PARTIALLY_FILLED
        assert partial.order.fill_quantity == 4
        assert partial.fill_delta_quantity == 4
        assert partial.fill_delta_price == pytest.approx(100.0)

        complete = om.apply_broker_order_update(
            {
                "orders": {
                    "id": "FY123",
                    "qty": 10,
                    "filledQty": 10,
                    "tradedPrice": 102.0,
                    "status": "COMPLETE",
                    "message": "filled",
                }
            }
        )
        assert complete.updated is True
        assert complete.order is not None
        assert complete.order.status == OrderStatus.FILLED
        assert complete.order.fill_quantity == 10
        assert complete.fill_delta_quantity == 6
        assert complete.fill_delta_price == pytest.approx((102.0 * 10 - 100.0 * 4) / 6)

    def test_apply_broker_trade_update_dedupes_trade_ids_and_rolls_average_price(self) -> None:
        om = OrderManager(paper_mode=False)
        client = MagicMock()
        client.place_order.return_value = {"s": "ok", "id": "FY456"}
        om.set_client(client)

        placed = om.place_order(
            Order(symbol="NSE:NIFTY", quantity=10, side=OrderSide.BUY, order_type=OrderType.MARKET)
        )
        assert placed.success is True

        first_fill = om.apply_broker_trade_update(
            {
                "trades": {
                    "orderNumber": "FY456",
                    "tradeNumber": "TRD-1",
                    "tradedQty": 3,
                    "tradePrice": 101.0,
                }
            }
        )
        assert first_fill.updated is True
        assert first_fill.order is not None
        assert first_fill.order.status == OrderStatus.PARTIALLY_FILLED
        assert first_fill.order.fill_quantity == 3
        assert first_fill.order.fill_price == pytest.approx(101.0)

        duplicate = om.apply_broker_trade_update(
            {
                "trades": {
                    "orderNumber": "FY456",
                    "tradeNumber": "TRD-1",
                    "tradedQty": 3,
                    "tradePrice": 101.0,
                }
            }
        )
        assert duplicate.updated is False
        assert duplicate.order is not None
        assert duplicate.order.fill_quantity == 3

        second_fill = om.apply_broker_trade_update(
            {
                "trades": {
                    "orderNumber": "FY456",
                    "tradeNumber": "TRD-2",
                    "tradedQty": 7,
                    "tradePrice": 99.0,
                }
            }
        )
        assert second_fill.updated is True
        assert second_fill.order is not None
        assert second_fill.order.status == OrderStatus.FILLED
        assert second_fill.order.fill_quantity == 10
        assert second_fill.order.fill_price == pytest.approx(((3 * 101.0) + (7 * 99.0)) / 10)


# =========================================================================
# Enum value tests
# =========================================================================


class TestEnums:
    def test_order_side_values(self) -> None:
        assert OrderSide.BUY.value == 1
        assert OrderSide.SELL.value == -1

    def test_order_type_values(self) -> None:
        assert OrderType.MARKET.value == 1
        assert OrderType.LIMIT.value == 2
        assert OrderType.STOP.value == 3
        assert OrderType.STOP_LIMIT.value == 4

    def test_order_status_values(self) -> None:
        assert OrderStatus.PENDING.value == "pending"
        assert OrderStatus.FILLED.value == "filled"
        assert OrderStatus.CANCELLED.value == "cancelled"
