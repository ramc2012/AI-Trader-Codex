"""Tests for the fractal market profile engine."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from src.analysis.fractal_profile import (
    OptionFlowSummary,
    build_daily_fractal_context,
    build_hourly_profiles,
    compute_profile_window,
    market_session_start,
)


@dataclass
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


def _make_three_minute_candles(
    start: datetime,
    periods: int,
    base_price: float,
    step: float,
) -> list[Candle]:
    candles: list[Candle] = []
    price = base_price
    for idx in range(periods):
        ts = start + timedelta(minutes=idx * 3)
        open_price = price
        close_price = price + step
        high = max(open_price, close_price) + 2.0
        low = min(open_price, close_price) - 1.0
        candles.append(
            Candle(
                timestamp=ts,
                open=open_price,
                high=high,
                low=low,
                close=close_price,
                volume=10_000 + idx * 250,
            )
        )
        price = close_price
    return candles


def test_compute_profile_window_builds_hourly_profile() -> None:
    start = datetime(2026, 3, 5, 9, 15)
    candles = _make_three_minute_candles(start, periods=20, base_price=24000.0, step=4.0)

    profile = compute_profile_window(
        candles=candles,
        market="NSE",
        window_start=start,
        window_end=start + timedelta(hours=1),
        period_minutes=3,
        ib_periods=2,
        tick_size=2.0,
        period_prefix="h1_",
    )

    assert profile is not None
    assert profile.poc >= profile.low
    assert profile.poc <= profile.high
    assert profile.val <= profile.poc <= profile.vah
    assert profile.shape in {"P", "D", "elongated_up"}
    assert profile.period_count == 20
    assert len(profile.levels) > 0


def test_build_hourly_profiles_tracks_value_migration() -> None:
    start = datetime(2026, 3, 5, 9, 15)
    candles = _make_three_minute_candles(start, periods=40, base_price=24000.0, step=5.0)

    profiles = build_hourly_profiles(
        candles=candles,
        market="NSE",
        session_start=start,
        session_end=datetime(2026, 3, 5, 11, 15),
        tick_size=2.0,
    )

    assert len(profiles) == 2
    assert profiles[1].va_migration_vs_prev in {"up", "gap_up"}
    assert profiles[1].poc_change_vs_prev > 0
    assert profiles[1].va_overlap_ratio >= 0.0


def test_build_daily_context_emits_bullish_candidate() -> None:
    current_start = datetime(2026, 3, 5, 9, 15)
    prev_start = datetime(2026, 3, 4, 9, 15)
    current_day = _make_three_minute_candles(current_start, periods=40, base_price=24000.0, step=5.0)
    prev_day = _make_three_minute_candles(prev_start, periods=40, base_price=23750.0, step=1.5)

    context = build_daily_fractal_context(
        symbol="NSE:NIFTY50-INDEX",
        market="NSE",
        session_date=current_start,
        current_day_candles=current_day,
        prev_day_candles=prev_day,
        orderflow_summary={
            "delta_trend": "up",
            "latest_delta": 2500,
            "avg_buying_pressure": 0.58,
            "imbalance_ratio": 0.26,
        },
        option_flow=OptionFlowSummary(
            snapshot_time="2026-03-05T10:30:00",
            nearest_expiry="2026-03-06",
            dominant_side="CE",
            call_oi_change=150000,
            put_oi_change=95000,
            avg_call_iv=0.19,
            avg_put_iv=0.21,
            supportive=True,
            suggested_contract="NIFTY 24200 CE",
            suggested_delta=0.37,
        ),
    )

    assert context is not None
    assert context.candidate is not None
    assert context.assessment is not None
    assert context.candidate.direction == "bullish"
    assert context.candidate.consecutive_migration_hours >= 1
    assert context.candidate.conviction >= 50
    assert context.candidate.setup_type in {"acceptance_trend", "gap_and_go", "breakout_drive"}
    assert context.candidate.position_size_multiplier >= 0.6
    assert context.candidate.adaptive_risk_reward >= 1.2
    assert context.assessment.bias == "bullish"


def test_us_session_start_respects_dst_boundaries() -> None:
    winter = market_session_start(
        datetime(2026, 1, 15, 0, 0),
        "US",
        [Candle(datetime(2026, 1, 15, 20, 0), 100, 101, 99, 100, 1000)],
    )
    summer = market_session_start(
        datetime(2026, 7, 1, 0, 0),
        "US",
        [Candle(datetime(2026, 7, 1, 19, 0), 100, 101, 99, 100, 1000)],
    )

    assert winter.hour == 20 and winter.minute == 0
    assert summer.hour == 19 and summer.minute == 0
