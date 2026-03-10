"""Tests for the FastAPI trading API endpoints.

Covers positions, portfolio, orders, open orders, and closed trades
endpoints defined in ``src/api/routes/trading.py``.  Uses real
OrderManager and PositionManager instances in paper mode -- no external
services required.
"""

from typing import Tuple

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.dependencies import get_order_manager, get_position_manager, get_trading_agent, reset_managers
from src.api.main import create_app
from src.api.routes.trading import _build_trade_pairs
from src.execution.order_manager import Order, OrderManager, OrderSide, OrderType
from src.execution.position_manager import PositionManager, PositionSide


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def app() -> Tuple[FastAPI, OrderManager, PositionManager]:
    """Create a test FastAPI app with fresh manager overrides.

    Yields:
        Tuple of (application, order_manager, position_manager).
    """
    reset_managers()
    application = create_app()
    om = OrderManager(paper_mode=True)
    pm = PositionManager()

    class DummyAgent:
        async def refresh_position_marks(self, symbols: list[str]) -> None:
            return None

        def _display_exit_plan(self, symbol: str):
            return None

        def get_capital_allocations(self):
            return {
                "NSE": {
                    "market": "NSE",
                    "label": "India",
                    "currency": "INR",
                    "currency_symbol": "₹",
                    "fx_to_inr": 1.0,
                    "allocated_capital": 250000.0,
                    "allocated_capital_inr": 250000.0,
                    "max_instrument_pct": 25.0,
                    "max_instrument_capital": 62500.0,
                    "max_instrument_capital_inr": 62500.0,
                },
                "US": {
                    "market": "US",
                    "label": "US",
                    "currency": "USD",
                    "currency_symbol": "$",
                    "fx_to_inr": 83.0,
                    "allocated_capital": 250000.0,
                    "allocated_capital_inr": 20750000.0,
                    "max_instrument_pct": 20.0,
                    "max_instrument_capital": 50000.0,
                    "max_instrument_capital_inr": 4150000.0,
                },
                "CRYPTO": {
                    "market": "CRYPTO",
                    "label": "Crypto",
                    "currency": "USD",
                    "currency_symbol": "$",
                    "fx_to_inr": 83.0,
                    "allocated_capital": 250000.0,
                    "allocated_capital_inr": 20750000.0,
                    "max_instrument_pct": 20.0,
                    "max_instrument_capital": 50000.0,
                    "max_instrument_capital_inr": 4150000.0,
                },
            }

        def total_allocated_capital_inr(self) -> float:
            return 41750000.0

    application.dependency_overrides[get_order_manager] = lambda: om
    application.dependency_overrides[get_position_manager] = lambda: pm
    application.dependency_overrides[get_trading_agent] = lambda: DummyAgent()
    yield application, om, pm
    reset_managers()


@pytest.fixture
def client(app: Tuple[FastAPI, OrderManager, PositionManager]) -> TestClient:
    """Create a test HTTP client from the overridden app.

    Args:
        app: Fixture tuple of (application, order_manager, position_manager).

    Returns:
        FastAPI TestClient with raise_server_exceptions disabled.
    """
    application, _, _ = app
    return TestClient(application, raise_server_exceptions=False)


@pytest.fixture
def om(app: Tuple[FastAPI, OrderManager, PositionManager]) -> OrderManager:
    """Shortcut to the injected OrderManager."""
    return app[1]


@pytest.fixture
def pm(app: Tuple[FastAPI, OrderManager, PositionManager]) -> PositionManager:
    """Shortcut to the injected PositionManager."""
    return app[2]


# =========================================================================
# Positions Endpoint Tests
# =========================================================================


