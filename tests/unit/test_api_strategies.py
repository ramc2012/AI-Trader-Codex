"""Tests for the strategy management API endpoints.

Validates the strategy lifecycle (enable/disable), executor summary,
and recent signal history endpoints exposed via /api/v1/strategies
and /api/v1/signals.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Tuple

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.dependencies import (
    get_order_manager,
    get_strategy_executor,
    reset_managers,
)
from src.api.main import create_app
from src.api.routes.strategies import _recent_signals, record_signal
from src.execution.order_manager import OrderManager
from src.execution.strategy_executor import StrategyExecutor
from src.strategies.directional.ema_crossover import EMACrossoverStrategy


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def app() -> Tuple[FastAPI, StrategyExecutor]:
    """Create a test FastAPI app with overridden dependencies.

    Yields:
        Tuple of (FastAPI application, StrategyExecutor instance).
    """
    reset_managers()
    application = create_app()
    om = OrderManager(paper_mode=True)
    executor = StrategyExecutor(paper_mode=True)
    executor.set_order_manager(om)
    application.dependency_overrides[get_strategy_executor] = lambda: executor
    application.dependency_overrides[get_order_manager] = lambda: om
    yield application, executor
    reset_managers()


@pytest.fixture
def client(app: Tuple[FastAPI, StrategyExecutor]) -> TestClient:
    """Create a test HTTP client from the app fixture.

    Args:
        app: Tuple of (FastAPI application, StrategyExecutor).

    Returns:
        A FastAPI TestClient.
    """
    application, _ = app
    return TestClient(application, raise_server_exceptions=False)


@pytest.fixture
def executor(app: Tuple[FastAPI, StrategyExecutor]) -> StrategyExecutor:
    """Extract the StrategyExecutor from the app fixture.

    Args:
        app: Tuple of (FastAPI application, StrategyExecutor).

    Returns:
        The StrategyExecutor instance used by the test app.
    """
    _, executor = app
    return executor


@pytest.fixture(autouse=True)
def clear_signals() -> None:
    """Clear the in-memory signal deque before each test."""
    _recent_signals.clear()


def _make_signal_dict(
    strategy_name: str = "test_strategy",
    symbol: str = "NSE:NIFTY50-INDEX",
    signal_type: str = "BUY",
    strength: str = "moderate",
    price: float = 22000.0,
) -> Dict[str, Any]:
    """Build a minimal signal dictionary compatible with SignalResponse.

    Args:
        strategy_name: Name of the strategy that produced the signal.
        symbol: Trading symbol.
        signal_type: Signal type (BUY, SELL, HOLD).
        strength: Signal strength (strong, moderate, weak).
        price: Signal price.

    Returns:
        Dictionary matching SignalResponse fields.
    """
    return {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "symbol": symbol,
        "signal_type": signal_type,
        "strength": strength,
        "price": price,
        "stop_loss": price - 100.0,
        "target": price + 200.0,
        "strategy_name": strategy_name,
        "metadata": {},
    }


# =========================================================================
# GET /api/v1/strategies Tests
# =========================================================================


class TestGetStrategies:
    """Tests for the GET /api/v1/strategies endpoint."""

    def test_empty_executor_returns_summary(
        self, client: TestClient
    ) -> None:
        """An executor with no strategies returns a valid summary."""
        resp = client.get("/api/v1/strategies")

        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "idle"
        assert data["paper_mode"] is True
        assert data["strategies_count"] == 0
        assert data["enabled_count"] == 0
        assert data["total_signals"] == 0
        assert data["total_trades"] == 0
        assert data["strategies"] == {}

    def test_summary_with_registered_strategy(
        self, client: TestClient, executor: StrategyExecutor
    ) -> None:
        """Summary reflects a registered and enabled strategy."""
        executor.register_strategy("test_ema", EMACrossoverStrategy())

        resp = client.get("/api/v1/strategies")

        assert resp.status_code == 200
        data = resp.json()
        assert data["strategies_count"] == 1
        assert data["enabled_count"] == 1
        assert "test_ema" in data["strategies"]
        strategy_info = data["strategies"]["test_ema"]
        assert strategy_info["enabled"] is True
        assert strategy_info["signals"] == 0
        assert strategy_info["trades"] == 0
        assert strategy_info["pnl"] == 0.0

    def test_summary_with_multiple_strategies(
        self, client: TestClient, executor: StrategyExecutor
    ) -> None:
        """Summary reflects multiple strategies with mixed enabled state."""
        executor.register_strategy("ema_fast", EMACrossoverStrategy(fast_period=5, slow_period=10))
        executor.register_strategy("ema_slow", EMACrossoverStrategy(fast_period=12, slow_period=26))
        executor.disable_strategy("ema_slow")

        resp = client.get("/api/v1/strategies")

        assert resp.status_code == 200
        data = resp.json()
        assert data["strategies_count"] == 2
        assert data["enabled_count"] == 1
        assert data["strategies"]["ema_fast"]["enabled"] is True
        assert data["strategies"]["ema_slow"]["enabled"] is False

    def test_summary_paper_mode_reflected(
        self, client: TestClient
    ) -> None:
        """The paper_mode flag is included in the response."""
        resp = client.get("/api/v1/strategies")

        assert resp.status_code == 200
        assert resp.json()["paper_mode"] is True


# =========================================================================
# POST /api/v1/strategies/{name}/enable and /disable Tests
# =========================================================================


class TestEnableDisable:
    """Tests for the enable and disable strategy endpoints."""

    def test_enable_existing_strategy(
        self, client: TestClient, executor: StrategyExecutor
    ) -> None:
        """Enabling a registered (but disabled) strategy succeeds."""
        executor.register_strategy("test_ema", EMACrossoverStrategy(), enabled=False)

        resp = client.post("/api/v1/strategies/test_ema/enable")

        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "Strategy 'test_ema' enabled."

        # Verify through the executor that it is actually enabled
        states = executor.get_strategy_states()
        assert states["test_ema"].enabled is True

    def test_disable_existing_strategy(
        self, client: TestClient, executor: StrategyExecutor
    ) -> None:
        """Disabling a registered and enabled strategy succeeds."""
        executor.register_strategy("test_ema", EMACrossoverStrategy())

        resp = client.post("/api/v1/strategies/test_ema/disable")

        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "Strategy 'test_ema' disabled."

        # Verify through the executor that it is actually disabled
        states = executor.get_strategy_states()
        assert states["test_ema"].enabled is False

    def test_enable_nonexistent_strategy_returns_404(
        self, client: TestClient
    ) -> None:
        """Attempting to enable a strategy that does not exist yields 404."""
        resp = client.post("/api/v1/strategies/nonexistent/enable")

        assert resp.status_code == 404
        data = resp.json()
        assert "nonexistent" in data["detail"]
        assert "not found" in data["detail"].lower()

    def test_disable_nonexistent_strategy_returns_404(
        self, client: TestClient
    ) -> None:
        """Attempting to disable a strategy that does not exist yields 404."""
        resp = client.post("/api/v1/strategies/nonexistent/disable")

        assert resp.status_code == 404
        data = resp.json()
        assert "nonexistent" in data["detail"]
        assert "not found" in data["detail"].lower()

    def test_enable_already_enabled_strategy_is_idempotent(
        self, client: TestClient, executor: StrategyExecutor
    ) -> None:
        """Enabling an already-enabled strategy succeeds without error."""
        executor.register_strategy("test_ema", EMACrossoverStrategy())

        resp = client.post("/api/v1/strategies/test_ema/enable")

        assert resp.status_code == 200
        states = executor.get_strategy_states()
        assert states["test_ema"].enabled is True

    def test_disable_already_disabled_strategy_is_idempotent(
        self, client: TestClient, executor: StrategyExecutor
    ) -> None:
        """Disabling an already-disabled strategy succeeds without error."""
        executor.register_strategy("test_ema", EMACrossoverStrategy(), enabled=False)

        resp = client.post("/api/v1/strategies/test_ema/disable")

        assert resp.status_code == 200
        states = executor.get_strategy_states()
        assert states["test_ema"].enabled is False

    def test_enable_then_disable_round_trip(
        self, client: TestClient, executor: StrategyExecutor
    ) -> None:
        """A strategy can be enabled and then disabled in sequence."""
        executor.register_strategy("test_ema", EMACrossoverStrategy(), enabled=False)

        resp_enable = client.post("/api/v1/strategies/test_ema/enable")
        assert resp_enable.status_code == 200
        assert executor.get_strategy_states()["test_ema"].enabled is True

        resp_disable = client.post("/api/v1/strategies/test_ema/disable")
        assert resp_disable.status_code == 200
        assert executor.get_strategy_states()["test_ema"].enabled is False

    def test_enable_reflected_in_summary(
        self, client: TestClient, executor: StrategyExecutor
    ) -> None:
        """After enabling a strategy the summary endpoint reflects the change."""
        executor.register_strategy("test_ema", EMACrossoverStrategy(), enabled=False)

        # Before enable
        summary_before = client.get("/api/v1/strategies").json()
        assert summary_before["enabled_count"] == 0

        client.post("/api/v1/strategies/test_ema/enable")

        # After enable
        summary_after = client.get("/api/v1/strategies").json()
        assert summary_after["enabled_count"] == 1


# =========================================================================
# GET /api/v1/signals Tests
# =========================================================================


class TestSignals:
    """Tests for the GET /api/v1/signals endpoint."""

    def test_empty_signals(self, client: TestClient) -> None:
        """When no signals have been recorded, the endpoint returns an empty list."""
        resp = client.get("/api/v1/signals")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_signals_with_prepopulated_data(self, client: TestClient) -> None:
        """Pre-populated signals are returned by the endpoint."""
        signal_dict = _make_signal_dict(strategy_name="ema_cross", signal_type="BUY")
        record_signal(signal_dict)

        resp = client.get("/api/v1/signals")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["strategy_name"] == "ema_cross"
        assert data[0]["signal_type"] == "BUY"
        assert data[0]["symbol"] == "NSE:NIFTY50-INDEX"

    def test_signals_multiple_returned_newest_first(
        self, client: TestClient
    ) -> None:
        """Multiple signals are returned newest-first."""
        for i in range(3):
            record_signal(
                _make_signal_dict(
                    strategy_name=f"strat_{i}",
                    price=22000.0 + i * 100,
                )
            )

        resp = client.get("/api/v1/signals")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3
        # Newest first: strat_2 should be first
        assert data[0]["strategy_name"] == "strat_2"
        assert data[1]["strategy_name"] == "strat_1"
        assert data[2]["strategy_name"] == "strat_0"

    def test_signals_filter_by_strategy(self, client: TestClient) -> None:
        """Signals can be filtered by strategy name."""
        record_signal(_make_signal_dict(strategy_name="alpha"))
        record_signal(_make_signal_dict(strategy_name="beta"))
        record_signal(_make_signal_dict(strategy_name="alpha"))

        resp = client.get("/api/v1/signals?strategy=alpha")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert all(s["strategy_name"] == "alpha" for s in data)

    def test_signals_filter_by_nonexistent_strategy_returns_empty(
        self, client: TestClient
    ) -> None:
        """Filtering by a strategy that has no signals returns empty list."""
        record_signal(_make_signal_dict(strategy_name="alpha"))

        resp = client.get("/api/v1/signals?strategy=nonexistent")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_signals_limit_parameter(self, client: TestClient) -> None:
        """The limit parameter restricts the number of signals returned."""
        for i in range(10):
            record_signal(_make_signal_dict(strategy_name=f"strat_{i}"))

        resp = client.get("/api/v1/signals?limit=3")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3
        # Should be the 3 newest (strat_9, strat_8, strat_7)
        assert data[0]["strategy_name"] == "strat_9"
        assert data[1]["strategy_name"] == "strat_8"
        assert data[2]["strategy_name"] == "strat_7"

    def test_signals_limit_with_filter(self, client: TestClient) -> None:
        """Limit applies after the strategy filter."""
        for i in range(5):
            record_signal(_make_signal_dict(strategy_name="target"))
        for i in range(3):
            record_signal(_make_signal_dict(strategy_name="other"))

        resp = client.get("/api/v1/signals?strategy=target&limit=2")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert all(s["strategy_name"] == "target" for s in data)

    def test_signals_default_limit_is_50(self, client: TestClient) -> None:
        """Without an explicit limit, at most 50 signals are returned."""
        for i in range(60):
            record_signal(_make_signal_dict(strategy_name=f"strat_{i}"))

        resp = client.get("/api/v1/signals")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 50

    def test_signals_limit_validation_minimum(self, client: TestClient) -> None:
        """A limit value below 1 is rejected with a 422."""
        resp = client.get("/api/v1/signals?limit=0")

        assert resp.status_code == 422

    def test_signals_limit_validation_maximum(self, client: TestClient) -> None:
        """A limit value above 200 is rejected with a 422."""
        resp = client.get("/api/v1/signals?limit=201")

        assert resp.status_code == 422

    def test_signals_malformed_entries_are_skipped(
        self, client: TestClient
    ) -> None:
        """Malformed signal dicts are silently skipped."""
        # Valid signal
        record_signal(_make_signal_dict(strategy_name="good"))
        # Malformed signal (missing required fields)
        record_signal({"bad": "data"})
        # Another valid signal
        record_signal(_make_signal_dict(strategy_name="also_good"))

        resp = client.get("/api/v1/signals")

        assert resp.status_code == 200
        data = resp.json()
        # Only the two valid signals should appear
        assert len(data) == 2
        names = [s["strategy_name"] for s in data]
        assert "good" in names
        assert "also_good" in names

    def test_signals_response_fields(self, client: TestClient) -> None:
        """Each signal in the response includes all expected fields."""
        record_signal(_make_signal_dict(
            strategy_name="field_test",
            symbol="NSE:NIFTYBANK-INDEX",
            signal_type="SELL",
            strength="strong",
            price=48000.0,
        ))

        resp = client.get("/api/v1/signals")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        signal = data[0]
        assert signal["symbol"] == "NSE:NIFTYBANK-INDEX"
        assert signal["signal_type"] == "SELL"
        assert signal["strength"] == "strong"
        assert signal["price"] == 48000.0
        assert signal["stop_loss"] == 47900.0
        assert signal["target"] == 48200.0
        assert signal["strategy_name"] == "field_test"
        assert "timestamp" in signal
        assert "metadata" in signal

    def test_signals_deque_cleared_between_tests(
        self, client: TestClient
    ) -> None:
        """Verify the autouse fixture correctly clears the deque.

        This test intentionally does not record any signals and checks
        that the deque is empty, confirming the clear_signals fixture works.
        """
        resp = client.get("/api/v1/signals")

        assert resp.status_code == 200
        assert resp.json() == []
