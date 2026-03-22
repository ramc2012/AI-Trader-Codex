"""Tests for US swing radar API endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

import src.api.routes.us_swing_radar as us_swing_radar_module
from src.api.dependencies import reset_managers
from src.api.main import create_app


class _StubScorer:
    def research_status(self) -> dict[str, object]:
        return {
            "ready": True,
            "requested_symbols": 200,
            "downloaded_symbols": 197,
            "dataset_rows": 512345,
            "dataset_symbols": 197,
            "start_date": "2016-01-01",
            "end_date": "2026-03-19",
            "failed_symbols": ["PARA"],
            "selected_short": {"multiplier": 1.5, "positive_rate": 0.108},
            "selected_long": {"multiplier": 3.0, "positive_rate": 0.182},
            "tuning": {"best_filters": {"min_score": 68.0, "min_probability": 0.45, "min_edge": 0.06}},
        }

    def list_latest_candidates(self, **_: object) -> list[dict[str, object]]:
        return [
            {
                "symbol": "AAPL",
                "spot_symbol": "US:AAPL",
                "sector": "Technology",
                "price": 210.0,
                "date": "2026-03-19",
                "source": "research_snapshot",
                "direction": "up",
                "horizon": "10_15D",
                "score": 80.0,
                "strength": "strong",
                "direction_probability": 0.57,
                "neutral_probability": 0.24,
                "direction_edge": 0.33,
                "allow_overnight": True,
                "planned_holding_days": 15,
                "expected_move_pct": 7.2,
                "stop_loss": 202.0,
                "target": 225.0,
                "atr_pct": 2.4,
                "market_regime": "bull",
                "baseline_hit_rate": 18.2,
                "matched_conditions": [],
            }
        ]


def test_us_swing_radar_overview_endpoint(monkeypatch) -> None:
    reset_managers()
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    monkeypatch.setattr(us_swing_radar_module, "USSwingLiveScorer", lambda: _StubScorer())

    try:
        response = client.get("/api/v1/us-swing-radar/overview?limit=5&min_score=55")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["research"]["ready"] is True
        assert body["research"]["downloaded_symbols"] == 197
        assert body["agent"]["expected_us_symbols"] == 200
        assert body["candidates"][0]["symbol"] == "AAPL"
    finally:
        reset_managers()

