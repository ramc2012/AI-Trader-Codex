"""Application-wide constants.

Centralizes magic numbers and string literals used across the codebase.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.config.agent_universe import (
    DEFAULT_AGENT_NSE_SYMBOLS,
    DEFAULT_WATCHLIST_NSE_SYMBOLS,
)

# =============================================================================
# Supported Symbols
# =============================================================================
NIFTY_SYMBOL = "NSE:NIFTY50-INDEX"
BANKNIFTY_SYMBOL = "NSE:NIFTYBANK-INDEX"
SENSEX_SYMBOL = "BSE:SENSEX-INDEX"
FINNIFTY_SYMBOL = "NSE:FINNIFTY-INDEX"
MIDCPNIFTY_SYMBOL = "NSE:NIFTYMIDCAP50-INDEX"

INDEX_SYMBOLS = [NIFTY_SYMBOL, BANKNIFTY_SYMBOL, SENSEX_SYMBOL, FINNIFTY_SYMBOL, MIDCPNIFTY_SYMBOL]
FUTURES_SYMBOLS: list[str] = []
ALL_WATCHLIST_SYMBOLS = list(DEFAULT_WATCHLIST_NSE_SYMBOLS)


@dataclass(frozen=True)
class IndexInstrument:
    name: str
    spot_symbol: str
    futures_root: str
    exchange: str


INDEX_INSTRUMENTS: dict[str, IndexInstrument] = {
    "NIFTY": IndexInstrument(
        name="NIFTY",
        spot_symbol=NIFTY_SYMBOL,
        futures_root="NIFTY",
        exchange="NSE",
    ),
    "BANKNIFTY": IndexInstrument(
        name="BANKNIFTY",
        spot_symbol=BANKNIFTY_SYMBOL,
        futures_root="BANKNIFTY",
        exchange="NSE",
    ),
    "FINNIFTY": IndexInstrument(
        name="FINNIFTY",
        spot_symbol=FINNIFTY_SYMBOL,
        futures_root="FINNIFTY",
        exchange="NSE",
    ),
    "MIDCPNIFTY": IndexInstrument(
        name="MIDCPNIFTY",
        spot_symbol=MIDCPNIFTY_SYMBOL,
        futures_root="MIDCPNIFTY",
        exchange="NSE",
    ),
    "SENSEX": IndexInstrument(
        name="SENSEX",
        spot_symbol=SENSEX_SYMBOL,
        futures_root="SENSEX",
        exchange="BSE",
    ),
}


def build_monthly_futures_symbol(root: str, exchange: str, dt: datetime) -> str:
    """Build futures symbol string for a given month/year.

    Example: NSE:NIFTY26FEBFUT
    """
    year_2d = f"{dt.year % 100:02d}"
    month = dt.strftime("%b").upper()
    return f"{exchange}:{root}{year_2d}{month}FUT"

# =============================================================================
# Timeframes
# =============================================================================
TIMEFRAME_1M = "1"
TIMEFRAME_3M = "3"
TIMEFRAME_5M = "5"
TIMEFRAME_15M = "15"
TIMEFRAME_30M = "30"
TIMEFRAME_60M = "60"
TIMEFRAME_1D = "D"
TIMEFRAME_1W = "W"
TIMEFRAME_1MO = "M"

INTRADAY_TIMEFRAMES = [
    TIMEFRAME_1M,
    TIMEFRAME_3M,
    TIMEFRAME_5M,
    TIMEFRAME_15M,
    TIMEFRAME_30M,
    TIMEFRAME_60M,
]

POSITIONAL_TIMEFRAMES = [TIMEFRAME_1D, TIMEFRAME_1W, TIMEFRAME_1MO]

ALL_TIMEFRAMES = INTRADAY_TIMEFRAMES + POSITIONAL_TIMEFRAMES

# Fyers resolution mapping (what to pass to the API)
FYERS_RESOLUTION_MAP: dict[str, str] = {
    TIMEFRAME_1M: "1",
    TIMEFRAME_3M: "3",
    TIMEFRAME_5M: "5",
    TIMEFRAME_15M: "15",
    TIMEFRAME_30M: "30",
    TIMEFRAME_60M: "60",
    TIMEFRAME_1D: "D",
    TIMEFRAME_1W: "W",
    TIMEFRAME_1MO: "M",
}

# =============================================================================
# Data Retention (days)
# =============================================================================
RETENTION_TICK = 10
RETENTION_1M = 90
RETENTION_INTRADAY = 730  # 2 years for 5m+
RETENTION_DAILY = -1  # forever

# =============================================================================
# Risk Limits (hard-coded safety)
# =============================================================================
ABSOLUTE_MAX_DAILY_LOSS_PCT = 5.0
ABSOLUTE_MAX_POSITION_SIZE_PCT = 10.0
ABSOLUTE_MAX_OPEN_POSITIONS = 6

# =============================================================================
# API
# =============================================================================
API_V1_PREFIX = "/api/v1"
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 10000
