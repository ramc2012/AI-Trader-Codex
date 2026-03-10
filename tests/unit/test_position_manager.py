"""Tests for the PositionManager and Position classes."""

import pytest

from src.execution.position_manager import (
    Position,
    PositionManager,
    PositionSide,
)


# =============================================================================
# Position dataclass property tests
# =============================================================================


class TestPositionProperties:
    """Tests for Position dataclass computed properties."""

    def test_long_position_unrealized_pnl_profit(self) -> None:
        """LONG position P&L is (current - avg) * qty when profitable."""
        pos = Position(
            symbol="NSE:NIFTY50-INDEX",
            quantity=50,
            side=PositionSide.LONG,
            avg_price=100.0,
            current_price=110.0,
        )
        assert pos.unrealized_pnl == pytest.approx(500.0)

    def test_long_position_unrealized_pnl_loss(self) -> None:
        """LONG position P&L is negative when price drops."""
        pos = Position(
            symbol="NSE:NIFTY50-INDEX",
            quantity=50,
            side=PositionSide.LONG,
            avg_price=100.0,
            current_price=90.0,
        )
        assert pos.unrealized_pnl == pytest.approx(-500.0)

    def test_short_position_unrealized_pnl_profit(self) -> None:
        """SHORT position P&L is (avg - current) * qty when profitable."""
        pos = Position(
            symbol="NSE:NIFTY50-INDEX",
            quantity=50,
            side=PositionSide.SHORT,
            avg_price=100.0,
            current_price=90.0,
        )
        assert pos.unrealized_pnl == pytest.approx(500.0)

    def test_short_position_unrealized_pnl_loss(self) -> None:
        """SHORT position P&L is negative when price rises."""
        pos = Position(
            symbol="NSE:NIFTY50-INDEX",
            quantity=50,
            side=PositionSide.SHORT,
            avg_price=100.0,
            current_price=110.0,
        )
        assert pos.unrealized_pnl == pytest.approx(-500.0)

    def test_flat_position_unrealized_pnl_zero(self) -> None:
        """FLAT position always has zero unrealized P&L."""
        pos = Position(
            symbol="NSE:NIFTY50-INDEX",
            quantity=0,
            side=PositionSide.FLAT,
            avg_price=0.0,
            current_price=100.0,
        )
        assert pos.unrealized_pnl == 0.0

    def test_unrealized_pnl_pct(self) -> None:
        """P&L percentage is calculated relative to entry value."""
        pos = Position(
            symbol="TEST",
            quantity=10,
            side=PositionSide.LONG,
            avg_price=200.0,
            current_price=220.0,
        )
        # pnl = (220-200)*10 = 200; entry_value = 200*10 = 2000; pct = 10%
        assert pos.unrealized_pnl_pct == pytest.approx(10.0)

    def test_unrealized_pnl_pct_zero_avg(self) -> None:
        """P&L percentage returns 0 when avg_price is 0."""
        pos = Position(
            symbol="TEST",
            quantity=10,
            side=PositionSide.LONG,
            avg_price=0.0,
            current_price=100.0,
        )
        assert pos.unrealized_pnl_pct == 0.0

    def test_market_value(self) -> None:
        """Market value is current_price * quantity."""
        pos = Position(
            symbol="TEST",
            quantity=25,
            side=PositionSide.LONG,
            avg_price=100.0,
            current_price=120.0,
        )
        assert pos.market_value == pytest.approx(3000.0)

    def test_is_profitable_true(self) -> None:
        """is_profitable is True when unrealized P&L > 0."""
        pos = Position(
            symbol="TEST",
            quantity=10,
            side=PositionSide.LONG,
            avg_price=100.0,
            current_price=110.0,
        )
        assert pos.is_profitable is True

    def test_is_profitable_false(self) -> None:
        """is_profitable is False when unrealized P&L <= 0."""
        pos = Position(
            symbol="TEST",
            quantity=10,
            side=PositionSide.LONG,
            avg_price=100.0,
            current_price=90.0,
        )
        assert pos.is_profitable is False


# =============================================================================
# PositionManager tests
# =============================================================================


