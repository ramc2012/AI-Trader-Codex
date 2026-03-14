"""Tests for FyersClient wrapper."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from fyers_apiv3.fyersModel import FyersModel

from src.integrations.fyers_client import FyersClient
from src.utils.exceptions import (
    APIError,
    AuthenticationError,
    DataFetchError,
    RateLimitError,
)


@pytest.fixture
def token_path(tmp_path: Path) -> Path:
    """Provide a temp path for token storage."""
    return tmp_path / ".fyers_token.json"


@pytest.fixture
def client(token_path: Path) -> FyersClient:
    """Create a FyersClient with test credentials (no real connection)."""
    with patch("src.integrations.fyers_client.get_settings") as mock_settings:
        settings = MagicMock()
        settings.fyers_app_id = "TEST_APP_ID"
        settings.fyers_secret_key = "TEST_SECRET"
        settings.fyers_redirect_uri = "http://localhost:8000/callback"
        settings.fyers_rate_limit_per_sec = 10  # fast for tests
        mock_settings.return_value = settings

        return FyersClient(token_path=token_path)


@pytest.fixture
def authenticated_client(client: FyersClient) -> FyersClient:
    """Return a client with a mocked FyersModel already set."""
    client._access_token = "TEST_APP_ID:fake_token_123"
    client._fyers = MagicMock(spec=FyersModel)
    return client


# =========================================================================
# Authentication Tests
# =========================================================================


class TestAuthentication:
    def test_generate_auth_url(self, client: FyersClient) -> None:
        with patch("src.integrations.fyers_client.SessionModel") as MockSession:
            instance = MockSession.return_value
            instance.generate_authcode.return_value = "https://api-t1.fyers.in/auth?code=test"

            url = client.generate_auth_url()

            assert "fyers" in url
            MockSession.assert_called_once()
            instance.generate_authcode.assert_called_once()

    def test_generate_auth_url_missing_credentials(self, token_path: Path) -> None:
        with patch("src.integrations.fyers_client.get_settings") as mock_settings:
            settings = MagicMock()
            settings.fyers_app_id = ""
            settings.fyers_secret_key = ""
            settings.fyers_redirect_uri = "http://localhost:8000/callback"
            settings.fyers_rate_limit_per_sec = 10
            mock_settings.return_value = settings

            c = FyersClient(token_path=token_path)
            with pytest.raises(AuthenticationError, match="must be configured"):
                c.generate_auth_url()

    def test_authenticate_success(self, client: FyersClient, token_path: Path) -> None:
        with patch("src.integrations.fyers_client.SessionModel") as MockSession:
            instance = MockSession.return_value
            instance.generate_token.return_value = {
                "s": "ok",
                "access_token": "TEST_APP_ID:valid_token_abc",
            }

            result = client.authenticate("auth_code_xyz")

            assert result["access_token"] == "TEST_APP_ID:valid_token_abc"
            assert client._access_token == "TEST_APP_ID:valid_token_abc"
            assert token_path.exists()

    def test_authenticate_failure(self, client: FyersClient) -> None:
        with patch("src.integrations.fyers_client.SessionModel") as MockSession:
            instance = MockSession.return_value
            instance.generate_token.return_value = {
                "s": "error",
                "message": "Invalid auth code",
            }

            with pytest.raises(AuthenticationError, match="Token generation failed"):
                client.authenticate("bad_code")

    def test_ensure_authenticated_forces_refresh_when_session_is_invalid(
        self, client: FyersClient
    ) -> None:
        with (
            patch.object(client, "try_auto_refresh_with_saved_pin", side_effect=[False, True]) as refresh,
            patch.object(client, "_is_refresh_token_valid", return_value=True),
            patch.object(FyersClient, "is_authenticated", new_callable=PropertyMock, return_value=False),
        ):
            refreshed = client.ensure_authenticated_with_saved_pin()

        assert refreshed is True
        assert refresh.call_args_list[0].args == (False,)
        assert refresh.call_args_list[1].args == (True,)

    def test_ensure_authenticated_skips_forced_refresh_without_refresh_token(
        self, client: FyersClient
    ) -> None:
        with (
            patch.object(client, "try_auto_refresh_with_saved_pin", return_value=False) as refresh,
            patch.object(client, "_is_refresh_token_valid", return_value=False),
            patch.object(FyersClient, "is_authenticated", new_callable=PropertyMock, return_value=False),
        ):
            refreshed = client.ensure_authenticated_with_saved_pin()

        assert refreshed is False
        refresh.assert_called_once_with(False)

    def test_set_access_token(self, client: FyersClient) -> None:
        client.set_access_token("TEST_APP_ID:manual_token")
        assert client._access_token == "TEST_APP_ID:manual_token"
        assert client._fyers is not None

    def test_is_authenticated_true(self, authenticated_client: FyersClient) -> None:
        authenticated_client._fyers.get_profile.return_value = {"s": "ok"}
        assert authenticated_client.is_authenticated is True

    def test_is_authenticated_false_no_token(self, client: FyersClient) -> None:
        assert client.is_authenticated is False

    def test_is_authenticated_false_api_error(
        self, authenticated_client: FyersClient
    ) -> None:
        authenticated_client._fyers.get_profile.side_effect = Exception("network error")
        assert authenticated_client.is_authenticated is False


# =========================================================================
# Token Persistence Tests
# =========================================================================


class TestTokenPersistence:
    def test_save_and_load_token(self, client: FyersClient, token_path: Path) -> None:
        client._access_token = "TEST_APP_ID:persisted_token"
        client._save_token()

        assert token_path.exists()
        data = json.loads(token_path.read_text())
        assert data["access_token"] == "TEST_APP_ID:persisted_token"

        # Create a new client that should load the saved token
        with patch("src.integrations.fyers_client.get_settings") as mock_settings:
            settings = MagicMock()
            settings.fyers_app_id = "TEST_APP_ID"
            settings.fyers_secret_key = "TEST_SECRET"
            settings.fyers_redirect_uri = "http://localhost:8000/callback"
            settings.fyers_rate_limit_per_sec = 10
            mock_settings.return_value = settings

            new_client = FyersClient(token_path=token_path)
            assert new_client._access_token == "TEST_APP_ID:persisted_token"

    def test_load_token_missing_file(self, client: FyersClient) -> None:
        # Should not raise — just a no-op
        client._load_token()
        assert client._access_token is None

    def test_load_token_corrupt_file(
        self, client: FyersClient, token_path: Path
    ) -> None:
        token_path.write_text("not valid json{{{")
        client._load_token()
        assert client._access_token is None


# =========================================================================
# Rate Limiting Tests
# =========================================================================


class TestRateLimiting:
    def test_rate_limit_throttles(self, authenticated_client: FyersClient) -> None:
        authenticated_client._rate_limit = 2
        authenticated_client._min_interval = 0.5  # 2 req/sec

        authenticated_client._fyers.get_profile.return_value = {"s": "ok"}

        start = time.monotonic()
        authenticated_client.get_profile()
        authenticated_client.get_profile()
        elapsed = time.monotonic() - start

        # Second call should have waited ~0.5s
        assert elapsed >= 0.4


# =========================================================================
# API Call Tests
# =========================================================================


class TestAPICalls:
    def test_get_profile(self, authenticated_client: FyersClient) -> None:
        authenticated_client._fyers.get_profile.return_value = {
            "s": "ok",
            "data": {"name": "Test User", "email": "test@example.com"},
        }
        result = authenticated_client.get_profile()
        assert result["s"] == "ok"
        assert result["data"]["name"] == "Test User"

    def test_get_funds(self, authenticated_client: FyersClient) -> None:
        authenticated_client._fyers.funds.return_value = {
            "s": "ok",
            "fund_limit": [{"title": "Total Balance", "equityAmount": 100000}],
        }
        result = authenticated_client.get_funds()
        assert result["s"] == "ok"

    def test_get_quotes(self, authenticated_client: FyersClient) -> None:
        authenticated_client._fyers.quotes.return_value = {
            "s": "ok",
            "d": [{"v": {"lp": 22150.5, "symbol": "NSE:NIFTY50-INDEX"}}],
        }
        result = authenticated_client.get_quotes(["NSE:NIFTY50-INDEX"])
        assert result["s"] == "ok"

    def test_get_quotes_too_many_symbols(
        self, authenticated_client: FyersClient
    ) -> None:
        symbols = [f"NSE:SYM{i}" for i in range(51)]
        with pytest.raises(ValueError, match="max 50"):
            authenticated_client.get_quotes(symbols)

    def test_get_history_success(self, authenticated_client: FyersClient) -> None:
        authenticated_client._fyers.history.return_value = {
            "s": "ok",
            "candles": [
                [1707369000, 22150.5, 22200.75, 22100.25, 22180.0, 150000],
                [1707372600, 22180.0, 22250.0, 22170.5, 22230.25, 120000],
            ],
        }
        result = authenticated_client.get_history(
            symbol="NSE:NIFTY50-INDEX",
            resolution="D",
            range_from="2024-01-01",
            range_to="2024-02-08",
        )
        assert len(result["candles"]) == 2

    def test_get_history_no_data(self, authenticated_client: FyersClient) -> None:
        authenticated_client._fyers.history.return_value = {
            "s": "ok",
            "candles": [],
        }
        with pytest.raises(DataFetchError, match="No candle data"):
            authenticated_client.get_history(
                symbol="NSE:NIFTY50-INDEX",
                resolution="D",
                range_from="2024-01-01",
                range_to="2024-02-08",
            )

    def test_get_history_api_error(self, authenticated_client: FyersClient) -> None:
        authenticated_client._fyers.history.return_value = {
            "s": "error",
            "code": -300,
            "message": "Invalid symbol",
        }
        with pytest.raises(DataFetchError, match="Failed to fetch history"):
            authenticated_client.get_history(
                symbol="INVALID:SYMBOL",
                resolution="D",
                range_from="2024-01-01",
                range_to="2024-02-08",
            )

    def test_get_market_depth(self, authenticated_client: FyersClient) -> None:
        authenticated_client._fyers.depth.return_value = {
            "s": "ok",
            "d": {"NSE:NIFTY50-INDEX": {"bids": [], "ask": []}},
        }
        result = authenticated_client.get_market_depth("NSE:NIFTY50-INDEX")
        assert result["s"] == "ok"

    def test_get_option_chain(self, authenticated_client: FyersClient) -> None:
        authenticated_client._fyers.optionchain.return_value = {
            "s": "ok",
            "data": {"expiryData": []},
        }
        result = authenticated_client.get_option_chain("NSE:NIFTY50-INDEX", strike_count=10)
        assert result["s"] == "ok"


# =========================================================================
# Error Handling Tests
# =========================================================================


class TestErrorHandling:
    def test_api_error_raises(self, authenticated_client: FyersClient) -> None:
        authenticated_client._fyers.get_profile.return_value = {
            "s": "error",
            "code": -300,
            "message": "Bad request",
        }
        with pytest.raises(APIError, match="Bad request"):
            authenticated_client.get_profile()

    def test_rate_limit_error_retries(
        self, authenticated_client: FyersClient
    ) -> None:
        # First two calls: rate limited, third: success
        authenticated_client._fyers.get_profile.side_effect = [
            {"s": "error", "code": -99, "message": "Rate limited"},
            {"s": "error", "code": -99, "message": "Rate limited"},
            {"s": "ok", "data": {"name": "User"}},
        ]
        result = authenticated_client.get_profile()
        assert result["s"] == "ok"
        assert authenticated_client._fyers.get_profile.call_count == 3

    def test_rate_limit_error_exhausts_retries(
        self, authenticated_client: FyersClient
    ) -> None:
        authenticated_client._fyers.get_profile.return_value = {
            "s": "error",
            "code": -99,
            "message": "Rate limited",
        }
        with pytest.raises(RateLimitError):
            authenticated_client.get_profile()

    def test_auth_error_in_response(
        self, authenticated_client: FyersClient
    ) -> None:
        authenticated_client._fyers.get_profile.return_value = {
            "s": "error",
            "code": -99,
            "message": "Invalid token",
        }
        # -99 triggers RateLimitError (which covers token expiry too)
        with pytest.raises(RateLimitError):
            authenticated_client.get_profile()

    def test_not_authenticated_raises(self, client: FyersClient) -> None:
        with pytest.raises(AuthenticationError, match="Not authenticated"):
            client.get_profile()

    def test_unknown_method_raises(self, authenticated_client: FyersClient) -> None:
        with pytest.raises(APIError, match="Unknown Fyers API method"):
            authenticated_client._call("nonexistent_method")

    def test_exception_during_api_call(
        self, authenticated_client: FyersClient
    ) -> None:
        authenticated_client._fyers.get_profile.side_effect = ConnectionError(
            "Network error"
        )
        with pytest.raises(APIError, match="failed"):
            authenticated_client.get_profile()


# =========================================================================
# Order & Trading Tests
# =========================================================================


class TestTrading:
    def test_place_order(self, authenticated_client: FyersClient) -> None:
        authenticated_client._fyers.place_order.return_value = {
            "s": "ok",
            "id": "ORDER_123",
        }
        result = authenticated_client.place_order(
            {
                "symbol": "NSE:NIFTY2440622000CE",
                "qty": 50,
                "type": 2,
                "side": 1,
                "productType": "INTRADAY",
                "validity": "DAY",
                "limitPrice": 0,
                "stopPrice": 0,
            }
        )
        assert result["s"] == "ok"

    def test_cancel_order(self, authenticated_client: FyersClient) -> None:
        authenticated_client._fyers.cancel_order.return_value = {
            "s": "ok",
            "id": "ORDER_123",
        }
        result = authenticated_client.cancel_order("ORDER_123")
        assert result["s"] == "ok"

    def test_get_orders(self, authenticated_client: FyersClient) -> None:
        authenticated_client._fyers.orderbook.return_value = {
            "s": "ok",
            "orderBook": [],
        }
        result = authenticated_client.get_orders()
        assert result["s"] == "ok"

    def test_get_positions(self, authenticated_client: FyersClient) -> None:
        authenticated_client._fyers.positions.return_value = {
            "s": "ok",
            "netPositions": [],
        }
        result = authenticated_client.get_positions()
        assert result["s"] == "ok"


# =========================================================================
# Cleanup Tests
# =========================================================================


class TestCleanup:
    def test_close(self, authenticated_client: FyersClient) -> None:
        authenticated_client.close()
        assert authenticated_client._fyers is None
        assert authenticated_client._access_token is None
