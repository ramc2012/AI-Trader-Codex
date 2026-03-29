"""Upstox API v2 client implementing the BrokerBase interface.

Provides authentication, market data, and order management via
the Upstox API. Designed as a drop-in alternative to the Fyers client.
"""

from __future__ import annotations

import asyncio
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

_ACCESS_TOKEN_LIFETIME = timedelta(hours=6)  # Upstox tokens expire same day
_UPSTOX_API_BASE = "https://api.upstox.com/v2"


class UpstoxClient(BrokerBase):
    """Upstox API v2 client with auth management, rate limiting, and retries.

    Args:
        api_key: Upstox API key. Defaults to settings.
        api_secret: Upstox API secret. Defaults to settings.
        redirect_uri: OAuth redirect URI. Defaults to settings.
        token_path: Path to persist the access token.
        rate_limit: Max API requests per second.
    """

    name = BrokerName.UPSTOX

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        redirect_uri: str | None = None,
        token_path: Path | None = None,
        rate_limit: int = 10,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key or getattr(settings, "upstox_api_key", "")
        self._api_secret = api_secret or getattr(settings, "upstox_api_secret", "")
        self._redirect_uri = redirect_uri or getattr(
            settings, "upstox_redirect_uri", "http://localhost:8000/upstox/callback"
        )

        if token_path is not None:
            self._token_path = token_path
        else:
            self._token_path = settings.data_path / ".upstox_token.json"

        self._access_token: str | None = None
        self._access_token_expires_at: str | None = None

        # Rate limiting
        self._last_request_time: float = 0.0
        self._min_interval: float = 1.0 / rate_limit

        self._load_token()

    # ── Authentication ────────────────────────────────────────────────

    def generate_auth_url(self) -> str:
        if not self._api_key:
            raise AuthenticationError(
                "Upstox API key not configured. Set UPSTOX_API_KEY in .env"
            )
        url = (
            f"https://api.upstox.com/v2/login/authorization/dialog"
            f"?response_type=code"
            f"&client_id={self._api_key}"
            f"&redirect_uri={self._redirect_uri}"
        )
        logger.info("upstox_auth_url_generated")
        return url

    def authenticate(self, auth_code: str) -> dict[str, Any]:
        if not self._api_key or not self._api_secret:
            raise AuthenticationError(
                "Upstox API key and secret must be configured."
            )

        url = f"{_UPSTOX_API_BASE}/login/authorization/token"
        payload = {
            "code": auth_code,
            "client_id": self._api_key,
            "client_secret": self._api_secret,
            "redirect_uri": self._redirect_uri,
            "grant_type": "authorization_code",
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

        try:
            resp = requests.post(url, data=payload, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as exc:
            raise AuthenticationError(f"Upstox auth failed: {exc}") from exc

        if "access_token" not in data:
            raise AuthenticationError(
                f"Upstox token exchange failed: {data.get('message', data)}"
            )

        self._access_token = data["access_token"]
        now = datetime.now()
        self._access_token_expires_at = (now + _ACCESS_TOKEN_LIFETIME).isoformat()
        self._save_token()

        logger.info("upstox_authenticated")
        return data

    @property
    def is_authenticated(self) -> bool:
        if not self._access_token:
            return False
        try:
            result = self.get_profile()
            return result.get("status") == "success"
        except Exception:
            return False

    def get_token_status(self) -> dict[str, Any]:
        status: dict[str, Any] = {
            "access_token_valid": bool(self._access_token),
            "access_token_expires_in_hours": None,
            "needs_full_reauth": not bool(self._access_token),
        }
        if self._access_token_expires_at:
            try:
                from dateutil import parser
                expiry = parser.isoparse(self._access_token_expires_at)
                delta = expiry - datetime.now()
                status["access_token_expires_in_hours"] = delta.total_seconds() / 3600
            except Exception:
                pass
        return status

    # ── Token Persistence ─────────────────────────────────────────────

    def _save_token(self) -> None:
        if not self._access_token:
            return
        data = {
            "access_token": self._access_token,
            "saved_at": datetime.now().isoformat(),
            "access_token_expires_at": self._access_token_expires_at,
        }
        self._token_path.parent.mkdir(parents=True, exist_ok=True)
        self._token_path.write_text(json.dumps(data, indent=2))
        logger.debug("upstox_token_saved", path=str(self._token_path))

    def _load_token(self) -> None:
        if not self._token_path.exists():
            return
        try:
            data = json.loads(self._token_path.read_text())
            self._access_token = data.get("access_token")
            self._access_token_expires_at = data.get("access_token_expires_at")
            logger.info("upstox_token_loaded_from_disk")
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("upstox_token_load_failed", error=str(exc))

    # ── Rate Limiting ─────────────────────────────────────────────────

    def _wait_for_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.monotonic()

    # ── API Call Wrapper ──────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(RateLimitError),
        reraise=True,
    )
    def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._access_token:
            raise AuthenticationError("Not authenticated with Upstox.")
        self._wait_for_rate_limit()

        url = f"{_UPSTOX_API_BASE}{endpoint}"
        try:
            resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
            if resp.status_code == 429:
                raise RateLimitError("Upstox rate limit hit")
            resp.raise_for_status()
            return resp.json()
        except RateLimitError:
            raise
        except requests.exceptions.RequestException as exc:
            raise APIError(f"Upstox API call failed: {exc}") from exc

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(RateLimitError),
        reraise=True,
    )
    def _post(self, endpoint: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._access_token:
            raise AuthenticationError("Not authenticated with Upstox.")
        self._wait_for_rate_limit()

        url = f"{_UPSTOX_API_BASE}{endpoint}"
        try:
            resp = requests.post(url, headers=self._headers(), json=data, timeout=30)
            if resp.status_code == 429:
                raise RateLimitError("Upstox rate limit hit")
            resp.raise_for_status()
            return resp.json()
        except RateLimitError:
            raise
        except requests.exceptions.RequestException as exc:
            raise APIError(f"Upstox API call failed: {exc}") from exc

    def _put(self, endpoint: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._access_token:
            raise AuthenticationError("Not authenticated with Upstox.")
        self._wait_for_rate_limit()

        url = f"{_UPSTOX_API_BASE}{endpoint}"
        try:
            resp = requests.put(url, headers=self._headers(), json=data, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as exc:
            raise APIError(f"Upstox API call failed: {exc}") from exc

    def _delete(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._access_token:
            raise AuthenticationError("Not authenticated with Upstox.")
        self._wait_for_rate_limit()

        url = f"{_UPSTOX_API_BASE}{endpoint}"
        try:
            resp = requests.delete(url, headers=self._headers(), params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as exc:
            raise APIError(f"Upstox API call failed: {exc}") from exc

    # ── Account ───────────────────────────────────────────────────────

    def get_profile(self) -> dict[str, Any]:
        return self._get("/user/profile")

    def get_funds(self) -> dict[str, Any]:
        return self._get("/user/get-funds-and-margin")

    # ── Market Data ───────────────────────────────────────────────────

    def get_quotes(self, symbols: list[str]) -> dict[str, Any]:
        translated = [self.translate_symbol(s) for s in symbols]
        symbol_str = ",".join(translated)
        return self._get("/market-quote/quotes", params={"instrument_key": symbol_str})

    def get_history(
        self,
        symbol: str,
        resolution: str,
        range_from: str,
        range_to: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        instrument_key = self.translate_symbol(symbol)
        interval = self._map_resolution(resolution)
        result = self._get(
            f"/historical-candle/{instrument_key}/{interval}/{range_to}/{range_from}"
        )

        # Normalize to the same format as Fyers: {"candles": [[ts, O, H, L, C, V], ...]}
        candles = result.get("data", {}).get("candles", [])
        if not candles:
            raise DataFetchError(
                f"No candle data from Upstox for {symbol} ({resolution})"
            )
        return {"candles": candles, "s": "ok"}

    def get_market_depth(self, symbol: str) -> dict[str, Any]:
        instrument_key = self.translate_symbol(symbol)
        return self._get("/market-quote/market-depth", params={"instrument_key": instrument_key})

    def get_option_chain(
        self, symbol: str, strike_count: int = 5, **kwargs: Any,
    ) -> dict[str, Any]:
        instrument_key = self.translate_symbol(symbol)
        return self._get(
            "/option/chain",
            params={"instrument_key": instrument_key, "expiry_date": kwargs.get("expiry_date", "")},
        )

    # ── Orders & Trading ──────────────────────────────────────────────

    def place_order(self, params: BrokerOrderParams) -> BrokerOrderResponse:
        native_params = self.translate_order_params(params)
        try:
            result = self._post("/order/place", data=native_params)
            success = result.get("status") == "success"
            order_id = str(result.get("data", {}).get("order_id", ""))
            return BrokerOrderResponse(
                success=success,
                order_id=order_id,
                message=result.get("message", ""),
                raw=result,
            )
        except Exception as exc:
            return BrokerOrderResponse(
                success=False, message=f"Order placement failed: {exc}",
            )

    def modify_order(self, order_id: str, params: dict[str, Any]) -> BrokerOrderResponse:
        data = {"order_id": order_id, **params}
        try:
            result = self._put("/order/modify", data=data)
            success = result.get("status") == "success"
            return BrokerOrderResponse(
                success=success,
                order_id=order_id,
                message=result.get("message", ""),
                raw=result,
            )
        except Exception as exc:
            return BrokerOrderResponse(
                success=False, order_id=order_id, message=str(exc),
            )

    def cancel_order(self, order_id: str) -> BrokerOrderResponse:
        try:
            result = self._delete("/order/cancel", params={"order_id": order_id})
            success = result.get("status") == "success"
            return BrokerOrderResponse(
                success=success,
                order_id=order_id,
                message=result.get("message", ""),
                raw=result,
            )
        except Exception as exc:
            return BrokerOrderResponse(
                success=False, order_id=order_id, message=str(exc),
            )

    def get_orders(self) -> dict[str, Any]:
        return self._get("/order/retrieve-all")

    def get_positions(self) -> dict[str, Any]:
        return self._get("/portfolio/short-term-positions")

    def get_tradebook(self) -> dict[str, Any]:
        return self._get("/order/trades/get-trades-for-day")

    def get_holdings(self) -> dict[str, Any]:
        return self._get("/portfolio/long-term-holdings")

    # ── Symbol Translation ────────────────────────────────────────────

    # Upstox uses instrument_key format: "NSE_EQ|INE002A01018"
    # Our universal format: "NSE:RELIANCE-EQ"
    # We provide a basic mapping; production would use the full instrument master

    _SYMBOL_MAP: dict[str, str] = {
        "NSE:NIFTY50-INDEX": "NSE_INDEX|Nifty 50",
        "NSE:NIFTYBANK-INDEX": "NSE_INDEX|Nifty Bank",
        "NSE:FINNIFTY-INDEX": "NSE_INDEX|Nifty Fin Service",
        "BSE:SENSEX-INDEX": "BSE_INDEX|SENSEX",
    }

    def translate_symbol(self, universal_symbol: str) -> str:
        if universal_symbol in self._SYMBOL_MAP:
            return self._SYMBOL_MAP[universal_symbol]

        # Generic translation: "NSE:RELIANCE-EQ" → "NSE_EQ|RELIANCE"
        if ":" in universal_symbol:
            exchange, ticker = universal_symbol.split(":", 1)
            ticker = ticker.replace("-EQ", "").replace("-INDEX", "")
            segment = f"{exchange}_EQ"
            return f"{segment}|{ticker}"

        return universal_symbol

    def translate_order_params(self, params: BrokerOrderParams) -> dict[str, Any]:
        side_map = {1: "BUY", -1: "SELL"}
        type_map = {1: "MARKET", 2: "LIMIT", 3: "SL", 4: "SL-M"}
        product_map = {
            "INTRADAY": "I",
            "CNC": "D",
            "MARGIN": "D",
        }

        native: dict[str, Any] = {
            "instrument_token": self.translate_symbol(params.symbol),
            "quantity": params.quantity,
            "transaction_type": side_map.get(params.side, "BUY"),
            "order_type": type_map.get(params.order_type, "MARKET"),
            "product": product_map.get(params.product_type, "I"),
            "validity": "DAY",
            "disclosed_quantity": 0,
            "trigger_price": 0,
            "is_amo": False,
        }

        if params.limit_price is not None:
            native["price"] = params.limit_price
        else:
            native["price"] = 0

        if params.stop_price is not None:
            native["trigger_price"] = params.stop_price

        return native

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _map_resolution(resolution: str) -> str:
        mapping = {
            "1": "1minute",
            "3": "3minute",
            "5": "5minute",
            "15": "15minute",
            "30": "30minute",
            "60": "1hour",
            "D": "day",
            "W": "week",
            "M": "month",
        }
        return mapping.get(resolution, "day")

    def close(self) -> None:
        self._access_token = None
        logger.info("upstox_client_closed")