class TestPositionManagerOpenPosition:
    """Tests for opening, averaging, reducing, and flipping positions."""

    def test_open_new_position(self) -> None:
        """Opening a new position creates it correctly."""
        pm = PositionManager()
        pos = pm.open_position(
            symbol="NSE:NIFTY50-INDEX",
            quantity=50,
            side=PositionSide.LONG,
            price=22000.0,
            strategy_tag="ema_crossover",
            order_id="ORD-001",
        )
        assert pos.symbol == "NSE:NIFTY50-INDEX"
        assert pos.quantity == 50
        assert pos.side == PositionSide.LONG
        assert pos.avg_price == 22000.0
        assert pos.current_price == 22000.0
        assert pos.strategy_tag == "ema_crossover"
        assert "ORD-001" in pos.order_ids
        assert pos.entry_time is not None
        assert pm.position_count == 1

    def test_open_position_averaging_same_direction(self) -> None:
        """Adding to a position in the same direction averages the price."""
        pm = PositionManager()
        pm.open_position("SYM", 100, PositionSide.LONG, 100.0)
        pos = pm.open_position("SYM", 100, PositionSide.LONG, 200.0)
        # avg = (100*100 + 200*100) / 200 = 150
        assert pos.quantity == 200
        assert pos.avg_price == pytest.approx(150.0)
        assert pm.position_count == 1

    def test_open_position_keeps_strategy_lots_under_one_symbol(self) -> None:
        """Different strategies share one visible symbol row but keep separate lots."""
        pm = PositionManager()
        pm.open_position("SYM", 40, PositionSide.LONG, 100.0, strategy_tag="alpha")
        pos = pm.open_position("SYM", 60, PositionSide.LONG, 110.0, strategy_tag="beta")

        assert pos.quantity == 100
        assert pos.avg_price == pytest.approx(106.0)
        assert pos.strategy_tag == "MULTI"

        alpha_positions = pm.get_positions_by_tag("alpha")
        beta_positions = pm.get_positions_by_tag("beta")
        assert len(alpha_positions) == 1
        assert len(beta_positions) == 1
        assert alpha_positions[0].quantity == 40
        assert alpha_positions[0].avg_price == pytest.approx(100.0)
        assert beta_positions[0].quantity == 60
        assert beta_positions[0].avg_price == pytest.approx(110.0)

    def test_open_position_partial_close_opposite(self) -> None:
        """Opposite direction with smaller qty partially closes."""
        pm = PositionManager()
        pm.open_position("SYM", 100, PositionSide.LONG, 100.0)
        pos = pm.open_position("SYM", 30, PositionSide.SHORT, 120.0)
        # Partial close: pnl = (120 - 100) * 30 = 600
        assert pos.quantity == 70
        assert pos.side == PositionSide.LONG
        assert pm.total_realized_pnl == pytest.approx(600.0)

    def test_open_position_full_close_opposite(self) -> None:
        """Opposite direction with equal qty fully closes, returns FLAT."""
        pm = PositionManager()
        pm.open_position("SYM", 50, PositionSide.LONG, 100.0)
        pos = pm.open_position("SYM", 50, PositionSide.SHORT, 90.0)
        # Full close: pnl = (90 - 100) * 50 = -500
        assert pos.quantity == 0
        assert pos.side == PositionSide.FLAT
        assert pm.total_realized_pnl == pytest.approx(-500.0)
        assert pm.position_count == 0

    def test_open_position_flip(self) -> None:
        """Opposite direction with larger qty flips the position."""
        pm = PositionManager()
        pm.open_position("SYM", 50, PositionSide.LONG, 100.0)
        pos = pm.open_position("SYM", 80, PositionSide.SHORT, 110.0)
        # Closes 50 LONG: pnl = (110 - 100) * 50 = 500
        # Opens 30 SHORT at 110
        assert pos.quantity == 30
        assert pos.side == PositionSide.SHORT
        assert pos.avg_price == 110.0
        assert pm.total_realized_pnl == pytest.approx(500.0)
        assert pm.position_count == 1


