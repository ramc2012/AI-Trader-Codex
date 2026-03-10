"""Tests for the RiskManager class and related dataclasses."""

import pytest

from src.risk.risk_manager import (
    DailyRiskState,
    RiskConfig,
    RiskManager,
    TradeValidation,
)


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def config() -> RiskConfig:
    """Standard risk config."""
    return RiskConfig(
        max_daily_loss=5000.0,
        max_daily_loss_pct=0.02,
        max_position_size=100_000.0,
        max_open_positions=5,
        max_concentration_pct=0.30,
        max_risk_per_trade_pct=0.02,
        capital=250_000.0,
        circuit_breaker_enabled=True,
    )


@pytest.fixture
def manager(config: RiskConfig) -> RiskManager:
    """Fresh risk manager."""
    return RiskManager(config=config)


# =========================================================================
# validate_trade — pass cases
# =========================================================================


class TestValidateTradePass:
    def test_valid_trade_within_all_limits(self, manager: RiskManager) -> None:
        """A small trade well within all limits should pass."""
        # position_value = 2 * 22000 = 44000 < 100000 limit
        # risk = 2 * 50 = 100, risk_pct = 100 / 250000 = 0.04% < 2% limit
        # concentration = 44000 / 250000 = 17.6% < 30% limit
        result = manager.validate_trade(
            symbol="NSE:NIFTY50-INDEX",
            side="BUY",
            quantity=2,
            entry_price=22000.0,
            stop_loss=21950.0,
        )
        assert result.is_valid is True
        assert result.reason == ""
        assert 0.0 <= result.risk_score <= 1.0


# =========================================================================
# validate_trade — rejection cases
# =========================================================================


class TestValidateTradeReject:
    def test_rejects_daily_loss_limit_exceeded(self, manager: RiskManager) -> None:
        """After a large realized loss, new trades should be rejected."""
        # Push realized PnL to -5000 (the limit)
        manager.daily_state.realized_pnl = -5000.0
        result = manager.validate_trade(
            symbol="NSE:NIFTY50-INDEX",
            side="BUY",
            quantity=50,
            entry_price=22000.0,
            stop_loss=21900.0,
        )
        assert result.is_valid is False
        assert "loss limit" in result.reason.lower() or "daily" in result.reason.lower()

    def test_rejects_max_positions_exceeded(self, manager: RiskManager) -> None:
        """At max open positions, reject new trades."""
        manager.daily_state.open_positions = 5  # max is 5
        result = manager.validate_trade(
            symbol="NSE:NIFTY50-INDEX",
            side="BUY",
            quantity=50,
            entry_price=22000.0,
            stop_loss=21900.0,
        )
        assert result.is_valid is False
        assert "position" in result.reason.lower()

    def test_rejects_emergency_stop(self, manager: RiskManager) -> None:
        """Emergency stop blocks all trades."""
        manager.trigger_emergency_stop("test")
        result = manager.validate_trade(
            symbol="NSE:NIFTY50-INDEX",
            side="BUY",
            quantity=50,
            entry_price=22000.0,
            stop_loss=21900.0,
        )
        assert result.is_valid is False
        assert "emergency" in result.reason.lower()

    def test_rejects_position_size_too_large(self, manager: RiskManager) -> None:
        """Position value exceeding max_position_size is rejected."""
        # max_position_size=100000, so qty=10 * 22000 = 220000 > 100000
        result = manager.validate_trade(
            symbol="NSE:NIFTY50-INDEX",
            side="BUY",
            quantity=10,
            entry_price=22000.0,
            stop_loss=21900.0,
        )
        assert result.is_valid is False
        assert "position value" in result.reason.lower() or "exceeds" in result.reason.lower()

    def test_rejects_risk_per_trade_too_high(self, manager: RiskManager) -> None:
        """Risk per trade exceeding limit is rejected."""
        # Use a custom config where position_size and concentration limits are very high
        # so we specifically trigger the risk-per-trade check.
        cfg = RiskConfig(
            max_daily_loss=50000.0,
            max_position_size=50_000_000.0,
            max_open_positions=10,
            max_concentration_pct=50.0,  # very high so concentration doesn't trigger
            max_risk_per_trade_pct=0.02,
            capital=250_000.0,
        )
        mgr = RiskManager(config=cfg)
        # qty=50, entry=22000, sl=20000 → risk = 50*2000 = 100000
        # risk_pct = 100000/250000 = 0.4 >> 0.02
        result = mgr.validate_trade(
            symbol="NSE:NIFTY50-INDEX",
            side="BUY",
            quantity=50,
            entry_price=22000.0,
            stop_loss=20000.0,
        )
        assert result.is_valid is False
        assert "risk per trade" in result.reason.lower()

    def test_rejects_circuit_breaker_triggered(self, manager: RiskManager) -> None:
        """When circuit breaker is triggered, reject new trades."""
        manager.daily_state.circuit_breaker_triggered = True
        result = manager.validate_trade(
            symbol="NSE:NIFTY50-INDEX",
            side="BUY",
            quantity=50,
            entry_price=22000.0,
            stop_loss=21900.0,
        )
        assert result.is_valid is False
        assert "circuit breaker" in result.reason.lower()

    def test_allows_trades_after_loss_limit_when_circuit_breaker_disabled(self) -> None:
        """Disabling the breaker should also disable daily-loss trade rejection."""
        cfg = RiskConfig(
            max_daily_loss=5_000.0,
            max_daily_loss_pct=0.02,
            max_position_size=100_000.0,
            max_open_positions=5,
            max_concentration_pct=0.30,
            max_risk_per_trade_pct=0.02,
            capital=250_000.0,
            circuit_breaker_enabled=False,
        )
        mgr = RiskManager(config=cfg)
        mgr.daily_state.realized_pnl = -5_500.0
        mgr.daily_state.circuit_breaker_triggered = True

        result = mgr.validate_trade(
            symbol="NSE:NIFTY50-INDEX",
            side="BUY",
            quantity=2,
            entry_price=22_000.0,
            stop_loss=21_950.0,
        )

        assert result.is_valid is True
        assert result.reason == ""


