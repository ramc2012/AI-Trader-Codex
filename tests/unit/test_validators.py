"""Tests for data validation utilities."""

import pytest

from src.utils.exceptions import DataValidationError
from src.utils.validators import validate_ohlc, validate_volume


class TestValidateOHLC:
    def test_valid_ohlc(self) -> None:
        validate_ohlc(open_=100.0, high=110.0, low=95.0, close=105.0)

    def test_high_equals_low(self) -> None:
        validate_ohlc(open_=100.0, high=100.0, low=100.0, close=100.0)

    def test_negative_price(self) -> None:
        with pytest.raises(DataValidationError, match="positive"):
            validate_ohlc(open_=-1.0, high=110.0, low=95.0, close=105.0)

    def test_high_less_than_low(self) -> None:
        with pytest.raises(DataValidationError, match="High.*less than Low"):
            validate_ohlc(open_=100.0, high=90.0, low=95.0, close=92.0)

    def test_high_less_than_open(self) -> None:
        with pytest.raises(DataValidationError, match="High.*must be >= Open"):
            validate_ohlc(open_=100.0, high=99.0, low=95.0, close=98.0)

    def test_low_greater_than_close(self) -> None:
        with pytest.raises(DataValidationError, match="Low.*must be <= Open"):
            validate_ohlc(open_=100.0, high=110.0, low=105.0, close=102.0)


class TestValidateVolume:
    def test_valid_volume(self) -> None:
        validate_volume(100)

    def test_zero_volume(self) -> None:
        validate_volume(0)

    def test_negative_volume(self) -> None:
        with pytest.raises(DataValidationError, match="negative"):
            validate_volume(-1)