class TestPositionManagerClosePosition:
    """Tests for close_position method."""

    def test_close_position_full(self) -> None:
        """Fully closing a position returns correct P&L and removes it."""
        pm = PositionManager()
        pm.open_position("SYM", 100, PositionSide.SHORT, 200.0)
        pnl = pm.close_position("SYM", 180.0)
        # SHORT pnl = (200 - 180) * 100 = 2000
        assert pnl == pytest.approx(2000.0)
        assert pm.position_count == 0
        assert pm.total_realized_pnl == pytest.approx(2000.0)

    def test_close_position_partial(self) -> None:
        """Partially closing reduces quantity and returns P&L for closed qty."""
        pm = PositionManager()
        pm.open_position("SYM", 100, PositionSide.LONG, 100.0)
        pnl = pm.close_position("SYM", 120.0, quantity=40)
        # pnl = (120 - 100) * 40 = 800
        assert pnl == pytest.approx(800.0)
        pos = pm.get_position("SYM")
        assert pos is not None
        assert pos.quantity == 60

    def test_close_position_unknown_symbol_raises(self) -> None:
        """Closing a non-existent position raises ValueError."""
        pm = PositionManager()
        with pytest.raises(ValueError, match="No position found"):
            pm.close_position("NONEXISTENT", 100.0)

    def test_close_position_excessive_qty_raises(self) -> None:
        """Closing more than held quantity raises ValueError."""
        pm = PositionManager()
        pm.open_position("SYM", 50, PositionSide.LONG, 100.0)
        with pytest.raises(ValueError, match="Cannot close"):
            pm.close_position("SYM", 110.0, quantity=100)

    def test_close_position_can_target_one_strategy_lot(self) -> None:
        """Closing a mixed position by strategy only closes that strategy slice."""
        pm = PositionManager()
        pm.open_position("SYM", 40, PositionSide.LONG, 100.0, strategy_tag="alpha")
        pm.open_position("SYM", 60, PositionSide.LONG, 110.0, strategy_tag="beta")

        pnl = pm.close_position("SYM", 120.0, quantity=40, strategy_tag="alpha")

        assert pnl == pytest.approx(800.0)
        pos = pm.get_position("SYM")
        assert pos is not None
        assert pos.quantity == 60
        assert pos.strategy_tag == "beta"
        trades = pm.get_closed_trades()
        assert len(trades) == 1
        assert trades[0]["strategy_tag"] == "alpha"


class TestPositionManagerPriceUpdates:
    """Tests for price update and P&L tracking."""

    def test_update_price(self) -> None:
        """update_price changes the current_price and affects unrealized P&L."""
        pm = PositionManager()
        pm.open_position("SYM", 10, PositionSide.LONG, 100.0)
        pos = pm.update_price("SYM", 150.0)
        assert pos is not None
        assert pos.current_price == 150.0
        assert pos.unrealized_pnl == pytest.approx(500.0)

    def test_update_price_unknown_returns_none(self) -> None:
        """update_price returns None for unknown symbol."""
        pm = PositionManager()
        assert pm.update_price("UNKNOWN", 100.0) is None

    def test_update_prices_bulk(self) -> None:
        """update_prices updates multiple symbols at once."""
        pm = PositionManager()
        pm.open_position("A", 10, PositionSide.LONG, 100.0)
        pm.open_position("B", 20, PositionSide.SHORT, 200.0)
        pm.update_prices({"A": 110.0, "B": 190.0})
        pos_a = pm.get_position("A")
        pos_b = pm.get_position("B")
        assert pos_a is not None and pos_a.current_price == 110.0
        assert pos_b is not None and pos_b.current_price == 190.0

    def test_total_unrealized_pnl_sums_correctly(self) -> None:
        """total_unrealized_pnl sums across all open positions."""
        pm = PositionManager()
        pm.open_position("A", 10, PositionSide.LONG, 100.0)
        pm.open_position("B", 10, PositionSide.LONG, 200.0)
        pm.update_prices({"A": 110.0, "B": 210.0})
        # A pnl = (110-100)*10 = 100; B pnl = (210-200)*10 = 100
        assert pm.total_unrealized_pnl == pytest.approx(200.0)

    def test_total_realized_pnl_accumulates(self) -> None:
        """total_realized_pnl accumulates across multiple closes."""
        pm = PositionManager()
        pm.open_position("A", 10, PositionSide.LONG, 100.0)
        pm.open_position("B", 10, PositionSide.LONG, 200.0)
        pm.close_position("A", 120.0)  # pnl = 200
        pm.close_position("B", 220.0)  # pnl = 200
        assert pm.total_realized_pnl == pytest.approx(400.0)

    def test_total_pnl_realized_plus_unrealized(self) -> None:
        """total_pnl = realized + unrealized."""
        pm = PositionManager()
        pm.open_position("A", 10, PositionSide.LONG, 100.0)
        pm.open_position("B", 10, PositionSide.LONG, 200.0)
        pm.close_position("A", 120.0)  # realized = 200
        pm.update_price("B", 210.0)  # unrealized = 100
        assert pm.total_pnl == pytest.approx(300.0)