# =========================================================================
# Circuit breaker
# =========================================================================


class TestCircuitBreaker:
    def test_triggers_at_loss_limit(self, manager: RiskManager) -> None:
        """update_pnl with a large loss should trigger the circuit breaker."""
        manager.update_pnl(-5000.0, is_realized=True)
        assert manager.daily_state.circuit_breaker_triggered is True

    def test_check_circuit_breaker_returns_true_when_triggered(
        self, manager: RiskManager
    ) -> None:
        manager.daily_state.circuit_breaker_triggered = True
        assert manager.check_circuit_breaker() is True

    def test_check_circuit_breaker_returns_false_within_limit(
        self, manager: RiskManager
    ) -> None:
        manager.update_pnl(-1000.0, is_realized=True)
        assert manager.daily_state.circuit_breaker_triggered is False

    def test_circuit_breaker_disabled(self) -> None:
        cfg = RiskConfig(circuit_breaker_enabled=False, max_daily_loss=1000.0)
        mgr = RiskManager(config=cfg)
        mgr.update_pnl(-2000.0, is_realized=True)
        assert mgr.daily_state.circuit_breaker_triggered is False


# =========================================================================
# reset_daily_state
# =========================================================================


class TestResetDailyState:
    def test_clears_everything(self, manager: RiskManager) -> None:
        manager.update_pnl(-3000.0, is_realized=True)
        manager.daily_state.total_trades = 10
        manager.daily_state.winning_trades = 5
        manager.daily_state.losing_trades = 5
        manager.daily_state.open_positions = 3
        manager.add_position("SYM1", 50000)

        manager.reset_daily_state()

        assert manager.daily_state.realized_pnl == 0.0
        assert manager.daily_state.unrealized_pnl == 0.0
        assert manager.daily_state.total_trades == 0
        assert manager.daily_state.open_positions == 0
        assert manager.daily_state.circuit_breaker_triggered is False

    def test_does_not_reset_emergency_stop(self, manager: RiskManager) -> None:
        """Emergency stop persists across daily resets."""
        manager.trigger_emergency_stop("test")
        manager.reset_daily_state()
        assert manager.emergency_stop is True