class TestPositions:
    """Tests for GET /api/v1/positions."""

    def test_empty_positions(self, client: TestClient) -> None:
        """An empty PositionManager returns an empty list."""
        resp = client.get("/api/v1/positions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_single_long_position(
        self, client: TestClient, pm: PositionManager
    ) -> None:
        """Opening a long position makes it visible via the endpoint."""
        pm.open_position(
            symbol="NSE:NIFTY50-INDEX",
            quantity=50,
            side=PositionSide.LONG,
            price=22000.0,
            strategy_tag="ema_crossover",
            order_id="ORD-001",
        )
        pm.update_price("NSE:NIFTY50-INDEX", 22100.0)

        resp = client.get("/api/v1/positions")
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) == 1

        pos = data[0]
        assert pos["symbol"] == "NSE:NIFTY50-INDEX"
        assert pos["quantity"] == 50
        assert pos["side"] == "long"
        assert pos["avg_price"] == 22000.0
        assert pos["current_price"] == 22100.0
        assert pos["strategy_tag"] == "ema_crossover"
        assert "ORD-001" in pos["order_ids"]

    def test_position_pnl_fields(
        self, client: TestClient, pm: PositionManager
    ) -> None:
        """Verify unrealized P&L, P&L %, market value, and profitability."""
        pm.open_position(
            symbol="NSE:NIFTY50-INDEX",
            quantity=100,
            side=PositionSide.LONG,
            price=20000.0,
        )
        pm.update_price("NSE:NIFTY50-INDEX", 20500.0)

        resp = client.get("/api/v1/positions")
        pos = resp.json()[0]

        # unrealized_pnl = (20500 - 20000) * 100 = 50000
        assert pos["unrealized_pnl"] == pytest.approx(50000.0)
        # unrealized_pnl_pct = 50000 / (20000 * 100) * 100 = 2.5%
        assert pos["unrealized_pnl_pct"] == pytest.approx(2.5)
        # market_value = 20500 * 100
        assert pos["market_value"] == pytest.approx(2050000.0)
        assert pos["is_profitable"] is True

    def test_short_position_loss(
        self, client: TestClient, pm: PositionManager
    ) -> None:
        """A short position shows loss when price rises."""
        pm.open_position(
            symbol="NSE:BANKNIFTY-INDEX",
            quantity=25,
            side=PositionSide.SHORT,
            price=48000.0,
        )
        pm.update_price("NSE:BANKNIFTY-INDEX", 48200.0)

        resp = client.get("/api/v1/positions")
        pos = resp.json()[0]

        # unrealized_pnl = (48000 - 48200) * 25 = -5000
        assert pos["unrealized_pnl"] == pytest.approx(-5000.0)
        assert pos["is_profitable"] is False

    def test_multiple_positions(
        self, client: TestClient, pm: PositionManager
    ) -> None:
        """Multiple open positions are all returned."""
        pm.open_position(
            symbol="NSE:NIFTY50-INDEX",
            quantity=50,
            side=PositionSide.LONG,
            price=22000.0,
        )
        pm.open_position(
            symbol="NSE:BANKNIFTY-INDEX",
            quantity=25,
            side=PositionSide.SHORT,
            price=48000.0,
        )

        resp = client.get("/api/v1/positions")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

        symbols = {p["symbol"] for p in resp.json()}
        assert symbols == {"NSE:NIFTY50-INDEX", "NSE:BANKNIFTY-INDEX"}

    def test_position_entry_time_present(
        self, client: TestClient, pm: PositionManager
    ) -> None:
        """Position entry_time is set and serialized correctly."""
        pm.open_position(
            symbol="NSE:NIFTY50-INDEX",
            quantity=10,
            side=PositionSide.LONG,
            price=22000.0,
        )

        resp = client.get("/api/v1/positions")
        pos = resp.json()[0]
        assert pos["entry_time"] is not None


# =========================================================================
# Portfolio Summary Endpoint Tests
# =========================================================================


