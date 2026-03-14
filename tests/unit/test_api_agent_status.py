"""Tests for AI agent status endpoint extensions."""

from __future__ import annotations

from fastapi.testclient import TestClient

import src.api.routes.agent as agent_module
from src.api.dependencies import reset_managers
from src.api.main import create_app


def test_agent_status_includes_execution_core_snapshot(monkeypatch) -> None:
    reset_managers()
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    async def _fake_execution_core_status() -> dict[str, object]:
        return {
            "reachable": True,
            "url": "http://execution-core:8081",
            "health": {"status": "ok", "nats_connected": True, "signal_candidates": 4},
            "stats": {
                "status": "running",
                "signal_subject": "ai_trader.execution.signals",
                "counters": {"signal_candidates": 4},
                "signal_engine": {"signal_timeframes": ["1", "3", "5"]},
                "latest_signals": [{"symbol": "CRYPTO:BTCUSDT", "signal_type": "BUY"}],
            },
        }

    monkeypatch.setattr(agent_module, "_execution_core_status_snapshot", _fake_execution_core_status)

    try:
        response = client.get("/api/v1/agent/status")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["execution_core_status"]["reachable"] is True
        assert body["execution_core_status"]["health"]["signal_candidates"] == 4
        assert body["execution_core_status"]["stats"]["signal_subject"] == "ai_trader.execution.signals"
    finally:
        reset_managers()
