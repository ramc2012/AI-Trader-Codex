"""WebSocket endpoints for real-time dashboard updates.

Provides streaming JSON data for the trading dashboard via
FastAPI's native WebSocket support. Includes a connection manager
for tracking active clients.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.api.dependencies import (
    get_alert_manager,
    get_position_manager,
    get_risk_manager,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["WebSocket"])


# =========================================================================
# Connection Manager
# =========================================================================


class ConnectionManager:
    """Manage active WebSocket connections.

    Tracks connected clients and provides broadcast capability.
    """

    def __init__(self) -> None:
        self._connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        self._connections.append(websocket)
        logger.info(
            "websocket_connected",
            total=len(self._connections),
        )

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection from the registry."""
        if websocket in self._connections:
            self._connections.remove(websocket)
        logger.info(
            "websocket_disconnected",
            total=len(self._connections),
        )

    async def send_json(self, websocket: WebSocket, data: Dict[str, Any]) -> None:
        """Send a JSON message to a specific WebSocket."""
        await websocket.send_json(data)

    async def broadcast(self, data: Dict[str, Any]) -> None:
        """Broadcast a JSON message to all connected clients.

        Disconnects clients that raise errors during send.
        """
        disconnected: List[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_json(data)
            except Exception:
                disconnected.append(ws)

        for ws in disconnected:
            self.disconnect(ws)

    @property
    def active_connections(self) -> int:
        """Number of currently active connections."""
        return len(self._connections)


# Shared manager instances
dashboard_manager = ConnectionManager()
tick_manager = ConnectionManager()


# =========================================================================
# WebSocket Endpoints
# =========================================================================


@router.websocket("/ws/dashboard")
async def dashboard_ws(websocket: WebSocket) -> None:
    """Stream dashboard data every 1 second.

    Sends a JSON payload containing portfolio summary, risk state,
    and alert counts. The connection stays open until the client
    disconnects.
    """
    await dashboard_manager.connect(websocket)
    try:
        while True:
            payload = _build_dashboard_payload()
            await dashboard_manager.send_json(websocket, payload)
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        dashboard_manager.disconnect(websocket)
    except Exception:
        dashboard_manager.disconnect(websocket)


@router.websocket("/ws/ticks/{symbol:path}")
async def tick_ws(websocket: WebSocket, symbol: str) -> None:
    """Stream tick data for a symbol (placeholder).

    Currently sends a heartbeat every second. Real tick data
    integration will be added once the TickCollector WebSocket
    is wired in.

    Args:
        symbol: The trading symbol to stream ticks for.
    """
    await tick_manager.connect(websocket)
    try:
        while True:
            payload = {
                "type": "heartbeat",
                "symbol": symbol,
                "timestamp": datetime.now().isoformat(),
                "message": "Tick streaming placeholder",
            }
            await tick_manager.send_json(websocket, payload)
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        tick_manager.disconnect(websocket)
    except Exception:
        tick_manager.disconnect(websocket)


# =========================================================================
# Payload Builder
# =========================================================================


def _build_dashboard_payload() -> Dict[str, Any]:
    """Build the dashboard WebSocket payload from current manager state.

    Returns:
        Dictionary with portfolio, risk, and alert data.
    """
    try:
        pm = get_position_manager()
        portfolio = pm.get_portfolio_summary()
    except Exception:
        portfolio = {
            "position_count": 0,
            "total_market_value": 0.0,
            "total_unrealized_pnl": 0.0,
            "total_realized_pnl": 0.0,
            "total_pnl": 0.0,
            "positions": {},
        }

    try:
        rm = get_risk_manager()
        risk = rm.get_risk_summary()
    except Exception:
        risk = {
            "circuit_breaker_triggered": False,
            "emergency_stop": False,
            "available_risk": 0.0,
        }

    try:
        am = get_alert_manager()
        alert_counts = am.get_alert_counts()
    except Exception:
        alert_counts = {
            "info": 0,
            "warning": 0,
            "critical": 0,
            "emergency": 0,
        }

    return {
        "type": "dashboard_update",
        "timestamp": datetime.now().isoformat(),
        "portfolio": portfolio,
        "risk": risk,
        "alerts": alert_counts,
    }