class TestPortfolio:
    """Tests for GET /api/v1/portfolio."""

    def test_empty_portfolio(self, client: TestClient) -> None:
        """Empty portfolio returns zero-value summary."""
        resp = client.get("/api/v1/portfolio")
        assert resp.status_code == 200

        data = resp.json()
        assert data["position_count"] == 0
        assert data["total_market_value"] == 0.0
        assert data["total_unrealized_pnl"] == 0.0
        assert data["total_realized_pnl"] == 0.0
        assert data["total_pnl"] == 0.0
        assert data["total_allocated_capital_inr"] == 41750000.0
        assert data["total_pnl_pct_on_allocated"] == 0.0
        assert data["positions"] == {}

    def test_portfolio_with_one_position(
        self, client: TestClient, pm: PositionManager
    ) -> None:
        """Portfolio reflects a single open position."""
        pm.open_position(
            symbol="NSE:NIFTY50-INDEX",
            quantity=50,
            side=PositionSide.LONG,
            price=22000.0,
            strategy_tag="test_strat",
        )
        pm.update_price("NSE:NIFTY50-INDEX", 22200.0)

        resp = client.get("/api/v1/portfolio")
        assert resp.status_code == 200

        data = resp.json()
        assert data["position_count"] == 1
        # market_value = 22200 * 50 = 1110000
        assert data["total_market_value"] == pytest.approx(1110000.0)
        # unrealized = (22200 - 22000) * 50 = 10000
        assert data["total_unrealized_pnl"] == pytest.approx(10000.0)
        assert data["total_realized_pnl"] == 0.0
        # total_pnl = realized + unrealized = 10000
        assert data["total_pnl"] == pytest.approx(10000.0)
        assert data["market_breakdown"]["NSE"]["allocated_capital"] == 250000.0
        assert data["market_breakdown"]["NSE"]["pnl_pct_on_allocated"] == pytest.approx(4.0)

    def test_portfolio_positions_detail(
        self, client: TestClient, pm: PositionManager
    ) -> None:
        """Portfolio positions dict includes per-symbol breakdown."""
        pm.open_position(
            symbol="NSE:NIFTY50-INDEX",
            quantity=50,
            side=PositionSide.LONG,
            price=22000.0,
        )
        pm.update_price("NSE:NIFTY50-INDEX", 22100.0)

        data = client.get("/api/v1/portfolio").json()
        assert "NSE:NIFTY50-INDEX" in data["positions"]

        detail = data["positions"]["NSE:NIFTY50-INDEX"]
        assert detail["qty"] == 50
        assert detail["side"] == "long"
        assert detail["avg"] == 22000.0
        assert detail["current"] == 22100.0
        # pnl = (22100 - 22000) * 50 = 5000
        assert detail["pnl"] == pytest.approx(5000.0)

    def test_portfolio_with_realized_pnl(
        self, client: TestClient, pm: PositionManager
    ) -> None:
        """Realized P&L is reflected after closing a position."""
        pm.open_position(
            symbol="NSE:NIFTY50-INDEX",
            quantity=50,
            side=PositionSide.LONG,
            price=22000.0,
        )
        # Close fully at a profit
        pm.close_position("NSE:NIFTY50-INDEX", price=22500.0)

        data = client.get("/api/v1/portfolio").json()
        assert data["position_count"] == 0
        # realized = (22500 - 22000) * 50 = 25000
        assert data["total_realized_pnl"] == pytest.approx(25000.0)
        assert data["total_unrealized_pnl"] == 0.0
        assert data["total_pnl"] == pytest.approx(25000.0)

    def test_portfolio_multiple_positions(
        self, client: TestClient, pm: PositionManager
    ) -> None:
        """Portfolio correctly aggregates multiple positions."""
        pm.open_position(
            symbol="NSE:NIFTY50-INDEX",
            quantity=50,
            side=PositionSide.LONG,
            price=22000.0,
        )
        pm.open_position(
            symbol="NSE:BANKNIFTY-INDEX",
            quantity=25,
            side=PositionSide.SHORT,
            price=48000.0,
        )
        pm.update_price("NSE:NIFTY50-INDEX", 22100.0)
        pm.update_price("NSE:BANKNIFTY-INDEX", 47900.0)

        data = client.get("/api/v1/portfolio").json()
        assert data["position_count"] == 2

        # nifty: (22100 - 22000)*50 = 5000
        # bank:  (48000 - 47900)*25 = 2500
        assert data["total_unrealized_pnl"] == pytest.approx(7500.0)


# =========================================================================
# Orders Endpoint Tests
# =========================================================================


