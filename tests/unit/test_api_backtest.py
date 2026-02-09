"""Tests for the backtest API routes.

Covers POST /api/v1/backtest/run, GET /api/v1/backtest/results,
and GET /api/v1/backtest/results/{result_id} endpoints.

Note: Some strategies (ema_crossover, macd) may produce only winning
trades with the sample data, yielding profit_factor=inf which is not
JSON-serializable. Tests use strategies known to produce finite metrics
(rsi_reversal, bollinger, supertrend) for reliable assertions.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import src.api.routes.backtest as backtest_module
from src.api.dependencies import reset_managers
from src.api.main import create_app
from src.api.routes.backtest import _STRATEGY_REGISTRY


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def app():
    """Create a fresh FastAPI application with reset backtest cache."""
    reset_managers()
    # Reset the in-memory backtest result cache so tests are isolated
    backtest_module._result_cache.clear()
    backtest_module._next_id = 1
    application = create_app()
    yield application
    reset_managers()


@pytest.fixture
def client(app) -> TestClient:
    """Create a test HTTP client bound to the app."""
    return TestClient(app, raise_server_exceptions=False)


# Strategies that produce both wins and losses with sample data,
# avoiding the profit_factor=inf JSON serialization issue.
FINITE_STRATEGIES = ["rsi_reversal", "bollinger", "supertrend"]


# =========================================================================
# POST /backtest/run
# =========================================================================


class TestRunBacktest:
    """Test running a strategy backtest via the API."""

    def test_run_rsi_reversal(self, client: TestClient) -> None:
        """Running rsi_reversal returns a valid BacktestResultResponse."""
        resp = client.post(
            "/api/v1/backtest/run",
            json={
                "strategy": "rsi_reversal",
                "symbol": "NSE:NIFTY50-INDEX",
                "initial_capital": 100000,
            },
        )

        assert resp.status_code == 200
        data = resp.json()

        # Verify all required fields are present
        assert data["id"] == 1
        assert data["strategy_name"] is not None
        assert data["symbol"] == "NSE:NIFTY50-INDEX"
        assert data["initial_capital"] == 100000.0
        assert "final_capital" in data
        assert "total_trades" in data
        assert "winning_trades" in data
        assert "losing_trades" in data
        assert "win_rate" in data
        assert "total_pnl" in data
        assert "total_return_pct" in data
        assert "max_drawdown" in data
        assert "profit_factor" in data
        assert "avg_win" in data
        assert "avg_loss" in data
        assert "trades" in data
        assert "start_date" in data
        assert "end_date" in data

    def test_run_bollinger(self, client: TestClient) -> None:
        """Running bollinger returns a successful response."""
        resp = client.post(
            "/api/v1/backtest/run",
            json={"strategy": "bollinger"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 1
        assert isinstance(data["total_trades"], int)

    def test_run_supertrend(self, client: TestClient) -> None:
        """Running supertrend returns a successful response."""
        resp = client.post(
            "/api/v1/backtest/run",
            json={"strategy": "supertrend"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 1
        assert isinstance(data["total_trades"], int)
        assert isinstance(data["profit_factor"], float)

    def test_result_id_increments(self, client: TestClient) -> None:
        """Each successive backtest run gets an incrementing ID."""
        resp1 = client.post(
            "/api/v1/backtest/run",
            json={"strategy": "rsi_reversal"},
        )
        resp2 = client.post(
            "/api/v1/backtest/run",
            json={"strategy": "bollinger"},
        )

        assert resp1.json()["id"] == 1
        assert resp2.json()["id"] == 2

    def test_trades_list_structure(self, client: TestClient) -> None:
        """The trades list in the response has the correct per-trade fields."""
        resp = client.post(
            "/api/v1/backtest/run",
            json={"strategy": "rsi_reversal"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_trades"] > 0
        trade = data["trades"][0]
        assert "entry_time" in trade
        assert "symbol" in trade
        assert "side" in trade
        assert "entry_price" in trade
        assert "pnl" in trade
        assert "pnl_pct" in trade

    def test_default_symbol_applied(self, client: TestClient) -> None:
        """When symbol is omitted, the default NSE:NIFTY50-INDEX is used."""
        resp = client.post(
            "/api/v1/backtest/run",
            json={"strategy": "supertrend"},
        )

        assert resp.status_code == 200
        assert resp.json()["symbol"] == "NSE:NIFTY50-INDEX"

    def test_custom_initial_capital(self, client: TestClient) -> None:
        """The initial_capital from the request is reflected in the response."""
        resp = client.post(
            "/api/v1/backtest/run",
            json={"strategy": "bollinger", "initial_capital": 500000},
        )

        assert resp.status_code == 200
        assert resp.json()["initial_capital"] == 500000.0


# =========================================================================
# POST /backtest/run -- invalid input
# =========================================================================


class TestRunBacktestInvalid:
    """Test error handling for invalid backtest requests."""

    def test_unknown_strategy_returns_400(self, client: TestClient) -> None:
        """An unregistered strategy name returns 400 with helpful detail."""
        resp = client.post(
            "/api/v1/backtest/run",
            json={"strategy": "nonexistent_strategy"},
        )

        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "Unknown strategy" in detail
        assert "nonexistent_strategy" in detail
        # The error message should list available strategies
        assert "ema_crossover" in detail

    def test_empty_strategy_returns_400(self, client: TestClient) -> None:
        """An empty strategy name returns 400."""
        resp = client.post(
            "/api/v1/backtest/run",
            json={"strategy": ""},
        )

        assert resp.status_code == 400

    def test_missing_strategy_field_returns_422(self, client: TestClient) -> None:
        """Omitting the required 'strategy' field returns 422 validation error."""
        resp = client.post(
            "/api/v1/backtest/run",
            json={"symbol": "NSE:NIFTY50-INDEX"},
        )

        assert resp.status_code == 422


# =========================================================================
# GET /backtest/results
# =========================================================================


class TestListResults:
    """Test listing cached backtest results."""

    def test_empty_results_list(self, client: TestClient) -> None:
        """An empty cache returns an empty list."""
        resp = client.get("/api/v1/backtest/results")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_after_single_run(self, client: TestClient) -> None:
        """After one backtest run, the list contains exactly one result."""
        client.post(
            "/api/v1/backtest/run",
            json={"strategy": "rsi_reversal"},
        )

        resp = client.get("/api/v1/backtest/results")

        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1
        assert results[0]["id"] == 1

    def test_list_after_multiple_runs(self, client: TestClient) -> None:
        """After multiple backtest runs, all results appear in the list."""
        for strategy in FINITE_STRATEGIES:
            client.post(
                "/api/v1/backtest/run",
                json={"strategy": strategy},
            )

        resp = client.get("/api/v1/backtest/results")

        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == len(FINITE_STRATEGIES)
        ids = [r["id"] for r in results]
        assert ids == list(range(1, len(FINITE_STRATEGIES) + 1))


# =========================================================================
# GET /backtest/results/{result_id}
# =========================================================================


class TestGetResult:
    """Test fetching a single backtest result by ID."""

    def test_get_valid_result(self, client: TestClient) -> None:
        """Fetching a valid result ID returns the correct result."""
        post_resp = client.post(
            "/api/v1/backtest/run",
            json={"strategy": "bollinger"},
        )
        assert post_resp.status_code == 200
        result_id = post_resp.json()["id"]

        resp = client.get(f"/api/v1/backtest/results/{result_id}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == result_id
        assert data["symbol"] == "NSE:NIFTY50-INDEX"

    def test_get_nonexistent_result_returns_404(self, client: TestClient) -> None:
        """Fetching a non-existent result ID returns 404."""
        resp = client.get("/api/v1/backtest/results/999")

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_get_result_matches_run_response(self, client: TestClient) -> None:
        """The GET result matches the original POST response exactly."""
        post_resp = client.post(
            "/api/v1/backtest/run",
            json={"strategy": "bollinger"},
        )
        post_data = post_resp.json()

        get_resp = client.get(f"/api/v1/backtest/results/{post_data['id']}")
        get_data = get_resp.json()

        assert post_data == get_data
