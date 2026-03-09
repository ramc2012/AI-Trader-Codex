"""NSE option expiry date calculations and option symbol builders.

Handles the 2026 NSE expiry rules:
- NIFTY: Weekly on Tuesday
- BANKNIFTY: Monthly on last Tuesday
- FINNIFTY: Monthly on last Tuesday
- MIDCPNIFTY: Monthly on last Tuesday
- SENSEX: Weekly on Thursday (BSE)
- BANKEX: Monthly (BSE)
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from typing import Literal

from src.config.market_hours import IST
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ── Day constants ─────────────────────────────────────────────────────────
MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY = range(5)

# ── Expiry day mapping per index ──────────────────────────────────────────
# True = weekly expiry; False = monthly (last day-of-week)
EXPIRY_CONFIG: dict[str, dict] = {
    "NIFTY": {"day": TUESDAY, "weekly": True},
    "BANKNIFTY": {"day": TUESDAY, "weekly": False},  # Monthly last Tuesday
    "FINNIFTY": {"day": TUESDAY, "weekly": False},
    "MIDCPNIFTY": {"day": TUESDAY, "weekly": False},
    "SENSEX": {"day": THURSDAY, "weekly": True},  # BSE
    "BANKEX": {"day": THURSDAY, "weekly": False},  # BSE
}

# For equity stocks: monthly last Thursday (legacy)
EQUITY_EXPIRY_DAY = THURSDAY

# Month code mapping for Fyers symbol format
MONTH_CODES = {
    1: "JAN", 2: "FEB", 3: "MAR", 4: "APR",
    5: "MAY", 6: "JUN", 7: "JUL", 8: "AUG",
    9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC",
}

# ── Holiday list (major NSE holidays — extend as needed) ──────────────────
NSE_HOLIDAYS_2026: set[date] = {
    date(2026, 1, 26),  # Republic Day
    date(2026, 3, 10),  # Maha Shivaratri
    date(2026, 3, 17),  # Holi
    date(2026, 3, 30),  # Id-ul-Fitr
    date(2026, 4, 2),   # Ram Navami
    date(2026, 4, 3),   # Good Friday
    date(2026, 4, 14),  # Dr Ambedkar Jayanti
    date(2026, 5, 1),   # May Day
    date(2026, 6, 5),   # Eid-ul-Adha
    date(2026, 8, 15),  # Independence Day
    date(2026, 8, 18),  # Muharram
    date(2026, 10, 2),  # Gandhi Jayanti
    date(2026, 10, 20), # Diwali (Laxmi Pujan)
    date(2026, 10, 21), # Diwali (Balipratipada)
    date(2026, 11, 5),  # Guru Nanak Jayanti
    date(2026, 12, 25), # Christmas
}


def is_trading_day(d: date) -> bool:
    """Check if a date is a trading day (weekday and not holiday)."""
    return d.weekday() < 5 and d not in NSE_HOLIDAYS_2026


def _next_weekday(d: date, weekday: int) -> date:
    """Get the next occurrence of a specific weekday on or after date d."""
    days_ahead = weekday - d.weekday()
    if days_ahead < 0:
        days_ahead += 7
    return d + timedelta(days=days_ahead)


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    """Get the last occurrence of a specific weekday in a month."""
    last_day = calendar.monthrange(year, month)[1]
    d = date(year, month, last_day)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d


def _adjust_for_holiday(d: date) -> date:
    """If expiry falls on a holiday, move to previous trading day."""
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


# ── Public expiry functions ───────────────────────────────────────────────


def get_next_weekly_expiry(
    from_date: date | None = None,
    weekday: int = TUESDAY,
) -> date:
    """Get the next weekly expiry date.

    Args:
        from_date: Reference date (defaults to today IST).
        weekday: Day of week for expiry (0=Mon, 1=Tue, ...).

    Returns:
        Next expiry date (adjusted for holidays).
    """
    if from_date is None:
        from_date = datetime.now(tz=IST).date()

    candidate = _next_weekday(from_date, weekday)
    # If today IS the expiry day, use it (before market close)
    if from_date.weekday() == weekday and is_trading_day(from_date):
        candidate = from_date

    return _adjust_for_holiday(candidate)


def get_next_monthly_expiry(
    from_date: date | None = None,
    weekday: int = TUESDAY,
) -> date:
    """Get the next monthly expiry (last weekday of month).

    Args:
        from_date: Reference date.
        weekday: Day of week (0=Mon, 1=Tue, ...).

    Returns:
        Next monthly expiry date.
    """
    if from_date is None:
        from_date = datetime.now(tz=IST).date()

    candidate = _last_weekday_of_month(from_date.year, from_date.month, weekday)

    if candidate < from_date:
        # Move to next month
        if from_date.month == 12:
            candidate = _last_weekday_of_month(from_date.year + 1, 1, weekday)
        else:
            candidate = _last_weekday_of_month(from_date.year, from_date.month + 1, weekday)

    return _adjust_for_holiday(candidate)


def get_expiry_for_symbol(
    symbol: str,
    from_date: date | None = None,
) -> date:
    """Get the next expiry date for any index/equity symbol.

    Args:
        symbol: Underlying symbol (e.g. 'NIFTY', 'SBIN').
        from_date: Reference date.

    Returns:
        Next expiry date.
    """
    config = EXPIRY_CONFIG.get(symbol.upper())
    if config:
        if config["weekly"]:
            return get_next_weekly_expiry(from_date, config["day"])
        return get_next_monthly_expiry(from_date, config["day"])

    # Equity stocks: monthly last Thursday
    return get_next_monthly_expiry(from_date, EQUITY_EXPIRY_DAY)


def get_upcoming_expiries(
    symbol: str,
    count: int = 5,
    from_date: date | None = None,
) -> list[date]:
    """Get multiple upcoming expiry dates for a symbol.

    Args:
        symbol: Underlying symbol.
        count: Number of expiries to return.
        from_date: Starting reference date.

    Returns:
        List of expiry dates in ascending order.
    """
    if from_date is None:
        from_date = datetime.now(tz=IST).date()

    expiries: list[date] = []
    current = from_date

    for _ in range(count * 2):  # Over-fetch to account for dedup
        exp = get_expiry_for_symbol(symbol, current)
        if exp not in expiries:
            expiries.append(exp)
        if len(expiries) >= count:
            break
        current = exp + timedelta(days=1)

    return expiries[:count]


# ── ATM Strike calculation ────────────────────────────────────────────────


def get_atm_strike(spot_price: float, strike_interval: float) -> float:
    """Round spot price to nearest ATM strike.

    Args:
        spot_price: Current underlying price.
        strike_interval: Strike step (e.g. 50 for NIFTY).

    Returns:
        ATM strike price.
    """
    return round(spot_price / strike_interval) * strike_interval


def get_strike_range(
    spot_price: float,
    strike_interval: float,
    num_strikes: int = 10,
) -> list[float]:
    """Get a range of strikes around ATM.

    Args:
        spot_price: Current price.
        strike_interval: Strike step.
        num_strikes: Number of strikes on each side of ATM.

    Returns:
        List of strike prices (ITM to OTM) in ascending order.
    """
    atm = get_atm_strike(spot_price, strike_interval)
    return [atm + i * strike_interval for i in range(-num_strikes, num_strikes + 1)]


# ── Option symbol builders ────────────────────────────────────────────────


def build_option_symbol(
    underlying: str,
    expiry: date,
    strike: float,
    option_type: Literal["CE", "PE"],
    exchange: str = "NSE",
) -> str:
    """Build Fyers-format option symbol.

    Weekly format:  NSE:NIFTY2560326000CE  (YYMDD)
    Monthly format: NSE:NIFTY26JAN26000CE  (YYMMM)

    Args:
        underlying: e.g. 'NIFTY', 'SBIN'
        expiry: Expiry date
        strike: Strike price
        option_type: 'CE' or 'PE'
        exchange: 'NSE' or 'BSE'

    Returns:
        Full Fyers symbol string.
    """
    yy = expiry.strftime("%y")
    month_code = MONTH_CODES[expiry.month]
    strike_str = str(int(strike)) if strike == int(strike) else f"{strike:.1f}"

    # Check if this is a monthly expiry
    config = EXPIRY_CONFIG.get(underlying.upper())
    if config:
        weekday = config["day"]
        last_day = _last_weekday_of_month(expiry.year, expiry.month, weekday)
        is_monthly = _adjust_for_holiday(last_day) == expiry
    else:
        # Equity — always monthly
        is_monthly = True

    if is_monthly:
        # Monthly format: YYMMMSTRIKETYPE (e.g. 26JAN26000CE)
        date_part = f"{yy}{month_code}"
    else:
        # Weekly format: YYMMDDSTRIKETYPE (e.g. 2603126000CE)
        date_part = expiry.strftime("%y%m%d")

    return f"{exchange}:{underlying}{date_part}{strike_str}{option_type}"


def build_futures_symbol(
    underlying: str,
    expiry: date,
    exchange: str = "NSE",
) -> str:
    """Build Fyers-format futures symbol.

    Format: NSE:SBIN26JANFUT

    Args:
        underlying: e.g. 'NIFTY', 'SBIN'
        expiry: Expiry date
        exchange: Exchange prefix

    Returns:
        Full Fyers futures symbol.
    """
    yy = expiry.strftime("%y")
    month_code = MONTH_CODES[expiry.month]
    return f"{exchange}:{underlying}{yy}{month_code}FUT"


def days_to_expiry(expiry: date, from_date: date | None = None) -> int:
    """Calculate trading days until expiry.

    Args:
        expiry: Expiry date.
        from_date: Reference date (defaults to today IST).

    Returns:
        Number of trading days remaining.
    """
    if from_date is None:
        from_date = datetime.now(tz=IST).date()

    count = 0
    current = from_date
    while current < expiry:
        current += timedelta(days=1)
        if is_trading_day(current):
            count += 1
    return count
