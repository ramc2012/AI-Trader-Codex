"""Tests for profile swing radar API endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

import src.api.routes.profile_swing_radar as profile_swing_radar_module
from src.api.dependencies import reset_managers
from src.api.main import create_app


class _StubScorer:
    def research_status(self) -> dict[str, object]:
        return {
            "ready": True,
            "dataset_rows": 12000,
            "dataset_symbols": 220,
            "start_date": "2023-04-10",
            "end_date": "2026-03-20",
            "coverage_symbols": 220,
            "models_available": ["nse_stock_5pct_direction_rf.joblib"],
            "summary": [
                {
                    "market": "NSE",
                    "asset_type": "stock",
                    "target": "5pct",
                    "rows": 6200,
                    "symbols": 183,
                    "hit_rate": 0.155,
                    "top_condition": "value_stack_bullish & open_drive_up",
                    "top_condition_hit_rate": 0.31,
                    "top_condition_lift": 2.0,
                }
            ],
        }

    def list_latest_candidates(self, **kwargs: object) -> list[dict[str, object]]:
        variant = str(kwargs.get("variant") or "classic")
        return [
            {
                "symbol": "RELIANCE",
                "spot_symbol": "NSE:RELIANCE-EQ",
                "market": "NSE",
                "asset_type": "stock",
                "date": "2026-03-20",
                "source": "research_snapshot",
                "variant": variant,
                "direction": "up",
                "target_name": "5pct",
                "score": 81.0 if variant == "ai" else 76.0,
                "strength": "strong",
                "direction_probability": 0.59,
                "neutral_probability": 0.24,
                "direction_edge": 0.35,
                "allow_overnight": True,
                "planned_holding_days": 2,
                "expected_move_pct": 5.6,
                "stop_loss": 2450.0,
                "target": 2620.0,
                "atr_pct": 2.2,
                "market_regime": "bull",
                "baseline_hit_rate": 18.4,
                "matched_conditions": [],
                "model_available": variant == "ai",
            }
        ]


def test_profile_swing_radar_overview_endpoint(monkeypatch) -> None:
    reset_managers()
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    monkeypatch.setattr(profile_swing_radar_module, "ProfileSwingLiveScorer", lambda: _StubScorer())

    try:
        response = client.get("/api/v1/profile-swing-radar/overview?limit=4&min_score=55")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["research"]["ready"] is True
        assert body["research"]["dataset_symbols"] == 220
        assert body["classic_candidates"][0]["symbol"] == "RELIANCE"
        assert body["ai_candidates"][0]["variant"] == "ai"
        assert "Profile_Swing_Radar" in body["agent"]["strategy_enabled"]
        assert "Profile_AI_Swing_Radar" in body["agent"]["strategy_enabled"]
    finally:
        reset_managers()
