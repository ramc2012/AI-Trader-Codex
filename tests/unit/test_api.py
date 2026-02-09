"""Tests for the FastAPI market data endpoints."""

from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.config.market_hours import IST


@pytest.fixture
def app():
    """Create a test FastAPI app."""
    return create_app()


@pytest.fixture
def client(app):
    """Create a test HTTP client."""
    return TestClient(app, raise_server_exceptions=False)


# =========================================================================
# Health Endpoint Tests
# =========================================================================


class TestHealthEndpoint:
    def test_health_ok(self, client: TestClient) -> None:
        with patch("src.api.routes.market_data.check_db_health", new_callable=AsyncMock) as mock_db:
            mock_db.return_value = True
            resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["database"] is True

    def test_health_degraded(self, client: TestClient) -> None:
        with patch("src.api.routes.market_data.check_db_health", new_callable=AsyncMock) as mock_db:
            mock_db.return_value = False
            resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["database"] is False


# =========================================================================
# Symbols Endpoint Tests
# =========================================================================


class TestSymbolsEndpoint:
    def test_list_symbols(self, client: TestClient) -> None:
        resp = client.get("/api/v1/symbols")
        assert resp.status_code == 200
        data = resp.json()
        assert "symbols" in data
        symbols = [s["symbol"] for s in data["symbols"]]
        assert "NSE:NIFTY50-INDEX" in symbols
        assert "NSE:NIFTYBANK-INDEX" in symbols

    def test_symbols_have_timeframes(self, client: TestClient) -> None:
        resp = client.get("/api/v1/symbols")
        data = resp.json()
        for sym in data["symbols"]:
            assert "timeframes" in sym
            assert len(sym["timeframes"]) > 0
            assert "D" in sym["timeframes"]


# =========================================================================
# OHLC Endpoint Tests
# =========================================================================


class TestOHLCEndpoint:
    def _mock_candle(self, ts: datetime):
        """Create a mock IndexOHLC-like object."""
        m = MagicMock()
        m.timestamp = ts
        m.open = Decimal("22150.50")
        m.high = Decimal("22200.75")
        m.low = Decimal("22100.25")
        m.close = Decimal("22180.00")
        m.volume = 150000
        return m

    def test_get_ohlc_success(self, client: TestClient) -> None:
        ts = datetime(2024, 2, 8, 9, 15, tzinfo=IST)
        mock_candles = [self._mock_candle(ts)]

        with patch(
            "src.api.routes.market_data.get_ohlc_candles", new_callable=AsyncMock
        ) as mock_fn:
            mock_fn.return_value = mock_candles
            resp = client.get("/api/v1/ohlc/NSE:NIFTY50-INDEX?timeframe=D&limit=10")

        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "NSE:NIFTY50-INDEX"
        assert data["timeframe"] == "D"
        assert data["count"] == 1
        assert len(data["candles"]) == 1
        assert data["candles"][0]["open"] == 22150.5

    def test_get_ohlc_invalid_timeframe(self, client: TestClient) -> None:
        resp = client.get("/api/v1/ohlc/NSE:NIFTY50-INDEX?timeframe=INVALID")
        assert resp.status_code == 400
        assert "Invalid timeframe" in resp.json()["detail"]

    def test_get_ohlc_empty(self, client: TestClient) -> None:
        with patch(
            "src.api.routes.market_data.get_ohlc_candles", new_callable=AsyncMock
        ) as mock_fn:
            mock_fn.return_value = []
            resp = client.get("/api/v1/ohlc/NSE:NIFTY50-INDEX?timeframe=D")

        assert resp.status_code == 200
        assert resp.json()["count"] == 0


# =========================================================================
# Ticks Endpoint Tests
# =========================================================================


class TestTicksEndpoint:
    def _mock_tick(self, ts: datetime):
        m = MagicMock()
        m.symbol = "NSE:NIFTY50-INDEX"
        m.timestamp = ts
        m.ltp = Decimal("22150.50")
        m.bid = Decimal("22150.00")
        m.ask = Decimal("22151.00")
        m.volume = 1000
        return m

    def test_get_ticks_success(self, client: TestClient) -> None:
        ts = datetime(2024, 2, 8, 10, 0, tzinfo=IST)
        with patch(
            "src.api.routes.market_data.get_recent_ticks", new_callable=AsyncMock
        ) as mock_fn:
            mock_fn.return_value = [self._mock_tick(ts)]
            resp = client.get("/api/v1/ticks/NSE:NIFTY50-INDEX?limit=10")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["ltp"] == 22150.5

    def test_get_ticks_empty(self, client: TestClient) -> None:
        with patch(
            "src.api.routes.market_data.get_recent_ticks", new_callable=AsyncMock
        ) as mock_fn:
            mock_fn.return_value = []
            resp = client.get("/api/v1/ticks/NSE:NIFTY50-INDEX")

        assert resp.status_code == 200
        assert resp.json() == []
