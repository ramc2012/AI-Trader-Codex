"""Tests for the WebSocket API routes and ConnectionManager.

Covers WS /api/v1/ws/dashboard, WS /api/v1/ws/ticks/{symbol},
and the ConnectionManager helper class.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api import dependencies as deps
from src.api.dependencies import reset_managers
from src.api.main import create_app
from src.api.routes.websocket import ConnectionManager
from src.execution.position_manager import PositionManager
from src.monitoring.alerts import AlertManager
from src.risk.risk_manager import RiskConfig, RiskManager


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def app():
    """Create a fresh FastAPI application with pre-initialized singletons.

    The WebSocket route calls get_position_manager(), get_risk_manager(),
    and get_alert_manager() directly (not via Depends()), so we set
    the module-level singletons in the dependencies module.
    """
    reset_managers()
    # Pre-initialize the dependency singletons so the dashboard
    # payload builder can access them without DB or external services.
    deps._position_manager = PositionManager()
    deps._risk_manager = RiskManager(config=RiskConfig())
    deps._alert_manager = AlertManager()

    application = create_app()
    yield application
    reset_managers()


@pytest.fixture
def client(app) -> TestClient:
    """Create a test HTTP client bound to the app."""
    return TestClient(app, raise_server_exceptions=False)


# =========================================================================
# ConnectionManager Unit Tests
# =========================================================================


class TestConnectionManager:
    """Test the WebSocket ConnectionManager helper class."""

    def test_initial_state(self) -> None:
        """A new ConnectionManager has zero active connections."""
        manager = ConnectionManager()
        assert manager.active_connections == 0

    @pytest.mark.anyio
    async def test_connect_increments_count(self) -> None:
        """Connecting a WebSocket increases the active connection count."""
        manager = ConnectionManager()
        ws = AsyncMock()
        await manager.connect(ws)

        assert manager.active_connections == 1
        ws.accept.assert_awaited_once()

    @pytest.mark.anyio
    async def test_disconnect_decrements_count(self) -> None:
        """Disconnecting a WebSocket decreases the active connection count."""
        manager = ConnectionManager()
        ws = AsyncMock()
        await manager.connect(ws)
        assert manager.active_connections == 1

        manager.disconnect(ws)
        assert manager.active_connections == 0

    @pytest.mark.anyio
    async def test_disconnect_nonexistent_is_safe(self) -> None:
        """Disconnecting a WebSocket that was never connected is a no-op."""
        manager = ConnectionManager()
        ws = AsyncMock()
        manager.disconnect(ws)  # Should not raise
        assert manager.active_connections == 0

    @pytest.mark.anyio
    async def test_multiple_connections(self) -> None:
        """Multiple WebSockets can be tracked simultaneously."""
        manager = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        ws3 = AsyncMock()

        await manager.connect(ws1)
        await manager.connect(ws2)
        await manager.connect(ws3)

        assert manager.active_connections == 3

        manager.disconnect(ws2)
        assert manager.active_connections == 2

    @pytest.mark.anyio
    async def test_send_json(self) -> None:
        """send_json delegates to the WebSocket's send_json method."""
        manager = ConnectionManager()
        ws = AsyncMock()
        await manager.connect(ws)

        payload = {"type": "test", "value": 42}
        await manager.send_json(ws, payload)
        ws.send_json.assert_awaited_once_with(payload)

    @pytest.mark.anyio
    async def test_broadcast_sends_to_all(self) -> None:
        """broadcast sends the message to every connected WebSocket."""
        manager = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await manager.connect(ws1)
        await manager.connect(ws2)

        payload = {"type": "broadcast", "data": "hello"}
        await manager.broadcast(payload)

        ws1.send_json.assert_awaited_once_with(payload)
        ws2.send_json.assert_awaited_once_with(payload)

    @pytest.mark.anyio
    async def test_broadcast_removes_failed_connections(self) -> None:
        """broadcast removes connections that raise errors during send."""
        manager = ConnectionManager()
        ws_good = AsyncMock()
        ws_bad = AsyncMock()
        ws_bad.send_json.side_effect = Exception("connection lost")

        await manager.connect(ws_good)
        await manager.connect(ws_bad)
        assert manager.active_connections == 2

        await manager.broadcast({"type": "test"})

        # The failed connection should be removed
        assert manager.active_connections == 1


