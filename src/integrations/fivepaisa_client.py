"""5paisa API client implementing the BrokerBase interface.

Provides authentication, market data, and order management via
the 5paisa API. Designed as a drop-in alternative broker client.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config.settings import get_settings
from src.integrations.broker_base import (
    BrokerBase,
    BrokerName,
    BrokerOrderParams,
    BrokerOrderResponse,
    BrokerQuote,
)
from src.utils.exceptions import (
    APIError,
    AuthenticationError,
    DataFetchError,
    RateLimitError,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

_FIVEPAISA_API_BASE = "https://Openapi.5paisa.com/VendorsAPI/Service1.svc"
_FIVEPAISA_TRADE_BASE = "https://Openapi.5paisa.com"


class FivePaisaClient(BrokerBase):
    """5paisa API client with TOTP-based auth, rate limiting, and retries.

    Args:
        app_name: 5paisa app name. Defaults to settings.
        app_source: 5paisa app source. Defaults to settings.
        user_id: 5paisa user ID. Defaults to settings.
        password: 5paisa password. Defaults to settings.
        user_key: 5paisa user key. Defaults to settings.
        encryption_key: 5paisa encryption key. Defaults to settings.
        token_path: Path to persist session cookies.
        rate_limit: Max API requests per second.
    """

    name = BrokerName.FIVEPAISA

    def __init__(
        self,
        app_name: str | None = None,
        app_source: str | None = None,
        user_id: str | None = None,
        password: str | None = None,
        user_key: str | None = None,
        encryption_key: str | None = None,
        token_path: Path | None = None,
        rate_limit: int = 5,
    ) -> None:
        settings = get_settings()
        self._app_name = app_name or getattr(settings, "fivepaisa_app_name", "")
        self._app_source = app_source or getattr(settings, "fivepaisa_app_source", "")
        self._user_id = user_id or getattr(settings, "fivepaisa_user_id", "")
        self._password = password or getattr(settings, "fivepaisa_password", "")
        self._user_key = user_key or getattr(settings, "fivepaisa_user_key", "")
        self._encryption_key = encryption_key or getattr(settings, "fivepaisa_encryption_key", "")

        if token_path is not None:
            self._token_path = token_path
        else:
            self._token_path = settings.data_path / ".fivepaisa_token.json"

        self._client_code: str = ""
        self._jwt_token: str | None = None
        self._cookie: str | None = None
        self._authenticated = False

        # Rate limiting
        self._last_request_time: float = 0.0
        self._min_interval: float = 1.0 / rate_limit

        self._load_token()

    # ── Authentication ────────────────────────────────────────────────

    def generate_auth_url(self) -> str:
        """5paisa uses TOTP/direct login, not OAuth redirect.

        Returns a descriptive message instead.
        """
        if not self._app_name:
            raise AuthenticationError(
                "5paisa credentials not configured. Set FIVEPAISA_APP_NAME in .env"
            )
        return (
            "5paisa uses direct TOTP login. "
            "Call authenticate(totp_code) with your TOTP token."
        )

    def authenticate(self, auth_code: str) -> dict[str, Any]:
        """Authenticate using TOTP code or request token.

        For 5paisa, auth_code can be:
        - A TOTP code for TOTP-based login
        - A request token from the OAuth flow (if using vendor API)
        """
        if not self._user_key:
            raise AuthenticationError(
                "5paisa user key not configured. Set FIVEPAISA_USER_KEY in .env"
            )

        # Try OAuth-style token exchange first
        url = f"{_FIVEPAISA_TRADE_BASE}/connect/token"
        payload = {
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": getattr(
                get_settings(), "fivepaisa_redirect_uri",
                "http://localhost:8000/fivepaisa/callback",
            ),
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

        try:
            resp = requests.post(url, data=payload, headers=headers, timeout=30)
            data = resp.json()

            if "access_token" in data:
                self._jwt_token = data["access_token"]
                self._client_code = str(data.get("clientcode", self._user_id))
                self._authenticated = True
                self._save_token()
                logger.info("fivepaisa_authenticated_via_oauth")
                return data

            # Fallback: try TOTP-based login
            return self._totp_login(auth_code)

        except requests.exceptions.RequestException as exc:
            # Try TOTP login as fallback
            logger.debug("fivepaisa_oauth_failed_trying_totp", error=str(exc))
            return self._totp_login(auth_code)

    def _totp_login(self, totp: str) -> dict[str, Any]:
        """5paisa TOTP-based login."""
        url = f"{_FIVEPAISA_TRADE_BASE}/connect/token"
        payload = {
            "grant_type": "authorization_code",
            "code": totp,
            "state": "Authorization",
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }

        try:
            resp = requests.post(url, data=payload, headers=headers, timeout=30)
            data = resp.json()

            if "access_token" in data:
                self._jwt_token = data["access_token"]
                self._client_code = str(data.get("clientcode", self._user_id))
                self._authenticated = True
                self._save_token()
                logger.info("fivepaisa_authenticated_via_totp")
                return data

            raise AuthenticationError(
                f"5paisa login failed: {data.get('error_description', data)}"
            )
        except requests.exceptions.RequestException as exc:
            raise AuthenticationError(f"5paisa auth network error: {exc}") from exc

    @property
    def is_authenticated(self) -> bool:
        return self._authenticated and bool(self._jwt_token)

    def get_token_status(self) -> dict[str, Any]:
        return {
            "access_token_valid": self.is_authenticated,
            "needs_full_reauth": not self.is_authenticated,
            "client_code": self._client_code,
        }

    # ── Token Persistence ─────────────────────────────────────────────

    def _save_token(self) -> None:
        if not self._jwt_token:
            return
        data = {
            "jwt_token": self._jwt_token,
            "client_code": self._client_code,
            "saved_at": datetime.now().isoformat(),
        }
        self._token_path.parent.mkdir(parents=True, exist_ok=True)
        self._token_path.write_text(json.dumps(data, indent=2))
        logger.debug("fivepaisa_token_saved")

    def _load_token(self) -> None:
        if not self._token_path.exists():
            return
        try:
            data = json.loads(self._token_path.read_text())
            self._jwt_token = data.get("jwt_token")
            self._client_code = data.get("client_code", "")
            if self._jwt_token:
                self._authenticated = True
                logger.info("fivepaisa_token_loaded_from_disk")
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("fivepaisa_token_load_failed", error=str(exc))

    # ── Rate Limiting ─────────────────────────────────────────────────

    def _wait_for_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.monotonic()

    # ── API Call Wrapper ──────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._jwt_token:
            headers["Authorization"] = f"Bearer {self._jwt_token}"
        return headers

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(RateLimitError),
        reraise=True,
    )
    def _api_call(
        self,
        method: str,
        url: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self._jwt_token:
            raise AuthenticationError("Not authenticated with 5paisa.")
        self._wait_for_rate_limit()

        try:
            if method == "GET":
                resp = requests.get(url, headers=self._headers(), params=payload, timeout=30)
            else:
                resp = requests.post(url, headers=self._headers(), json=payload, timeout=30)

            if resp.status_code == 429:
                raise RateLimitError("5paisa rate limit hit")
            resp.raise_for_status()
            return resp.json()
        except RateLimitError:
            raise
        except requests.exceptions.RequestException as exc:
            raise APIError(f"5paisa API call failed: {exc}") from exc

    # ── Account ───────────────────────────────────────────────────────

    def get_profile(self) -> dict[str, Any]:
        url = f"{_FIVEPAISA_TRADE_BASE}/connect/customerinfo"
        return self._api_call("GET", url)

    def get_funds(self) -> dict[str, Any]:
        url = f"{_FIVEPAISA_TRADE_BASE}/connect/margin"
        payload = {"ClientCode": self._client_code}
        return self._api_call("POST", url, payload)

    # ── Market Data ───────────────────────────────────────────────────

    def get_quotes(self, symbols: list[str]) -> dict[str, Any]:
        url = f"{_FIVEPAISA_TRADE_BASE}/connect/marketfeed"
        scrip_list = [{"Exch": "N", "ExchType": "C", "ScripCode": self.translate_symbol(s)} for s in symbols]
        payload = {
            "ClientCode": self._client_code,
            "Count": len(scrip_list),
            "MarketFeedData": scrip_list,
        }
        return self._api_call("POST", url, payload)

    def get_history(
        self,
        symbol: str,
        resolution: str,
        range_from: str,
        range_to: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        url = f"{_FIVEPAISA_TRADE_BASE}/connect/historical"
        payload = {
            "Exch": "N",
            "ExchType": "C",
            "ScripCode": int(self.translate_symbol(symbol)),
            "time": self._map_resolution(resolution),
            "From": range_from,
            "To": range_to,
        }
        result = self._api_call("POST", url, payload)

        # Normalize to Fyers-compatible format
        candles = result.get("data", result.get("Data", []))
        if not candles:
            raise DataFetchError(
                f"No candle data from 5paisa for {symbol} ({resolution})"
            )
        return {"candles": candles, "s": "ok"}

    def get_market_depth(self, symbol: str) -> dict[str, Any]:
        url = f"{_FIVEPAISA_TRADE_BASE}/connect/depth"
        payload = {
            "ClientCode": self._client_code,
            "Count": 1,
            "MarketFeedData": [{"Exch": "N", "ExchType": "C", "ScripCode": int(self.translate_symbol(symbol))}],
        }
        return self._api_call("POST", url, payload)

    def get_option_chain(
        self, symbol: str, strike_count: int = 5, **kwargs: Any,
    ) -> dict[str, Any]:
        url = f"{_FIVEPAISA_TRADE_BASE}/connect/optionchain"
        payload = {
            "Exch": "N",
            "ExchType": "D",
            "ScripCode": int(self.translate_symbol(symbol)),
            "StrikeRate": strike_count,
        }
        return self._api_call("POST", url, payload)

    # ── Orders & Trading ──────────────────────────────────────────────

    def place_order(self, params: BrokerOrderParams) -> BrokerOrderResponse:
        url = f"{_FIVEPAISA_TRADE_BASE}/connect/placeorder"
        native_params = self.translate_order_params(params)
        try:
            result = self._api_call("POST", url, native_params)
            status = int(result.get("Status", 1))
            success = status == 0
            order_id = str(result.get("BrokerOrderID", ""))
            return BrokerOrderResponse(
                success=success,
                order_id=order_id,
                message=result.get("Message", ""),
                raw=result,
            )
        except Exception as exc:
            return BrokerOrderResponse(
                success=False, message=f"5paisa order failed: {exc}",
            )

    def modify_order(self, order_id: str, params: dict[str, Any]) -> BrokerOrderResponse:
        url = f"{_FIVEPAISA_TRADE_BASE}/connect/modifyorder"
        data = {"ExchOrderID": order_id, **params}
        try:
            result = self._api_call("POST", url, data)
            status = int(result.get("Status", 1))
            return BrokerOrderResponse(
                success=status == 0,
                order_id=order_id,
                message=result.get("Message", ""),
                raw=result,
            )
        except Exception as exc:
            return BrokerOrderResponse(
                success=False, order_id=order_id, message=str(exc),
            )

    def cancel_order(self, order_id: str) -> BrokerOrderResponse:
        url = f"{_FIVEPAISA_TRADE_BASE}/connect/cancelorder"
        try:
            result = self._api_call("POST", url, {"ExchOrderID": order_id})
            status = int(result.get("Status", 1))
            return BrokerOrderResponse(
                success=status == 0,
                order_id=order_id,
                message=result.get("Message", ""),
                raw=result,
            )
        except Exception as exc:
            return BrokerOrderResponse(
                success=False, order_id=order_id, message=str(exc),
            )

    def get_orders(self) -> dict[str, Any]:
        url = f"{_FIVEPAISA_TRADE_BASE}/connect/orderbook"
        return self._api_call("POST", url, {"ClientCode": self._client_code})

    def get_positions(self) -> dict[str, Any]:
        url = f"{_FIVEPAISA_TRADE_BASE}/connect/netposition"
        return self._api_call("POST", url, {"ClientCode": self._client_code})

    def get_tradebook(self) -> dict[str, Any]:
        url = f"{_FIVEPAISA_TRADE_BASE}/connect/tradebook"
        return self._api_call("POST", url, {"ClientCode": self._client_code})

    def get_holdings(self) -> dict[str, Any]:
        url = f"{_FIVEPAISA_TRADE_BASE}/connect/holdings"
        return self._api_call("POST", url, {"ClientCode": self._client_code})

    # ── Symbol Translation ────────────────────────────────────────────

    # 5paisa uses ScripCode (integer). This is a basic mapping;
    # production would use the full scrip master CSV.

    _SYMBOL_MAP: dict[str, str] = {
        "NSE:NIFTY50-INDEX": "999920000",
        "NSE:NIFTYBANK-INDEX": "999920005",
        "NSE:FINNIFTY-INDEX": "999920041",
        "BSE:SENSEX-INDEX": "999901",
        "NSE:RELIANCE-EQ": "2885",
        "NSE:TCS-EQ": "11536",
        "NSE:INFY-EQ": "1594",
        "NSE:HDFCBANK-EQ": "1330",
        "NSE:ICICIBANK-EQ": "4963",
    }

    def translate_symbol(self, universal_symbol: str) -> str:
        return self._SYMBOL_MAP.get(universal_symbol, universal_symbol)

    def translate_order_params(self, params: BrokerOrderParams) -> dict[str, Any]:
        side_map = {1: "B", -1: "S"}
        type_map = {1: "MKT", 2: "L", 3: "SL-M", 4: "SL"}

        native: dict[str, Any] = {
            "ClientCode": self._client_code,
            "Exch": "N",
            "ExchType": "C",
            "ScripCode": int(self.translate_symbol(params.symbol)),
            "Qty": params.quantity,
            "BuySell": side_map.get(params.side, "B"),
            "OrderType": type_map.get(params.order_type, "MKT"),
            "IsIntraday": params.product_type == "INTRADAY",
            "AtMarket": params.order_type == 1,
            "RemoteOrderID": params.tag or "AI_TRADER",
        }

        if params.limit_price is not None:
            native["Price"] = params.limit_price
        else:
            native["Price"] = 0

        if params.stop_price is not None:
            native["StopLossPrice"] = params.stop_price
        else:
            native["StopLossPrice"] = 0

        return native

    @staticmethod
    def _map_resolution(resolution: str) -> str:
        mapping = {
            "1": "1m",
            "3": "3m",
            "5": "5m",
            "15": "15m",
            "30": "30m",
            "60": "1h",
            "D": "1d",
            "W": "1w",
            "M": "1M",
        }
        return mapping.get(resolution, "1d")

    def close(self) -> None:
        self._jwt_token = None
        self._authenticated = False
        logger.info("fivepaisa_client_closed")
