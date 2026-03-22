"""Tests for FnO radar API endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

import src.api.routes.fno_radar as fno_radar_module
from src.api.dependencies import get_db, reset_managers
from src.api.main import create_app


class _StubScorer:
    def research_status(self) -> dict[str, object]:
        return {
            "ready": True,
            "requested_symbols": 187,
            "downloaded_symbols": 183,
            "dataset_rows": 443643,
            "dataset_symbols": 182,
            "start_date": "2016-01-01",
            "end_date": "2026-03-19",
            "failed_symbols": ["GMRINFRA"],
            "selected_short": {"multiplier": 1.75, "positive_rate": 0.1128},
            "selected_long": {"multiplier": 3.5, "positive_rate": 0.2438},
        }

    def list_latest_candidates(self, **_: object) -> list[dict[str, object]]:
        return [
            {
                "symbol": "RELIANCE",
                "spot_symbol": "NSE:RELIANCE-EQ",
                "sector": "Oil & Gas",
                "price": 2480.0,
                "date": "2026-03-19",
                "source": "research_snapshot",
                "direction": "up",
                "horizon": "10_15D",
                "score": 81.0,
                "strength": "strong",
                "direction_probability": 0.57,
                "neutral_probability": 0.25,
                "direction_edge": 0.32,
                "allow_overnight": True,
                "planned_holding_days": 15,
                "expected_move_pct": 8.2,
                "stop_loss": 2390.0,
                "target": 2685.0,
                "atr_pct": 2.1,
                "market_regime": "bull",
                "baseline_hit_rate": 24.4,
                "matched_conditions": [],
            }
        ]


def test_fno_radar_overview_endpoint(monkeypatch) -> None:
    reset_managers()
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    monkeypatch.setattr(fno_radar_module, "FnOSwingLiveScorer", lambda: _StubScorer())

    class _FakeResult:
        def one(self) -> tuple[int, None]:
            return (54, None)

    class _FakeSession:
        async def execute(self, _stmt):  # noqa: ANN001
            return _FakeResult()

    async def _fake_db():
        yield _FakeSession()

    app.dependency_overrides[get_db] = _fake_db

    try:
        response = client.get("/api/v1/fno-radar/overview?limit=5&min_score=55")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["research"]["ready"] is True
        assert body["research"]["downloaded_symbols"] == 183
        assert body["local_market_data"]["daily_symbols"] == 54
        assert body["agent"]["expected_fno_symbols"] >= 180
        assert body["candidates"][0]["symbol"] == "RELIANCE"
    finally:
        app.dependency_overrides.clear()
        reset_managers()
