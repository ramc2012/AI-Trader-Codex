from __future__ import annotations

from src.utils.us_market_data import parse_nasdaq_chart_timestamp, parse_nasdaq_historical_date


def test_parse_nasdaq_chart_timestamp_uses_timeasof_session_date() -> None:
    ts = parse_nasdaq_chart_timestamp(
        {
            "x": 1773052140000,
            "y": 663.9893,
            "z": {"dateTime": "10:29 AM ET", "value": "663.9893"},
        },
        time_as_of="Mar 9, 2026 10:30 AM ET",
    )
    assert ts is not None
    assert ts.isoformat() == "2026-03-09T19:59:00+05:30"


def test_parse_nasdaq_historical_date_converts_from_us_eastern() -> None:
    ts = parse_nasdaq_historical_date("03/09/2026")
    assert ts is not None
    assert ts.isoformat() == "2026-03-09T09:30:00+05:30"
