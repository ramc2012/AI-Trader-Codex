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
import os
import stat
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from dateutil import parser
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

# Default token file location — uses DATA_DIR so it persists across Docker restarts.
# Falls back to project root when running locally without DATA_DIR set.
def _default_token_path() -> Path:
    from src.config.settings import get_settings
    return get_settings().token_file_path
_ACCESS_TOKEN_LIFETIME = timedelta(hours=24)
_REFRESH_TOKEN_LIFETIME = timedelta(days=15)
_ACCESS_TOKEN_REFRESH_BUFFER = timedelta(minutes=10)
_REFRESH_TOKEN_EXPIRY_BUFFER = timedelta(minutes=15)
_AUTO_REFRESH_COOLDOWN = timedelta(seconds=30)


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
        self._token_path = token_path or _default_token_path()
        self._rate_limit = rate_limit or settings.fyers_rate_limit_per_sec
        self._log_path = log_path

        self._access_token: str | None = None
        self._fyers: FyersModel | None = None
        self._refresh_token: str | None = None
        self._access_token_expires_at: str | None = None
        self._refresh_token_expires_at: str | None = None
        self._last_auto_refresh_attempt: datetime | None = None

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

        now = datetime.now()
        self._access_token = response["access_token"]
        self._access_token_expires_at = (now + _ACCESS_TOKEN_LIFETIME).isoformat()

        # Store refresh token if provided by Fyers (BEFORE saving)
        if "refresh_token" in response:
            self._refresh_token = response["refresh_token"]
            self._refresh_token_expires_at = (now + _REFRESH_TOKEN_LIFETIME).isoformat()
            logger.info("refresh_token_captured")

        self._init_fyers_model()
        self._save_token()  # Save token AFTER capturing refresh token

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

    @property
    def access_token(self) -> str | None:
        """Current access token (read-only)."""
        return self._access_token

    # =========================================================================
    # Token Persistence
    # =========================================================================

    def _save_token(self) -> None:
        """Save the current access token and refresh token to disk."""
        if not self._access_token:
            return

        now = datetime.now()
        data = {
            "access_token": self._access_token,
            "saved_at": now.isoformat(),
        }

        # Add refresh token if available
        if self._refresh_token:
            data["refresh_token"] = self._refresh_token

        if self._access_token_expires_at:
            data["access_token_expires_at"] = self._access_token_expires_at
        else:
            data["access_token_expires_at"] = (now + _ACCESS_TOKEN_LIFETIME).isoformat()
            self._access_token_expires_at = data["access_token_expires_at"]

        if self._refresh_token and self._refresh_token_expires_at:
            data["refresh_token_expires_at"] = self._refresh_token_expires_at

        self._token_path.write_text(json.dumps(data, indent=2))
        # Restrict token file to owner read/write only (security hardening)
        os.chmod(self._token_path, stat.S_IRUSR | stat.S_IWUSR)
        logger.debug("token_saved", path=str(self._token_path), has_refresh=bool(self._refresh_token))

    def _load_token(self) -> None:
        """Load a previously saved token from disk."""
        if not self._token_path.exists():
            return
        try:
            data = json.loads(self._token_path.read_text())
            token = data.get("access_token")
            if token:
                self._access_token = token
                self._refresh_token = data.get("refresh_token")
                self._access_token_expires_at = data.get("access_token_expires_at")
                self._refresh_token_expires_at = data.get("refresh_token_expires_at")

                saved_at_str = data.get("saved_at")
                if saved_at_str:
                    try:
                        saved_at = parser.isoparse(saved_at_str)
                        if not self._access_token_expires_at:
                            self._access_token_expires_at = (saved_at + _ACCESS_TOKEN_LIFETIME).isoformat()
                        if self._refresh_token and not self._refresh_token_expires_at:
                            self._refresh_token_expires_at = (saved_at + _REFRESH_TOKEN_LIFETIME).isoformat()
                    except Exception:
                        logger.debug("token_saved_at_parse_failed", path=str(self._token_path))

                self._init_fyers_model()
                logger.info("token_loaded_from_disk",
                           path=str(self._token_path),
                           has_refresh=bool(self._refresh_token))
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
    # Token Refresh Support
    # =========================================================================

    def _is_access_token_expired(self) -> bool:
        """Check if access token is expired or will expire soon.

        Returns:
            True if token is expired or will expire within refresh buffer
        """
        if not self._access_token:
            return True

        if not self._access_token_expires_at:
            # Missing metadata on older installs: treat as valid and rely on auth check.
            # This avoids aggressive refresh attempts during credential entry.
            logger.debug("access_token_expiry_missing_assuming_valid")
            return False

        try:
            expiry = parser.isoparse(self._access_token_expires_at)
            return datetime.now() >= expiry - _ACCESS_TOKEN_REFRESH_BUFFER
        except Exception:
            return True

    def _is_refresh_token_valid(self) -> bool:
        """Check if refresh token is still valid.

        Returns:
            True if refresh token exists and hasn't expired
        """
        if not self._refresh_token:
            return False

        if not self._refresh_token_expires_at:
            # Legacy token files may not contain refresh-token expiry.
            # Allow refresh attempt; server-side validation remains authoritative.
            return True

        try:
            expiry = parser.isoparse(self._refresh_token_expires_at)
            return datetime.now() < expiry - _REFRESH_TOKEN_EXPIRY_BUFFER
        except Exception:
            return True

    def _generate_app_id_hash(self) -> str:
        """Generate SHA-256 hash of app_id + secret_key for refresh token API.

        Returns:
            Hexadecimal SHA-256 hash
        """
        from src.utils.crypto import generate_app_id_hash
        return generate_app_id_hash(self._app_id, self._secret_key)

    def refresh_access_token(self, pin: str) -> dict[str, Any]:
        """Use refresh token to get a new access token.

        This calls the Fyers refresh token API to exchange a refresh token
        for a new access token, avoiding the need for full OAuth flow.

        Args:
            pin: User's FYERS PIN

        Returns:
            Token response dict from Fyers with new access_token

        Raises:
            AuthenticationError: If refresh token is missing, invalid, or refresh fails
        """
        if not hasattr(self, '_refresh_token') or not self._refresh_token:
            raise AuthenticationError(
                "No refresh token available. Please authenticate via OAuth."
            )

        if not self._is_refresh_token_valid():
            raise AuthenticationError(
                "Refresh token has expired. Please re-authenticate via OAuth."
            )

        try:
            # Prepare request
            url = "https://api-t1.fyers.in/api/v3/validate-refresh-token"
            headers = {"Content-Type": "application/json"}
            payload = {
                "grant_type": "refresh_token",
                "appIdHash": self._generate_app_id_hash(),
                "refresh_token": self._refresh_token,
                "pin": str(pin),
            }

            logger.info("refresh_token_request", url=url)

            # Make request
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()

            # Check response
            if data.get("s") != "ok" or "access_token" not in data:
                raise AuthenticationError(
                    f"Token refresh failed: {data.get('message', data)}"
                )

            # Update tokens
            now = datetime.now()
            self._access_token = data["access_token"]
            self._access_token_expires_at = (now + _ACCESS_TOKEN_LIFETIME).isoformat()

            # Some APIs return a new refresh token, others reuse the same one
            if "refresh_token" in data:
                self._refresh_token = data["refresh_token"]
                self._refresh_token_expires_at = (now + _REFRESH_TOKEN_LIFETIME).isoformat()

            # Reinitialize Fyers model with new token
            self._init_fyers_model()

            # Save updated tokens
            self._save_token()

            logger.info("token_refresh_successful")
            return data

        except AuthenticationError:
            raise
        except requests.exceptions.RequestException as exc:
            logger.error("token_refresh_network_error", error=str(exc))
            raise AuthenticationError(f"Network error during token refresh: {str(exc)}")
        except Exception as exc:
            logger.error("token_refresh_failed", error=str(exc))
            raise AuthenticationError(f"Token refresh failed: {str(exc)}")

    def try_auto_refresh_with_saved_pin(self, force: bool = False) -> bool:
        """Best-effort refresh using stored PIN when access token is expiring/expired.

        Args:
            force: If True, bypasses expiry check but still honors cooldown.

        Returns:
            True when a refresh happened successfully; otherwise False.
        """
        now = datetime.now()

        if (
            self._last_auto_refresh_attempt is not None
            and now - self._last_auto_refresh_attempt < _AUTO_REFRESH_COOLDOWN
        ):
            return False

        if not force and not self._is_access_token_expired():
            return False

        if not self._is_refresh_token_valid():
            return False

        try:
            from src.utils.pin_storage import has_saved_pin, load_pin
        except Exception as exc:
            logger.warning("pin_storage_unavailable", error=str(exc))
            return False

        if not has_saved_pin():
            return False

        pin = load_pin()
        if not pin:
            logger.warning("saved_pin_missing_or_unreadable")
            return False

        self._last_auto_refresh_attempt = now
        try:
            self.refresh_access_token(pin)
            logger.info("token_auto_refreshed_with_saved_pin")
            return True
        except AuthenticationError as exc:
            logger.warning("token_auto_refresh_failed", error=str(exc))
            return False

    def auto_refresh_if_needed(self, pin: str | None = None) -> bool:
        """Automatically refresh token if expired or expiring soon.

        Args:
            pin: Optional PIN for refresh. Required if token needs refresh.

        Returns:
            True if token was refreshed, False if still valid

        Raises:
            AuthenticationError: If refresh is needed but PIN not provided or refresh fails
        """
        if not self._is_access_token_expired():
            logger.debug("token_still_valid_no_refresh_needed")
            return False

        if not self._is_refresh_token_valid():
            raise AuthenticationError(
                "Both access and refresh tokens expired. Full re-authentication required."
            )

        if not pin:
            raise AuthenticationError(
                "Access token expired. PIN required for automatic refresh."
            )

        logger.info("auto_refreshing_expired_token")
        self.refresh_access_token(pin)
        return True

    def get_token_status(self) -> dict[str, Any]:
        """Get detailed status of current tokens.

        Returns:
            Dict with token status information:
            {
                "access_token_valid": bool,
                "access_token_expires_in_hours": float or None,
                "refresh_token_valid": bool,
                "refresh_token_expires_in_days": float or None,
                "needs_full_reauth": bool
            }
        """
        status = {
            "access_token_valid": bool(self._access_token and not self._is_access_token_expired()),
            "access_token_expires_in_hours": None,
            "refresh_token_valid": self._is_refresh_token_valid(),
            "refresh_token_expires_in_days": None,
            "needs_full_reauth": False,
        }

        # Calculate time until access token expiry
        if hasattr(self, '_access_token_expires_at') and self._access_token_expires_at:
            try:
                expiry = parser.isoparse(self._access_token_expires_at)
                delta = expiry - datetime.now()
                status["access_token_expires_in_hours"] = delta.total_seconds() / 3600
            except Exception:
                pass

        # Calculate time until refresh token expiry
        if hasattr(self, '_refresh_token_expires_at') and self._refresh_token_expires_at:
            try:
                expiry = parser.isoparse(self._refresh_token_expires_at)
                delta = expiry - datetime.now()
                status["refresh_token_expires_in_days"] = delta.total_seconds() / 86400
            except Exception:
                pass

        # Determine if full re-auth is needed
        status["needs_full_reauth"] = not status["refresh_token_valid"]

        return status

    # =========================================================================
    # Cleanup
    # =========================================================================

    def close(self) -> None:
        """Clean up resources. Call when done with the client."""
        self._fyers = None
        self._access_token = None
        logger.info("fyers_client_closed")
