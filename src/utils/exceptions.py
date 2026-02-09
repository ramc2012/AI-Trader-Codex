"""Custom exception hierarchy for the trading system.

All application exceptions inherit from NiftyTraderError so they can
be caught broadly or specifically as needed.
"""


class NiftyTraderError(Exception):
    """Base exception for the Nifty AI Trader application."""


# --- Authentication & API ---


class AuthenticationError(NiftyTraderError):
    """Fyers authentication failed or token expired."""


class APIError(NiftyTraderError):
    """General Fyers API error."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


class RateLimitError(APIError):
    """API rate limit exceeded."""


# --- Data ---


class DataError(NiftyTraderError):
    """Base error for data-related issues."""


class DataValidationError(DataError):
    """Data failed validation checks (e.g., OHLC logic)."""


class DataFetchError(DataError):
    """Failed to fetch data from source."""


class DataGapError(DataError):
    """Missing data detected in time series."""


# --- Database ---


class DatabaseError(NiftyTraderError):
    """Database operation failed."""


class ConnectionError(DatabaseError):
    """Cannot connect to database."""


# --- Trading ---


class TradingError(NiftyTraderError):
    """Base error for trading operations."""


class OrderError(TradingError):
    """Order placement or management failed."""


class RiskLimitError(TradingError):
    """Risk limit would be breached."""


class InsufficientFundsError(TradingError):
    """Not enough funds for the requested operation."""


# --- Configuration ---


class ConfigurationError(NiftyTraderError):
    """Invalid or missing configuration."""