class TestPositionManagerQueries:
    """Tests for query methods and portfolio summary."""

    def test_get_position_existing(self) -> None:
        """get_position returns the correct position."""
        pm = PositionManager()
        pm.open_position("SYM", 10, PositionSide.LONG, 100.0)
        pos = pm.get_position("SYM")
        assert pos is not None
        assert pos.symbol == "SYM"

    def test_get_position_nonexistent(self) -> None:
        """get_position returns None for unknown symbol."""
        pm = PositionManager()
        assert pm.get_position("UNKNOWN") is None

    def test_get_all_positions(self) -> None:
        """get_all_positions returns all open positions."""
        pm = PositionManager()
        pm.open_position("A", 10, PositionSide.LONG, 100.0)
        pm.open_position("B", 20, PositionSide.SHORT, 200.0)
        positions = pm.get_all_positions()
        assert len(positions) == 2

    def test_get_positions_by_tag(self) -> None:
        """get_positions_by_tag filters positions by strategy tag."""
        pm = PositionManager()
        pm.open_position("A", 10, PositionSide.LONG, 100.0, strategy_tag="alpha")
        pm.open_position("B", 20, PositionSide.SHORT, 200.0, strategy_tag="beta")
        pm.open_position("C", 5, PositionSide.LONG, 50.0, strategy_tag="alpha")
        alpha_positions = pm.get_positions_by_tag("alpha")
        assert len(alpha_positions) == 2

    def test_get_portfolio_summary(self) -> None:
        """get_portfolio_summary includes all required fields."""
        pm = PositionManager()
        pm.open_position("A", 10, PositionSide.LONG, 100.0)
        pm.update_price("A", 110.0)
        summary = pm.get_portfolio_summary()
        assert summary["position_count"] == 1
        assert summary["total_market_value"] == pytest.approx(1100.0)
        assert summary["total_unrealized_pnl"] == pytest.approx(100.0)
        assert summary["total_realized_pnl"] == pytest.approx(0.0)
        assert summary["total_pnl"] == pytest.approx(100.0)
        assert "A" in summary["positions"]
        pos_info = summary["positions"]["A"]
        assert pos_info["qty"] == 10
        assert pos_info["side"] == "long"
        assert pos_info["avg"] == 100.0
        assert pos_info["current"] == 110.0
        assert pos_info["pnl"] == pytest.approx(100.0)

    def test_get_closed_trades(self) -> None:
        """get_closed_trades returns history of closed trades."""
        pm = PositionManager()
        pm.open_position("SYM", 10, PositionSide.LONG, 100.0, strategy_tag="test")
        pm.close_position("SYM", 120.0)
        trades = pm.get_closed_trades()
        assert len(trades) == 1
        trade = trades[0]
        assert trade["symbol"] == "SYM"
        assert trade["side"] == "long"
        assert trade["quantity"] == 10
        assert trade["entry_price"] == 100.0
        assert trade["exit_price"] == 120.0
        assert trade["pnl"] == pytest.approx(200.0)
        assert trade["strategy_tag"] == "test"
        assert "closed_at" in trade

    def test_format_position_summary_orders_by_pnl_and_caps_output(self) -> None:
        """format_position_summary returns a compact ranked snapshot."""
        pm = PositionManager()
        pm.open_position("NSE:NIFTY50-INDEX", 10, PositionSide.LONG, 100.0)
        pm.open_position("NSE:BANKNIFTY-INDEX", 5, PositionSide.SHORT, 200.0)
        pm.open_position("CRYPTO:BTCUSDT", 1, PositionSide.LONG, 300.0)
        pm.update_prices({
            "NSE:NIFTY50-INDEX": 110.0,   # +100
            "NSE:BANKNIFTY-INDEX": 230.0,  # -150
            "CRYPTO:BTCUSDT": 320.0,       # +20
        })

        summary = pm.format_position_summary(max_items=2)

        lines = summary.splitlines()
        assert lines[0].startswith("• BANKNIFTY SHORT x5")
        assert "P&L -150.00" in lines[0]
        assert lines[1].startswith("• NIFTY50 LONG x10")
        assert "P&L +100.00" in lines[1]
        assert lines[2] == "• +1 more position(s)"

    def test_format_position_summary_handles_no_positions(self) -> None:
        """format_position_summary reports an empty portfolio cleanly."""
        pm = PositionManager()
        assert pm.format_position_summary() == "• None"
