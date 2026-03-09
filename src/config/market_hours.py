"""Market-session utilities for NSE and global markets."""

import os
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
US_EASTERN = ZoneInfo("America/New_York")

# NSE equity market hours
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)

# US regular market hours (Eastern Time).
US_MARKET_OPEN = time(9, 30)
US_MARKET_CLOSE = time(16, 0)

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


def _load_holiday_overrides() -> set[date]:
    """Load holiday overrides from env var `MARKET_HOLIDAYS` (YYYY-MM-DD,comma-separated)."""
    raw = os.getenv("MARKET_HOLIDAYS", "").strip()
    if not raw:
        return set()
    holidays: set[date] = set()
    for token in raw.split(","):
        value = token.strip()
        if not value:
            continue
        try:
            holidays.add(datetime.strptime(value, "%Y-%m-%d").date())
        except ValueError:
            continue
    return holidays


HOLIDAY_OVERRIDES = _load_holiday_overrides()


def _normalize_dt(dt: datetime | None = None) -> datetime:
    if dt is None:
        return datetime.now(IST)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


def is_market_holiday(dt: datetime | None = None) -> bool:
    local = _normalize_dt(dt)
    return local.date() in HOLIDAY_OVERRIDES


def is_market_day(dt: datetime | None = None) -> bool:
    local = _normalize_dt(dt)
    if local.weekday() not in TRADING_DAYS:
        return False
    if is_market_holiday(local):
        return False
    return True


def next_trading_day(dt: datetime | None = None) -> date:
    local = _normalize_dt(dt)
    cursor = local.date()
    while True:
        cursor = cursor + timedelta(days=1)
        probe = datetime.combine(cursor, MARKET_OPEN, tzinfo=IST)
        if is_market_day(probe):
            return cursor


def is_pre_open_window(dt: datetime | None = None) -> bool:
    local = _normalize_dt(dt)
    if not is_market_day(local):
        return False
    current_time = local.time()
    return PRE_MARKET_OPEN <= current_time <= PRE_MARKET_CLOSE


def is_market_open(dt: datetime | None = None) -> bool:
    """Check if market is currently open.

    Args:
        dt: Datetime to check (defaults to now in IST)

    Returns:
        True if market is open, False otherwise
    """
    dt = _normalize_dt(dt)

    # Check if it's a trading day (Mon-Fri)
    if not is_market_day(dt):
        return False

    # Check if time is within market hours
    current_time = dt.time()
    return MARKET_OPEN <= current_time <= MARKET_CLOSE


def is_us_market_day(dt: datetime | None = None) -> bool:
    """Return True when `dt` falls on a US weekday (Mon-Fri)."""
    if dt is None:
        probe = datetime.now(US_EASTERN)
    elif dt.tzinfo is None:
        probe = dt.replace(tzinfo=US_EASTERN)
    else:
        probe = dt.astimezone(US_EASTERN)
    return probe.weekday() in TRADING_DAYS


def is_us_market_open(dt: datetime | None = None) -> bool:
    """Check if US regular trading session is open (Eastern Time)."""
    if dt is None:
        probe = datetime.now(US_EASTERN)
    elif dt.tzinfo is None:
        probe = dt.replace(tzinfo=US_EASTERN)
    else:
        probe = dt.astimezone(US_EASTERN)
    if not is_us_market_day(probe):
        return False
    current_time = probe.time()
    return US_MARKET_OPEN <= current_time <= US_MARKET_CLOSE
