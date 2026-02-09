"""Tests for the risk management API routes.

Validates the /risk/summary and /risk/metrics endpoints, ensuring
correct serialization of RiskManager state and RiskCalculator output
through the FastAPI dependency injection layer.
"""

from __future__ import annotations

from datetime import date
from typing import Tuple

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.dependencies import (
    get_position_manager,
    get_risk_calculator,
    get_risk_manager,
    reset_managers,
)
from src.api.main import create_app
from src.execution.position_manager import PositionManager, PositionSide
from src.risk.risk_calculator import RiskCalculator
from src.risk.risk_manager import RiskConfig, RiskManager


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def app() -> Tuple[FastAPI, RiskManager, RiskCalculator, PositionManager]:
    """Create a test app with fresh manager instances injected.

    Yields:
        Tuple of (FastAPI app, RiskManager, RiskCalculator, PositionManager).
    """
    reset_managers()
    application = create_app()

    rm = RiskManager(config=RiskConfig())
    rc = RiskCalculator()
    pm = PositionManager()

    application.dependency_overrides[get_risk_manager] = lambda: rm
    application.dependency_overrides[get_risk_calculator] = lambda: rc
    application.dependency_overrides[get_position_manager] = lambda: pm

    yield application, rm, rc, pm

    reset_managers()


@pytest.fixture
def client(app: Tuple[FastAPI, RiskManager, RiskCalculator, PositionManager]) -> TestClient:
    """Create a TestClient bound to the test app.

    Args:
        app: The app fixture tuple.

    Returns:
        TestClient instance.
    """
    application, *_ = app
    return TestClient(application, raise_server_exceptions=False)


# =========================================================================
# Risk Summary Endpoint Tests
# =========================================================================


class TestRiskSummary:
    """Tests for GET /api/v1/risk/summary."""

    def test_default_risk_summary(
        self,
        app: Tuple[FastAPI, RiskManager, RiskCalculator, PositionManager],
        client: TestClient,
    ) -> None:
        """Default summary should reflect a fresh RiskManager state."""
        _, rm, _, _ = app

        resp = client.get("/api/v1/risk/summary")
        assert resp.status_code == 200

        data = resp.json()

        # Verify all expected keys are present
        expected_keys = {
            "date",
            "capital",
            "realized_pnl",
            "unrealized_pnl",
            "total_pnl",
            "total_trades",
            "winning_trades",
            "losing_trades",
            "open_positions",
            "max_open_positions",
            "daily_loss_limit",
            "available_risk",
            "circuit_breaker_triggered",
            "emergency_stop",
            "position_values",
        }
        assert set(data.keys()) == expected_keys

        # Default values for a fresh RiskManager
        assert data["date"] == str(date.today())
        assert data["capital"] == 250000.0
        assert data["realized_pnl"] == 0.0
        assert data["unrealized_pnl"] == 0.0
        assert data["total_pnl"] == 0.0
        assert data["total_trades"] == 0
        assert data["winning_trades"] == 0
        assert data["losing_trades"] == 0
        assert data["open_positions"] == 0
        assert data["max_open_positions"] == 5
        assert data["circuit_breaker_triggered"] is False
        assert data["emergency_stop"] is False
        assert data["position_values"] == {}

        # daily_loss_limit should be min(5000, 250000 * 0.02) = 5000
        assert data["daily_loss_limit"] == 5000.0
        assert data["available_risk"] == 5000.0

    def test_summary_with_updated_state(
        self,
        app: Tuple[FastAPI, RiskManager, RiskCalculator, PositionManager],
        client: TestClient,
    ) -> None:
        """Summary should reflect recorded trades and position changes."""
        _, rm, _, _ = app

        # Record a winning trade
        rm.record_trade_result(pnl=1500.0)
        # Record a losing trade
        rm.record_trade_result(pnl=-800.0)
        # Add a tracked position
        rm.add_position("NSE:NIFTY50-INDEX", 50000.0)
        # Set unrealized PnL
        rm.update_pnl(pnl=200.0, is_realized=False)

        resp = client.get("/api/v1/risk/summary")
        assert resp.status_code == 200

        data = resp.json()

        assert data["total_trades"] == 2
        assert data["winning_trades"] == 1
        assert data["losing_trades"] == 1
        # Realized = 1500 + (-800) = 700
        assert data["realized_pnl"] == 700.0
        assert data["unrealized_pnl"] == 200.0
        assert data["total_pnl"] == 900.0
        assert data["open_positions"] == 1
        assert data["position_values"] == {"NSE:NIFTY50-INDEX": 50000.0}
        assert data["circuit_breaker_triggered"] is False
        assert data["emergency_stop"] is False

    def test_summary_after_circuit_breaker(
        self,
        app: Tuple[FastAPI, RiskManager, RiskCalculator, PositionManager],
        client: TestClient,
    ) -> None:
        """Summary should reflect triggered circuit breaker state."""
        _, rm, _, _ = app

        # Force a large loss exceeding the daily limit (5000)
        rm.record_trade_result(pnl=-5500.0)

        resp = client.get("/api/v1/risk/summary")
        assert resp.status_code == 200

        data = resp.json()
        assert data["circuit_breaker_triggered"] is True
        assert data["realized_pnl"] == -5500.0
        assert data["available_risk"] == 0.0

    def test_summary_after_emergency_stop(
        self,
        app: Tuple[FastAPI, RiskManager, RiskCalculator, PositionManager],
        client: TestClient,
    ) -> None:
        """Summary should reflect emergency stop state."""
        _, rm, _, _ = app

        rm.trigger_emergency_stop(reason="Manual intervention")

        resp = client.get("/api/v1/risk/summary")
        assert resp.status_code == 200

        data = resp.json()
        assert data["emergency_stop"] is True