class TestOrders:
    """Tests for GET /api/v1/orders and GET /api/v1/orders/open."""

    def test_empty_orders(self, client: TestClient) -> None:
        """No orders placed returns an empty list."""
        resp = client.get("/api/v1/orders")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_empty_open_orders(self, client: TestClient) -> None:
        """No orders placed means no open orders."""
        resp = client.get("/api/v1/orders/open")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_market_order_appears_in_all_orders(
        self, client: TestClient, om: OrderManager
    ) -> None:
        """A placed market order appears in the all-orders list."""
        order = Order(
            symbol="NSE:NIFTY50-INDEX",
            quantity=50,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            limit_price=22000.0,
            tag="test_strat",
        )
        result = om.place_order(order)
        assert result.success

        resp = client.get("/api/v1/orders")
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) == 1

        o = data[0]
        assert o["symbol"] == "NSE:NIFTY50-INDEX"
        assert o["quantity"] == 50
        assert o["side"] == "BUY"
        assert o["order_type"] == "MARKET"
        assert o["product_type"] == "INTRADAY"
        assert o["tag"] == "test_strat"
        assert o["order_id"] is not None
        assert o["status"] == "filled"
        assert o["is_buy"] is True
        assert o["is_complete"] is True

    def test_market_order_not_in_open_orders(
        self, client: TestClient, om: OrderManager
    ) -> None:
        """A filled market order is NOT listed as open."""
        order = Order(
            symbol="NSE:NIFTY50-INDEX",
            quantity=50,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            limit_price=22000.0,
        )
        om.place_order(order)

        resp = client.get("/api/v1/orders/open")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_limit_order_is_open(
        self, client: TestClient, om: OrderManager
    ) -> None:
        """A limit order stays in 'placed' status and shows as open."""
        order = Order(
            symbol="NSE:NIFTY50-INDEX",
            quantity=25,
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            limit_price=22500.0,
        )
        result = om.place_order(order)
        assert result.success

        # Should appear in all orders
        all_orders = client.get("/api/v1/orders").json()
        assert len(all_orders) == 1
        assert all_orders[0]["status"] == "placed"
        assert all_orders[0]["is_complete"] is False

        # Should appear in open orders
        open_orders = client.get("/api/v1/orders/open").json()
        assert len(open_orders) == 1
        assert open_orders[0]["order_id"] == result.order_id

    def test_cancelled_order_not_open(
        self, client: TestClient, om: OrderManager
    ) -> None:
        """A cancelled limit order is in all orders but not in open orders."""
        order = Order(
            symbol="NSE:NIFTY50-INDEX",
            quantity=25,
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            limit_price=22500.0,
        )
        result = om.place_order(order)
        om.cancel_order(result.order_id)

        all_orders = client.get("/api/v1/orders").json()
        assert len(all_orders) == 1
        assert all_orders[0]["status"] == "cancelled"

        open_orders = client.get("/api/v1/orders/open").json()
        assert len(open_orders) == 0

    def test_multiple_orders_mixed_status(
        self, client: TestClient, om: OrderManager
    ) -> None:
        """Mix of filled, placed, and cancelled orders is partitioned correctly."""
        # Market order (filled immediately)
        market = Order(
            symbol="NSE:NIFTY50-INDEX",
            quantity=50,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            limit_price=22000.0,
        )
        om.place_order(market)

        # Limit order (stays open)
        limit_order = Order(
            symbol="NSE:NIFTY50-INDEX",
            quantity=25,
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            limit_price=22500.0,
        )
        om.place_order(limit_order)

        # Stop order (stays open)
        stop_order = Order(
            symbol="NSE:BANKNIFTY-INDEX",
            quantity=10,
            side=OrderSide.BUY,
            order_type=OrderType.STOP,
            stop_price=48500.0,
        )
        om.place_order(stop_order)

        all_orders = client.get("/api/v1/orders").json()
        assert len(all_orders) == 3

        open_orders = client.get("/api/v1/orders/open").json()
        assert len(open_orders) == 2

        open_statuses = {o["status"] for o in open_orders}
        assert "filled" not in open_statuses

    def test_order_response_fields_complete(
        self, client: TestClient, om: OrderManager
    ) -> None:
        """All OrderResponse fields are present in the JSON output."""
        order = Order(
            symbol="NSE:NIFTY50-INDEX",
            quantity=50,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            limit_price=22000.0,
            tag="field_check",
        )
        om.place_order(order)

        data = client.get("/api/v1/orders").json()[0]

        expected_keys = {
            "symbol",
            "quantity",
            "side",
            "order_type",
            "product_type",
            "limit_price",
            "stop_price",
            "tag",
            "order_id",
            "status",
            "fill_price",
            "fill_quantity",
            "placed_at",
            "filled_at",
            "rejection_reason",
            "is_buy",
            "is_complete",
            "value",
        }
        assert expected_keys.issubset(set(data.keys()))

    def test_order_fill_price_and_quantity(
        self, client: TestClient, om: OrderManager
    ) -> None:
        """Filled market order has correct fill_price and fill_quantity."""
        order = Order(
            symbol="NSE:NIFTY50-INDEX",
            quantity=75,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            limit_price=21500.0,
        )
        om.place_order(order)

        data = client.get("/api/v1/orders").json()[0]
        assert data["fill_price"] == 21500.0
        assert data["fill_quantity"] == 75
        assert data["filled_at"] is not None
        assert data["placed_at"] is not None

    def test_order_value_calculation(
        self, client: TestClient, om: OrderManager
    ) -> None:
        """Order value is price * quantity."""
        order = Order(
            symbol="NSE:NIFTY50-INDEX",
            quantity=10,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            limit_price=22000.0,
        )
        om.place_order(order)

        data = client.get("/api/v1/orders").json()[0]
        # value = fill_price * quantity = 22000 * 10
        assert data["value"] == pytest.approx(220000.0)


