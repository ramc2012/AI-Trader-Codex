"""Indian market trading hours and calendar utilities."""

from datetime import time
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
