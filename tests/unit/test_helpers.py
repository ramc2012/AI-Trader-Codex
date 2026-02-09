"""Tests for helper utilities."""

from datetime import datetime
from zoneinfo import ZoneInfo

from src.config.market_hours import IST
from src.utils.helpers import epoch_to_ist, is_market_open, ist_to_epoch


class TestIsMarketOpen:
    def test_market_open_midday(self) -> None:
        # Wednesday 12:00 IST
        dt = datetime(2024, 2, 7, 12, 0, tzinfo=IST)
        assert is_market_open(dt) is True

    def test_market_closed_weekend(self) -> None:
        # Saturday 12:00 IST
        dt = datetime(2024, 2, 10, 12, 0, tzinfo=IST)
        assert is_market_open(dt) is False

    def test_market_closed_early_morning(self) -> None:
        # Wednesday 8:00 IST (before 9:15)
        dt = datetime(2024, 2, 7, 8, 0, tzinfo=IST)
        assert is_market_open(dt) is False

    def test_market_closed_after_hours(self) -> None:
        # Wednesday 16:00 IST (after 15:30)
        dt = datetime(2024, 2, 7, 16, 0, tzinfo=IST)
        assert is_market_open(dt) is False

    def test_market_open_at_open_time(self) -> None:
        dt = datetime(2024, 2, 7, 9, 15, tzinfo=IST)
        assert is_market_open(dt) is True

    def test_market_open_at_close_time(self) -> None:
        dt = datetime(2024, 2, 7, 15, 30, tzinfo=IST)
        assert is_market_open(dt) is True


class TestEpochConversions:
    def test_epoch_to_ist(self) -> None:
        # 2024-02-08 12:00:00 IST = 2024-02-08 06:30:00 UTC
        epoch = 1707375000
        dt = epoch_to_ist(epoch)
        assert dt.tzinfo is not None
        assert dt.tzname() == "IST"

    def test_roundtrip(self) -> None:
        dt = datetime(2024, 2, 8, 12, 0, 0, tzinfo=IST)
        epoch = ist_to_epoch(dt)
        back = epoch_to_ist(epoch)
        assert back.year == dt.year
        assert back.month == dt.month
        assert back.day == dt.day
        assert back.hour == dt.hour