# =========================================================================
# update_pnl
# =========================================================================


class TestUpdatePnl:
    def test_accumulates_realized_pnl(self, manager: RiskManager) -> None:
        manager.update_pnl(1000.0, is_realized=True)
        manager.update_pnl(-500.0, is_realized=True)
        assert manager.daily_state.realized_pnl == pytest.approx(500.0)

    def test_unrealized_pnl_replaced(self, manager: RiskManager) -> None:
        """Unrealized PnL is set (not accumulated)."""
        manager.update_pnl(1000.0, is_realized=False)
        manager.update_pnl(-500.0, is_realized=False)
        assert manager.daily_state.unrealized_pnl == pytest.approx(-500.0)


# =========================================================================
# get_available_risk
# =========================================================================


class TestGetAvailableRisk:
    def test_decreases_with_losses(self, manager: RiskManager) -> None:
        initial = manager.get_available_risk()
        manager.update_pnl(-2000.0, is_realized=True)
        after_loss = manager.get_available_risk()
        assert after_loss < initial

    def test_full_budget_when_no_losses(self, manager: RiskManager) -> None:
        available = manager.get_available_risk()
        # effective_max_loss = min(5000, 250000*0.02=5000) = 5000
        assert available == pytest.approx(5000.0)

    def test_zero_after_hitting_limit(self, manager: RiskManager) -> None:
        manager.update_pnl(-5000.0, is_realized=True)
        assert manager.get_available_risk() == pytest.approx(0.0)


# =========================================================================
# trigger_emergency_stop
# =========================================================================


class TestEmergencyStop:
    def test_activates_stop(self, manager: RiskManager) -> None:
        assert manager.emergency_stop is False
        manager.trigger_emergency_stop("broker API down")
        assert manager.emergency_stop is True


# =========================================================================
# record_trade_result
# =========================================================================


class TestRecordTradeResult:
    def test_updates_win_loss_counts(self, manager: RiskManager) -> None:
        manager.record_trade_result(500.0)   # win
        manager.record_trade_result(-200.0)  # loss
        manager.record_trade_result(300.0)   # win
        manager.record_trade_result(0.0)     # breakeven (neither win nor loss)

        assert manager.daily_state.total_trades == 4
        assert manager.daily_state.winning_trades == 2
        assert manager.daily_state.losing_trades == 1
        assert manager.daily_state.realized_pnl == pytest.approx(600.0)


# =========================================================================
# get_risk_summary
# =========================================================================


class TestGetRiskSummary:
    def test_returns_complete_info(self, manager: RiskManager) -> None:
        manager.update_pnl(-1000.0, is_realized=True)
        summary = manager.get_risk_summary()

        expected_keys = {
            "date", "capital", "realized_pnl", "unrealized_pnl",
            "total_pnl", "total_trades", "winning_trades", "losing_trades",
            "open_positions", "max_open_positions", "daily_loss_limit",
            "available_risk", "circuit_breaker_enabled",
            "circuit_breaker_triggered", "emergency_stop", "position_values",
        }
        assert expected_keys.issubset(set(summary.keys()))
        assert summary["realized_pnl"] == -1000.0
        assert summary["capital"] == 250_000.0
        assert summary["circuit_breaker_enabled"] is True


# =========================================================================
# Custom RiskConfig
# =========================================================================


class TestCustomRiskConfig:
    def test_custom_config_works(self) -> None:
        cfg = RiskConfig(
            max_daily_loss=10_000.0,
            max_daily_loss_pct=0.05,
            max_position_size=500_000.0,
            max_open_positions=10,
            max_concentration_pct=0.50,
            max_risk_per_trade_pct=0.05,
            capital=1_000_000.0,
        )
        mgr = RiskManager(config=cfg)

        # A large trade that fits within the custom limits
        result = mgr.validate_trade(
            symbol="NSE:NIFTY50-INDEX",
            side="BUY",
            quantity=20,
            entry_price=22000.0,
            stop_loss=21900.0,
        )
        assert result.is_valid is True