class TestOrderPairs:
    """Tests for FIFO trade pair construction."""

    def test_open_entry_is_retained_with_blank_exit(self) -> None:
        """One-way filled entries remain visible in history with open exit fields."""
        buy_order = Order(
            symbol="NSE:NIFTY50-INDEX",
            quantity=50,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            limit_price=22000.0,
            tag="ema_crossover",
            order_id="BUY-001",
            fill_price=22000.0,
            fill_quantity=50,
        )

        pairs = _build_trade_pairs([buy_order], usd_inr_rate=83.0)

        assert len(pairs) == 1
        pair = pairs[0]
        assert pair.symbol == "NSE:NIFTY50-INDEX"
        assert pair.side == "LONG"
        assert pair.quantity == 50
        assert pair.entry_price == pytest.approx(22000.0)
        assert pair.exit_price is None
        assert pair.exit_time is None
        assert pair.exit_order_id is None
        assert pair.pnl == pytest.approx(0.0)
        assert pair.pnl_inr == pytest.approx(0.0)
        assert pair.strategy_tag == "ema_crossover"

    def test_closed_pair_and_open_remainder_are_both_returned(self) -> None:
        """Partial exits produce a closed row plus an open remainder row."""
        buy_order = Order(
            symbol="NSE:NIFTY50-INDEX",
            quantity=50,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            limit_price=22000.0,
            order_id="BUY-001",
            fill_price=22000.0,
            fill_quantity=50,
        )
        sell_order = Order(
            symbol="NSE:NIFTY50-INDEX",
            quantity=20,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            limit_price=22100.0,
            order_id="SELL-001",
            fill_price=22100.0,
            fill_quantity=20,
        )

        pairs = _build_trade_pairs([buy_order, sell_order], usd_inr_rate=83.0)

        assert len(pairs) == 2
        closed = next(pair for pair in pairs if pair.exit_time is not None)
        open_leg = next(pair for pair in pairs if pair.exit_time is None)

        assert closed.quantity == 20
        assert closed.exit_price == pytest.approx(22100.0)
        assert closed.pnl == pytest.approx(2000.0)

        assert open_leg.quantity == 30
        assert open_leg.entry_price == pytest.approx(22000.0)
        assert open_leg.exit_price is None
        assert open_leg.pnl_inr == pytest.approx(0.0)


# =========================================================================
# Closed Trades Endpoint Tests
# =========================================================================


