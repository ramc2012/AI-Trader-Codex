from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any

from src.config.market_hours import IST, US_EASTERN


def parse_nasdaq_session_date(time_as_of: str | None) -> date:
    raw = str(time_as_of or "").strip()
    if raw:
        for fmt in ("%b %d, %Y %I:%M %p ET", "%b %d, %Y %H:%M ET"):
            try:
                parsed = datetime.strptime(raw, fmt)
                return parsed.date()
            except ValueError:
                continue
    return datetime.now(tz=US_EASTERN).date()


def parse_nasdaq_chart_timestamp(
    point: dict[str, Any],
    *,
    time_as_of: str | None = None,
) -> datetime | None:
    session_date = parse_nasdaq_session_date(time_as_of)
    z = point.get("z")
    label = z.get("dateTime") if isinstance(z, dict) else None
    if isinstance(label, str) and label.strip():
        parsed_time: time | None = None
        for fmt in ("%I:%M %p ET", "%H:%M ET"):
            try:
                parsed_time = datetime.strptime(label.strip(), fmt).time()
                break
            except ValueError:
                continue
        if parsed_time is not None:
            return datetime.combine(session_date, parsed_time, tzinfo=US_EASTERN).astimezone(IST)

    raw_epoch = point.get("x")
    try:
        return datetime.fromtimestamp(int(raw_epoch) / 1000.0, tz=timezone.utc).astimezone(IST)
    except (TypeError, ValueError, OSError):
        return None


def parse_nasdaq_historical_date(raw_date: Any) -> datetime | None:
    try:
        parsed = datetime.strptime(str(raw_date), "%m/%d/%Y").replace(tzinfo=US_EASTERN)
    except ValueError:
        return None
    return parsed.astimezone(IST)
