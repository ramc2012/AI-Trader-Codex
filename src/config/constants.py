"""Application-wide constants.

Centralizes magic numbers and string literals used across the codebase.
"""

# =============================================================================
# Supported Symbols
# =============================================================================
NIFTY_SYMBOL = "NSE:NIFTY50-INDEX"
BANKNIFTY_SYMBOL = "NSE:NIFTYBANK-INDEX"
SENSEX_SYMBOL = "BSE:SENSEX-INDEX"

INDEX_SYMBOLS = [NIFTY_SYMBOL, BANKNIFTY_SYMBOL, SENSEX_SYMBOL]

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
RETENTION_TICK = 7
RETENTION_1M = 90
RETENTION_INTRADAY = 730  # 2 years for 5m+
RETENTION_DAILY = -1  # forever

# =============================================================================
# Risk Limits (hard-coded safety)
# =============================================================================
ABSOLUTE_MAX_DAILY_LOSS_PCT = 5.0
ABSOLUTE_MAX_POSITION_SIZE_PCT = 10.0
ABSOLUTE_MAX_OPEN_POSITIONS = 5

# =============================================================================
# API
# =============================================================================
API_V1_PREFIX = "/api/v1"
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 10000
