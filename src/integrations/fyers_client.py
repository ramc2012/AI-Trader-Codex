"""Fyers API v3 client wrapper with authentication, rate limiting, and retries.

Provides a clean async-friendly interface around the fyers-apiv3 SDK with:
- OAuth 2.0 authentication flow
- Token persistence (save/load to disk)
- Rate limiting (configurable requests/second)
- Retry logic with exponential backoff
- Structured logging for all API interactions
- Connection health checks
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from fyers_apiv3.fyersModel import FyersModel, SessionModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config.settings import get_settings
from src.utils.exceptions import (
    APIError,
    AuthenticationError,
    DataFetchError,
    RateLimitError,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Default token file location (relative to project root)
_DEFAULT_TOKEN_PATH = Path(".fyers_token.json")


class FyersClient:
    """Wrapper around Fyers API v3 with auth management and rate limiting.

    Args:
        app_id: Fyers app/client ID. Defaults to settings value.
        secret_key: Fyers secret key. Defaults to settings value.
        redirect_uri: OAuth redirect URI. Defaults to settings value.
        token_path: Path to persist the access token. Defaults to .fyers_token.json.
        rate_limit: Max API requests per second. Defaults to settings value.
        log_path: Directory for Fyers SDK logs. None disables SDK logging.
    """

    def __init__(
        self,
        app_id: str | None = None,
        secret_key: str | None = None,
        redirect_uri: str | None = None,
        token_path: Path | None = None,
        rate_limit: int | None = None,
        log_path: str | None = None,
    ) -> None:
        settings = get_settings()
        self._app_id = app_id or settings.fyers_app_id
        self._secret_key = secret_key or settings.fyers_secret_key
        self._redirect_uri = redirect_uri or settings.fyers_redirect_uri
        self._token_path = token_path or _DEFAULT_TOKEN_PATH
        self._rate_limit = rate_limit or settings.fyers_rate_limit_per_sec
        self._log_path = log_path

        self._access_token: str | None = None
        self._fyers: FyersModel | None = None

        # Rate limiting state
        self._last_request_time: float = 0.0
        self._min_interval: float = 1.0 / self._rate_limit

        # Try loading an existing token
        self._load_token()

    # =========================================================================
    # Authentication
    # =========================================================================

    def generate_auth_url(self) -> str:
        """Generate the OAuth authorization URL for user login.

        Returns:
            URL the user should visit to authorize the app.

        Raises:
            AuthenticationError: If app_id or secret_key is missing.
        """
        if not self._app_id or not self._secret_key:
            raise AuthenticationError(
                "Fyers app_id and secret_key must be configured. "
                "Set FYERS_APP_ID and FYERS_SECRET_KEY in .env"
            )

        session = SessionModel(
            client_id=self._app_id,
            redirect_uri=self._redirect_uri,
            response_type="code",
            secret_key=self._secret_key,
            grant_type="authorization_code",
        )
        url: str = session.generate_authcode()
        logger.info("auth_url_generated", redirect_uri=self._redirect_uri)
        return url

    def authenticate(self, auth_code: str) -> dict[str, Any]:
        """Exchange an authorization code for an access token.

        Args:
            auth_code: The authorization code from the OAuth redirect.

        Returns:
            Token response dict from Fyers.

        Raises:
            AuthenticationError: If token generation fails.
        """
        session = SessionModel(
            client_id=self._app_id,
            redirect_uri=self._redirect_uri,
            response_type="code",
            secret_key=self._secret_key,
            grant_type="authorization_code",
        )
        session.set_token(auth_code)
        response = session.generate_token()

        if response.get("s") != "ok" and "access_token" not in response:
            raise AuthenticationError(
                f"Token generation failed: {response.get('message', response)}"
            )

        self._access_token = response["access_token"]
        self._init_fyers_model()
        self._save_token()

        logger.info("authentication_successful")
        return response

    def set_access_token(self, token: str) -> None:
        """Directly set an access token (e.g., loaded externally).

        Args:
            token: A valid Fyers access token in format 'client_id:token'.
        """
        self._access_token = token
        self._init_fyers_model()
        logger.info("access_token_set_manually")

    @property
    def is_authenticated(self) -> bool:
        """Check if we have an access token and can reach Fyers."""
        if not self._access_token or not self._fyers:
            return False
        try:
            resp = self._fyers.get_profile()
            return resp.get("s") == "ok"
        except Exception:
            return False

    # =========================================================================
    # Token Persistence
    # =========================================================================

    def _save_token(self) -> None:
        """Save the current access token to disk."""
        if not self._access_token:
            return
        data = {
            "access_token": self._access_token,
            "saved_at": datetime.now().isoformat(),
        }
        self._token_path.write_text(json.dumps(data, indent=2))
        logger.debug("token_saved", path=str(self._token_path))

    def _load_token(self) -> None:
        """Load a previously saved token from disk."""
        if not self._token_path.exists():
            return
        try:
            data = json.loads(self._token_path.read_text())
            token = data.get("access_token")
            if token:
                self._access_token = token
                self._init_fyers_model()
                logger.info("token_loaded_from_disk", path=str(self._token_path))
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("token_load_failed", error=str(exc))

    # =========================================================================
    # FyersModel Management
    # =========================================================================

    def _init_fyers_model(self) -> None:
        """Initialize (or re-initialize) the underlying FyersModel."""
        kwargs: dict[str, Any] = {
            "is_async": False,
            "client_id": self._app_id,
            "token": self._access_token,
        }
        if self._log_path:
            kwargs["log_path"] = self._log_path
        self._fyers = FyersModel(**kwargs)

    def _ensure_authenticated(self) -> FyersModel:
        """Return the FyersModel or raise if not authenticated."""
        if not self._fyers or not self._access_token:
            raise AuthenticationError(
                "Not authenticated. Call generate_auth_url() and authenticate() first."
            )
        return self._fyers

    # =========================================================================
    # Rate Limiting
    # =========================================================================

    def _wait_for_rate_limit(self) -> None:
        """Block until we can make another request within the rate limit."""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.monotonic()

    async def _async_wait_for_rate_limit(self) -> None:
        """Async version of rate limit wait."""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)
        self._last_request_time = time.monotonic()

    # =========================================================================
    # API Call Wrapper
    # =========================================================================

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(RateLimitError),
        reraise=True,
    )
    def _call(self, method_name: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a Fyers API method with rate limiting and retries.

        Args:
            method_name: Name of the FyersModel method to call.
            data: Optional data dict to pass to the method.

        Returns:
            API response dict.

        Raises:
            AuthenticationError: If not authenticated or token expired.
            RateLimitError: If rate-limited after retries.
            APIError: For other API errors.
        """
        fyers = self._ensure_authenticated()
        self._wait_for_rate_limit()

        method = getattr(fyers, method_name, None)
        if method is None:
            raise APIError(f"Unknown Fyers API method: {method_name}")

        logger.debug("api_call", method=method_name, data=data)

        try:
            response: dict[str, Any] = method(data) if data else method()
        except Exception as exc:
            logger.error("api_call_exception", method=method_name, error=str(exc))
            raise APIError(f"API call {method_name} failed: {exc}") from exc

        status = response.get("s", "")
        code = response.get("code", 0)

        if status == "error":
            msg = response.get("message", "Unknown error")
            logger.warning("api_error", method=method_name, code=code, message=msg)

            if code == -99:
                raise RateLimitError(f"Rate limited or token expired: {msg}", status_code=code)
            if "token" in msg.lower() or "auth" in msg.lower():
                raise AuthenticationError(f"Authentication error: {msg}")
            raise APIError(f"API error ({code}): {msg}", status_code=code)

        logger.debug("api_response", method=method_name, status=status)
        return response

    # =========================================================================
    # Account & Profile
    # =========================================================================

    def get_profile(self) -> dict[str, Any]:
        """Fetch the authenticated user's profile.

        Returns:
            Profile data dict.
        """
        return self._call("get_profile")

    def get_funds(self) -> dict[str, Any]:
        """Fetch available funds and margin information.

        Returns:
            Funds data dict.
        """
        return self._call("funds")

    # =========================================================================
    # Market Data
    # =========================================================================

    def get_quotes(self, symbols: list[str]) -> dict[str, Any]:
        """Fetch real-time quotes for the given symbols.

        Args:
            symbols: List of symbol strings (max 50).

        Returns:
            Quotes response dict.

        Raises:
            ValueError: If more than 50 symbols requested.
        """
        if len(symbols) > 50:
            raise ValueError("Fyers quotes API supports max 50 symbols per request")
        data = {"symbols": ",".join(symbols)}
        return self._call("quotes", data)

    def get_market_depth(self, symbol: str) -> dict[str, Any]:
        """Fetch market depth (order book) for a symbol.

        Args:
            symbol: Symbol string (e.g., 'NSE:NIFTY50-INDEX').

        Returns:
            Depth response dict.
        """
        return self._call("depth", {"symbol": symbol, "ohlcv_flag": 1})

    def get_history(
        self,
        symbol: str,
        resolution: str,
        range_from: str,
        range_to: str,
        cont_flag: int = 0,
        date_format: int = 1,
    ) -> dict[str, Any]:
        """Fetch historical OHLCV candle data.

        Args:
            symbol: Symbol string (e.g., 'NSE:NIFTY50-INDEX').
            resolution: Candle timeframe ('1', '5', '15', '60', 'D', 'W', 'M').
            range_from: Start date 'YYYY-MM-DD' (if date_format=1).
            range_to: End date 'YYYY-MM-DD' (if date_format=1).
            cont_flag: 0 for normal, 1 for continuous futures data.
            date_format: 0 for epoch, 1 for 'YYYY-MM-DD'.

        Returns:
            Dict with 'candles' key containing [[ts, O, H, L, C, V], ...].

        Raises:
            DataFetchError: If the API returns an error or no data.
        """
        data = {
            "symbol": symbol,
            "resolution": resolution,
            "date_format": str(date_format),
            "range_from": range_from,
            "range_to": range_to,
            "cont_flag": str(cont_flag),
        }

        try:
            response = self._call("history", data)
        except APIError as exc:
            raise DataFetchError(
                f"Failed to fetch history for {symbol} ({resolution}): {exc}"
            ) from exc

        if "candles" not in response or not response["candles"]:
            raise DataFetchError(
                f"No candle data returned for {symbol} "
                f"({resolution}) from {range_from} to {range_to}"
            )

        return response

    def get_market_status(self) -> dict[str, Any]:
        """Fetch current market status (open/closed).

        Returns:
            Market status dict.
        """
        return self._call("market_status")

    def get_option_chain(
        self, symbol: str, strike_count: int = 5, timestamp: int | None = None
    ) -> dict[str, Any]:
        """Fetch option chain for an underlying.

        Args:
            symbol: Underlying symbol (e.g., 'NSE:NIFTY50-INDEX').
            strike_count: Number of strikes above and below ATM.
            timestamp: Expiry timestamp (epoch). None for nearest expiry.

        Returns:
            Option chain response dict.
        """
        data: dict[str, Any] = {
            "symbol": symbol,
            "strikecount": strike_count,
        }
        if timestamp is not None:
            data["timestamp"] = timestamp
        return self._call("optionchain", data)

    # =========================================================================
    # Orders & Trading (for future use)
    # =========================================================================

    def get_orders(self) -> dict[str, Any]:
        """Fetch the order book."""
        return self._call("orderbook")

    def get_positions(self) -> dict[str, Any]:
        """Fetch open positions."""
        return self._call("positions")

    def get_tradebook(self) -> dict[str, Any]:
        """Fetch today's executed trades."""
        return self._call("tradebook")

    def get_holdings(self) -> dict[str, Any]:
        """Fetch portfolio holdings."""
        return self._call("holdings")

    def place_order(self, order_data: dict[str, Any]) -> dict[str, Any]:
        """Place a new order.

        Args:
            order_data: Order parameters dict with keys:
                symbol, qty, type, side, productType, validity,
                limitPrice, stopPrice, offlineOrder.

        Returns:
            Order response with orderId.
        """
        return self._call("place_order", order_data)

    def modify_order(self, order_data: dict[str, Any]) -> dict[str, Any]:
        """Modify an existing order.

        Args:
            order_data: Dict with 'id' and fields to modify.

        Returns:
            Modification response.
        """
        return self._call("modify_order", order_data)

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        """Cancel an existing order.

        Args:
            order_id: The Fyers order ID.

        Returns:
            Cancellation response.
        """
        return self._call("cancel_order", {"id": order_id})

    # =========================================================================
    # Cleanup
    # =========================================================================

    def close(self) -> None:
        """Clean up resources. Call when done with the client."""
        self._fyers = None
        self._access_token = None
        logger.info("fyers_client_closed")