class TestTrades:
    """Tests for GET /api/v1/trades."""

    def test_empty_trades(self, client: TestClient) -> None:
        """No closed trades returns an empty list."""
        resp = client.get("/api/v1/trades")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_single_closed_trade(
        self, client: TestClient, pm: PositionManager
    ) -> None:
        """Closing a position creates a closed trade record."""
        pm.open_position(
            symbol="NSE:NIFTY50-INDEX",
            quantity=50,
            side=PositionSide.LONG,
            price=22000.0,
            strategy_tag="ema_crossover",
        )
        pm.close_position("NSE:NIFTY50-INDEX", price=22300.0)

        resp = client.get("/api/v1/trades")
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) == 1

        trade = data[0]
        assert trade["symbol"] == "NSE:NIFTY50-INDEX"
        assert trade["side"] == "long"
        assert trade["quantity"] == 50
        assert trade["entry_price"] == 22000.0
        assert trade["exit_price"] == 22300.0
        # pnl = (22300 - 22000) * 50 = 15000
        assert trade["pnl"] == pytest.approx(15000.0)
        assert trade["strategy_tag"] == "ema_crossover"
        assert trade["closed_at"] is not None

    def test_short_trade_profit(
        self, client: TestClient, pm: PositionManager
    ) -> None:
        """Profitable short trade has positive P&L."""
        pm.open_position(
            symbol="NSE:BANKNIFTY-INDEX",
            quantity=25,
            side=PositionSide.SHORT,
            price=48000.0,
        )
        pm.close_position("NSE:BANKNIFTY-INDEX", price=47500.0)

        trade = client.get("/api/v1/trades").json()[0]
        # pnl = (48000 - 47500) * 25 = 12500
        assert trade["pnl"] == pytest.approx(12500.0)
        assert trade["side"] == "short"

    def test_losing_trade(
        self, client: TestClient, pm: PositionManager
    ) -> None:
        """A losing long trade has negative P&L."""
        pm.open_position(
            symbol="NSE:NIFTY50-INDEX",
            quantity=50,
            side=PositionSide.LONG,
            price=22000.0,
        )
        pm.close_position("NSE:NIFTY50-INDEX", price=21800.0)

        trade = client.get("/api/v1/trades").json()[0]
        # pnl = (21800 - 22000) * 50 = -10000
        assert trade["pnl"] == pytest.approx(-10000.0)

    def test_partial_close_creates_trade(
        self, client: TestClient, pm: PositionManager
    ) -> None:
        """Partial close creates a trade record while position remains open."""
        pm.open_position(
            symbol="NSE:NIFTY50-INDEX",
            quantity=100,
            side=PositionSide.LONG,
            price=22000.0,
        )
        pm.close_position("NSE:NIFTY50-INDEX", price=22200.0, quantity=40)

        # Trade recorded for partial close
        trades = client.get("/api/v1/trades").json()
        assert len(trades) == 1
        assert trades[0]["quantity"] == 40
        # pnl = (22200 - 22000) * 40 = 8000
        assert trades[0]["pnl"] == pytest.approx(8000.0)

        # Position still open with remaining quantity
        positions = client.get("/api/v1/positions").json()
        assert len(positions) == 1
        assert positions[0]["quantity"] == 60

    def test_multiple_closed_trades(
        self, client: TestClient, pm: PositionManager
    ) -> None:
        """Multiple closed trades are all returned."""
        # First trade: long nifty
        pm.open_position(
            symbol="NSE:NIFTY50-INDEX",
            quantity=50,
            side=PositionSide.LONG,
            price=22000.0,
        )
        pm.close_position("NSE:NIFTY50-INDEX", price=22100.0)

        # Second trade: short banknifty
        pm.open_position(
            symbol="NSE:BANKNIFTY-INDEX",
            quantity=25,
            side=PositionSide.SHORT,
            price=48000.0,
        )
        pm.close_position("NSE:BANKNIFTY-INDEX", price=47800.0)

        trades = client.get("/api/v1/trades").json()
        assert len(trades) == 2

        symbols = {t["symbol"] for t in trades}
        assert symbols == {"NSE:NIFTY50-INDEX", "NSE:BANKNIFTY-INDEX"}

    def test_closed_trade_response_fields_complete(
        self, client: TestClient, pm: PositionManager
    ) -> None:
        """All ClosedTradeResponse fields are present."""
        pm.open_position(
            symbol="NSE:NIFTY50-INDEX",
            quantity=10,
            side=PositionSide.LONG,
            price=22000.0,
            strategy_tag="check_fields",
        )
        pm.close_position("NSE:NIFTY50-INDEX", price=22050.0)

        trade = client.get("/api/v1/trades").json()[0]

        expected_keys = {
            "symbol",
            "side",
            "quantity",
            "entry_price",
            "exit_price",
            "pnl",
            "closed_at",
            "strategy_tag",
        }
        assert expected_keys.issubset(set(trade.keys()))

    def test_trades_not_affected_by_open_positions(
        self, client: TestClient, pm: PositionManager
    ) -> None:
        """Open positions do not appear in the trades list."""
        pm.open_position(
            symbol="NSE:NIFTY50-INDEX",
            quantity=50,
            side=PositionSide.LONG,
            price=22000.0,
        )

        trades = client.get("/api/v1/trades").json()
        assert len(trades) == 0