# =========================================================================
# WS /ws/dashboard Tests
# =========================================================================


class TestDashboardWebSocket:
    """Test the dashboard WebSocket endpoint."""

    def test_connect_and_receive_first_message(self, client: TestClient) -> None:
        """Connecting to /ws/dashboard yields a dashboard_update message."""
        with client.websocket_connect("/api/v1/ws/dashboard") as ws:
            data = ws.receive_json()

            assert data["type"] == "dashboard_update"
            assert "timestamp" in data

    def test_message_contains_portfolio(self, client: TestClient) -> None:
        """The dashboard message includes a portfolio section."""
        with client.websocket_connect("/api/v1/ws/dashboard") as ws:
            data = ws.receive_json()

            assert "portfolio" in data
            portfolio = data["portfolio"]
            assert "position_count" in portfolio
            assert "total_market_value" in portfolio
            assert "total_unrealized_pnl" in portfolio
            assert "total_realized_pnl" in portfolio
            assert "total_pnl" in portfolio

    def test_message_contains_risk(self, client: TestClient) -> None:
        """The dashboard message includes a risk section."""
        with client.websocket_connect("/api/v1/ws/dashboard") as ws:
            data = ws.receive_json()

            assert "risk" in data
            risk = data["risk"]
            assert "circuit_breaker_triggered" in risk
            assert "emergency_stop" in risk
            assert "available_risk" in risk

    def test_message_contains_alerts(self, client: TestClient) -> None:
        """The dashboard message includes an alerts section."""
        with client.websocket_connect("/api/v1/ws/dashboard") as ws:
            data = ws.receive_json()

            assert "alerts" in data
            alerts = data["alerts"]
            assert "info" in alerts
            assert "warning" in alerts
            assert "critical" in alerts
            assert "emergency" in alerts

    def test_portfolio_values_with_no_positions(self, client: TestClient) -> None:
        """With no positions, portfolio values are zero."""
        with client.websocket_connect("/api/v1/ws/dashboard") as ws:
            data = ws.receive_json()

            portfolio = data["portfolio"]
            assert portfolio["position_count"] == 0
            assert portfolio["total_market_value"] == 0.0
            assert portfolio["total_unrealized_pnl"] == 0.0


# =========================================================================
# WS /ws/ticks/{symbol} Tests
# =========================================================================


class TestTickWebSocket:
    """Test the tick streaming WebSocket endpoint."""

    def test_connect_and_receive_heartbeat(self, client: TestClient) -> None:
        """Connecting to /ws/ticks/{symbol} yields a heartbeat message."""
        with client.websocket_connect("/api/v1/ws/ticks/NSE:NIFTY50-INDEX") as ws:
            data = ws.receive_json()

            assert data["type"] == "heartbeat"
            assert data["symbol"] == "NSE:NIFTY50-INDEX"

    def test_heartbeat_message_structure(self, client: TestClient) -> None:
        """The heartbeat message has the expected fields."""
        with client.websocket_connect("/api/v1/ws/ticks/NSE:NIFTY50-INDEX") as ws:
            data = ws.receive_json()

            assert "type" in data
            assert "symbol" in data
            assert "timestamp" in data
            assert "message" in data
            assert data["message"] == "waiting_for_tick"

    def test_tick_ws_with_different_symbol(self, client: TestClient) -> None:
        """The symbol in the URL is echoed back in the heartbeat message."""
        with client.websocket_connect("/api/v1/ws/ticks/NSE:NIFTYBANK-INDEX") as ws:
            data = ws.receive_json()

            assert data["symbol"] == "NSE:NIFTYBANK-INDEX"