# =========================================================================
# Risk Metrics Endpoint Tests
# =========================================================================


class TestRiskMetrics:
    """Tests for GET /api/v1/risk/metrics."""

    def test_metrics_with_no_trades(
        self,
        app: Tuple[FastAPI, RiskManager, RiskCalculator, PositionManager],
        client: TestClient,
    ) -> None:
        """Metrics should return zeros when there are no closed trades."""
        resp = client.get("/api/v1/risk/metrics")
        assert resp.status_code == 200

        data = resp.json()

        # All numeric fields should be zero
        assert data["sharpe_ratio"] == 0.0
        assert data["sortino_ratio"] == 0.0
        assert data["calmar_ratio"] == 0.0
        assert data["max_drawdown"] == 0.0
        assert data["max_drawdown_duration"] == 0
        assert data["var_95"] == 0.0
        assert data["var_99"] == 0.0
        assert data["cvar_95"] == 0.0
        assert data["volatility"] == 0.0
        assert data["downside_volatility"] == 0.0
        assert data["profit_factor"] == 0.0
        assert data["win_rate"] == 0.0
        assert data["avg_win"] == 0.0
        assert data["avg_loss"] == 0.0
        assert data["expectancy"] == 0.0
        assert data["total_return"] == 0.0
        assert data["annualized_return"] == 0.0

    def test_metrics_after_closing_trades(
        self,
        app: Tuple[FastAPI, RiskManager, RiskCalculator, PositionManager],
        client: TestClient,
    ) -> None:
        """Metrics should compute non-zero values from closed trade PnLs."""
        _, _, _, pm = app

        # Open and close several positions to create trade history
        pm.open_position(
            symbol="NSE:NIFTY50-INDEX",
            quantity=50,
            side=PositionSide.LONG,
            price=100.0,
            strategy_tag="test",
        )
        pm.close_position("NSE:NIFTY50-INDEX", price=110.0)  # pnl = +500

        pm.open_position(
            symbol="NSE:NIFTYBANK-INDEX",
            quantity=25,
            side=PositionSide.LONG,
            price=200.0,
            strategy_tag="test",
        )
        pm.close_position("NSE:NIFTYBANK-INDEX", price=190.0)  # pnl = -250

        pm.open_position(
            symbol="NSE:NIFTY50-INDEX",
            quantity=30,
            side=PositionSide.SHORT,
            price=150.0,
            strategy_tag="test",
        )
        pm.close_position("NSE:NIFTY50-INDEX", price=140.0)  # pnl = +300

        # Verify the PositionManager recorded the trades correctly
        closed = pm.get_closed_trades()
        assert len(closed) == 3
        assert closed[0]["pnl"] == 500.0
        assert closed[1]["pnl"] == -250.0
        assert closed[2]["pnl"] == 300.0

        resp = client.get("/api/v1/risk/metrics")
        assert resp.status_code == 200

        data = resp.json()

        # Verify non-zero metrics with 2 wins / 1 loss
        assert data["win_rate"] > 0.0
        assert data["avg_win"] > 0.0
        assert data["avg_loss"] < 0.0
        assert data["profit_factor"] > 0.0
        assert data["total_return"] != 0.0

        # Verify expected keys are present
        expected_keys = {
            "sharpe_ratio",
            "sortino_ratio",
            "calmar_ratio",
            "max_drawdown",
            "max_drawdown_duration",
            "var_95",
            "var_99",
            "cvar_95",
            "volatility",
            "downside_volatility",
            "profit_factor",
            "win_rate",
            "avg_win",
            "avg_loss",
            "expectancy",
            "total_return",
            "annualized_return",
        }
        assert set(data.keys()) == expected_keys

    def test_metrics_mostly_winning_trades(
        self,
        app: Tuple[FastAPI, RiskManager, RiskCalculator, PositionManager],
        client: TestClient,
    ) -> None:
        """Metrics should handle a predominantly winning trade series.

        Note: A 100% win-rate produces profit_factor=inf which cannot be
        serialized to JSON. We include one tiny loss to exercise the
        high-win-rate path through the API without triggering inf.
        """
        _, _, _, pm = app

        pm.open_position("SYM_A", 10, PositionSide.LONG, 100.0)
        pm.close_position("SYM_A", price=100.50)  # pnl = +5.0

        pm.open_position("SYM_B", 20, PositionSide.LONG, 50.0)
        pm.close_position("SYM_B", price=50.20)  # pnl = +4.0

        pm.open_position("SYM_C", 10, PositionSide.LONG, 80.0)
        pm.close_position("SYM_C", price=80.30)  # pnl = +3.0

        # Include one tiny loss to avoid inf profit_factor
        pm.open_position("SYM_D", 1, PositionSide.LONG, 100.0)
        pm.close_position("SYM_D", price=99.90)  # pnl = -0.10

        resp = client.get("/api/v1/risk/metrics")
        assert resp.status_code == 200

        data = resp.json()
        assert data["win_rate"] == 0.75  # 3 wins out of 4 trades
        assert data["avg_win"] > 0.0
        assert data["avg_loss"] < 0.0
        assert data["profit_factor"] > 1.0

    def test_metrics_all_losing_trades(
        self,
        app: Tuple[FastAPI, RiskManager, RiskCalculator, PositionManager],
        client: TestClient,
    ) -> None:
        """Metrics should handle the case where all trades are losers.

        Uses small PnL values to avoid overflow in the annualized return
        calculation (which treats raw PnL values as return fractions).
        """
        _, _, _, pm = app

        pm.open_position("SYM_A", 10, PositionSide.LONG, 100.0)
        pm.close_position("SYM_A", price=99.50)  # pnl = -5.0

        pm.open_position("SYM_B", 20, PositionSide.LONG, 50.0)
        pm.close_position("SYM_B", price=49.80)  # pnl = -4.0

        pm.open_position("SYM_C", 10, PositionSide.LONG, 80.0)
        pm.close_position("SYM_C", price=79.70)  # pnl = -3.0

        resp = client.get("/api/v1/risk/metrics")
        assert resp.status_code == 200

        data = resp.json()
        assert data["win_rate"] == 0.0
        assert data["avg_win"] == 0.0
        assert data["avg_loss"] < 0.0
        assert data["max_drawdown"] < 0.0
        assert data["profit_factor"] == 0.0
