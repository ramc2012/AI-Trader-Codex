"""Abstract broker interface for multi-broker support.

All broker clients (Fyers, Upstox, 5paisa) implement this interface,
allowing the order manager and trading agent to work with any broker
without coupling to a specific API.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class BrokerName(str, Enum):
    """Supported broker identifiers."""

    FYERS = "fyers"
    UPSTOX = "upstox"
    FIVEPAISA = "fivepaisa"


@dataclass
class BrokerOrderParams:
    """Broker-agnostic order parameters.

    Each broker client's ``translate_order()`` method converts this
    into the broker's native format.
    """

    symbol: str
    quantity: int
    side: int  # 1 = BUY, -1 = SELL
    order_type: int  # 1=MARKET, 2=LIMIT, 3=STOP, 4=STOP_LIMIT
    product_type: str = "INTRADAY"  # INTRADAY / CNC / MARGIN
    limit_price: float | None = None
    stop_price: float | None = None
    validity: str = "DAY"
    tag: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "side": self.side,
            "order_type": self.order_type,
            "product_type": self.product_type,
            "validity": self.validity,
        }
        if self.limit_price is not None:
            d["limit_price"] = self.limit_price
        if self.stop_price is not None:
            d["stop_price"] = self.stop_price
        if self.tag:
            d["tag"] = self.tag
        return d


@dataclass
class BrokerOrderResponse:
    """Standardized response from a broker order operation."""

    success: bool
    order_id: str = ""
    message: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class BrokerQuote:
    """Standardized quote data from any broker."""

    symbol: str
    ltp: float
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    prev_close: float = 0.0
    volume: int = 0
    change: float = 0.0
    change_pct: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    oi: int = 0
    timestamp: datetime | None = None


class BrokerBase(ABC):
    """Abstract base class for all broker integrations.

    Subclasses must implement every abstract method. The trading agent
    and order manager interact exclusively through this interface.
    """

    name: BrokerName

    # ── Authentication ────────────────────────────────────────────────

    @abstractmethod
    def generate_auth_url(self) -> str:
        """Generate the OAuth/login URL for user authentication."""
        ...

    @abstractmethod
    def authenticate(self, auth_code: str) -> dict[str, Any]:
        """Exchange an auth code for an access token."""
        ...

    @property
    @abstractmethod
    def is_authenticated(self) -> bool:
        """Whether the client has a valid, active session."""
        ...

    @abstractmethod
    def get_token_status(self) -> dict[str, Any]:
        """Return token validity, expiry, and refresh status."""
        ...

    # ── Account ───────────────────────────────────────────────────────

    @abstractmethod
    def get_profile(self) -> dict[str, Any]:
        """Fetch the authenticated user's profile."""
        ...

    @abstractmethod
    def get_funds(self) -> dict[str, Any]:
        """Fetch available funds and margin information."""
        ...

    # ── Market Data ───────────────────────────────────────────────────

    @abstractmethod
    def get_quotes(self, symbols: list[str]) -> dict[str, Any]:
        """Fetch real-time quotes for the given symbols."""
        ...

    @abstractmethod
    def get_history(
        self,
        symbol: str,
        resolution: str,
        range_from: str,
        range_to: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Fetch historical OHLCV candle data."""
        ...

    @abstractmethod
    def get_market_depth(self, symbol: str) -> dict[str, Any]:
        """Fetch market depth (order book) for a symbol."""
        ...

    @abstractmethod
    def get_option_chain(
        self, symbol: str, strike_count: int = 5, **kwargs: Any,
    ) -> dict[str, Any]:
        """Fetch option chain for an underlying."""
        ...

    # ── Orders & Trading ──────────────────────────────────────────────

    @abstractmethod
    def place_order(self, params: BrokerOrderParams) -> BrokerOrderResponse:
        """Place a new order."""
        ...

    @abstractmethod
    def modify_order(self, order_id: str, params: dict[str, Any]) -> BrokerOrderResponse:
        """Modify an existing order."""
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> BrokerOrderResponse:
        """Cancel an existing order."""
        ...

    @abstractmethod
    def get_orders(self) -> dict[str, Any]:
        """Fetch the order book."""
        ...

    @abstractmethod
    def get_positions(self) -> dict[str, Any]:
        """Fetch open positions."""
        ...

    @abstractmethod
    def get_tradebook(self) -> dict[str, Any]:
        """Fetch today's executed trades."""
        ...

    @abstractmethod
    def get_holdings(self) -> dict[str, Any]:
        """Fetch portfolio holdings."""
        ...

    # ── Symbol Translation ────────────────────────────────────────────

    @abstractmethod
    def translate_symbol(self, universal_symbol: str) -> str:
        """Convert a universal symbol (e.g. 'NSE:RELIANCE-EQ') to broker format."""
        ...

    @abstractmethod
    def translate_order_params(self, params: BrokerOrderParams) -> dict[str, Any]:
        """Convert generic order params to broker-native API format."""
        ...

    # ── Lifecycle ─────────────────────────────────────────────────────

    @abstractmethod
    def close(self) -> None:
        """Clean up resources."""
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} broker={self.name.value}>"
