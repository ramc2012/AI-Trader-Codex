"""Data validation utilities for market data integrity."""

from decimal import Decimal

from src.utils.exceptions import DataValidationError


def validate_ohlc(
    open_: float | Decimal,
    high: float | Decimal,
    low: float | Decimal,
    close: float | Decimal,
) -> None:
    """Validate OHLC candle data for logical consistency.

    Args:
        open_: Opening price.
        high: Highest price.
        low: Lowest price.
        close: Closing price.

    Raises:
        DataValidationError: If any OHLC rule is violated.
    """
    if any(v <= 0 for v in (open_, high, low, close)):
        raise DataValidationError(f"Prices must be positive: O={open_} H={high} L={low} C={close}")
    if high < low:
        raise DataValidationError(f"High ({high}) cannot be less than Low ({low})")
    if high < open_ or high < close:
        raise DataValidationError(f"High ({high}) must be >= Open ({open_}) and Close ({close})")
    if low > open_ or low > close:
        raise DataValidationError(f"Low ({low}) must be <= Open ({open_}) and Close ({close})")


def validate_volume(volume: int) -> None:
    """Validate that volume is non-negative.

    Args:
        volume: Trade volume.

    Raises:
        DataValidationError: If volume is negative.
    """
    if volume < 0:
        raise DataValidationError(f"Volume cannot be negative: {volume}")
