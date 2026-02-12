"""Indian market trading hours and calendar utilities."""

from datetime import datetime, time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# NSE equity market hours
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)

# Pre-market session
PRE_MARKET_OPEN = time(9, 0)
PRE_MARKET_CLOSE = time(9, 8)

# Post-market (closing session)
POST_MARKET_OPEN = time(15, 40)
POST_MARKET_CLOSE = time(16, 0)

# Fyers data feed availability (slightly wider than market hours)
DATA_FEED_START = time(9, 0)
DATA_FEED_END = time(15, 35)

# Days the market is open (Monday=0, Sunday=6)
TRADING_DAYS = {0, 1, 2, 3, 4}  # Mon-Fri


def is_market_open(dt: datetime = None) -> bool:
    """Check if market is currently open.

    Args:
        dt: Datetime to check (defaults to now in IST)

    Returns:
        True if market is open, False otherwise
    """
    if dt is None:
        dt = datetime.now(IST)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)

    # Check if it's a trading day (Mon-Fri)
    if dt.weekday() not in TRADING_DAYS:
        return False

    # Check if time is within market hours
    current_time = dt.time()
    return MARKET_OPEN <= current_time <= MARKET_CLOSE
