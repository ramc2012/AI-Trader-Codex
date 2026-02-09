"""General-purpose helper functions."""

from datetime import datetime
from zoneinfo import ZoneInfo

from src.config.market_hours import IST, MARKET_CLOSE, MARKET_OPEN, TRADING_DAYS


def now_ist() -> datetime:
    """Return the current datetime in IST."""
    return datetime.now(tz=IST)


def is_market_open(dt: datetime | None = None) -> bool:
    """Check if the Indian equity market is currently open.

    Args:
        dt: Datetime to check. Defaults to now (IST).

    Returns:
        True if the market is open at the given time.
    """
    if dt is None:
        dt = now_ist()
    else:
        dt = dt.astimezone(IST)

    if dt.weekday() not in TRADING_DAYS:
        return False

    current_time = dt.time()
    return MARKET_OPEN <= current_time <= MARKET_CLOSE


def epoch_to_ist(epoch: int) -> datetime:
    """Convert a Unix epoch timestamp to IST datetime.

    Args:
        epoch: Unix timestamp in seconds.

    Returns:
        Timezone-aware datetime in IST.
    """
    return datetime.fromtimestamp(epoch, tz=IST)


def ist_to_epoch(dt: datetime) -> int:
    """Convert an IST datetime to Unix epoch seconds.

    Args:
        dt: Datetime (timezone-aware or naive, assumed IST if naive).

    Returns:
        Unix timestamp in seconds.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return int(dt.timestamp())
