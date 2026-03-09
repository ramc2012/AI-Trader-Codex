"""Fractal Market Profile engine.

Builds nested profile structures:
- Daily profiles from 30-minute TPO periods
- Hourly profiles from 3-minute TPO periods

The intent is to expose intraday profile evolution, value migration,
and actionable directional candidates for option-style trading.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal, Optional

from src.config.market_hours import IST, US_EASTERN

ProfileShape = Literal["P", "b", "D", "elongated_up", "elongated_down"]
MigrationType = Literal["up", "down", "overlapping", "gap_up", "gap_down", "flat", "none"]
DirectionType = Literal["bullish", "bearish"]
BiasType = Literal["bullish", "bearish", "neutral"]
AcceptanceType = Literal["accepted", "fast", "balanced", "mixed"]
SetupType = Literal["acceptance_trend", "gap_and_go", "breakout_drive", "balance", "exhaustion_watch"]

_IST_OFFSET = timedelta(hours=5, minutes=30)


@dataclass(frozen=True)
class ProfileLevel:
    price: float
    tpo_count: int
    periods: list[str] = field(default_factory=list)
    volume: int = 0
    single_print: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "price": round(float(self.price), 4),
            "tpo_count": int(self.tpo_count),
            "periods": list(self.periods),
            "volume": int(self.volume),
            "single_print": bool(self.single_print),
        }


@dataclass(frozen=True)
class ProfileWindow:
    start: datetime
    end: datetime
    open_price: float
    close_price: float
    high: float
    low: float
    poc: float
    vah: float
    val: float
    ib_high: float
    ib_low: float
    ib_broken_above: bool
    ib_broken_below: bool
    shape: ProfileShape
    levels: list[ProfileLevel] = field(default_factory=list)
    single_prints: list[tuple[float, float]] = field(default_factory=list)
    va_width_pct: float = 0.0
    poc_position: float = 0.5
    tpo_count_above_poc: int = 0
    tpo_count_below_poc: int = 0
    period_count: int = 0
    tick_size: float = 0.05

    @property
    def range_points(self) -> float:
        return float(self.high) - float(self.low)

    @property
    def ib_range(self) -> float:
        return float(self.ib_high) - float(self.ib_low)

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "open": round(float(self.open_price), 4),
            "close": round(float(self.close_price), 4),
            "high": round(float(self.high), 4),
            "low": round(float(self.low), 4),
            "poc": round(float(self.poc), 4),
            "vah": round(float(self.vah), 4),
            "val": round(float(self.val), 4),
            "ib_high": round(float(self.ib_high), 4),
            "ib_low": round(float(self.ib_low), 4),
            "ib_range": round(float(self.ib_range), 4),
            "ib_broken_above": bool(self.ib_broken_above),
            "ib_broken_below": bool(self.ib_broken_below),
            "shape": self.shape,
            "single_prints": [
                [round(float(start), 4), round(float(end), 4)]
                for start, end in self.single_prints
            ],
            "va_width_pct": round(float(self.va_width_pct), 4),
            "poc_position": round(float(self.poc_position), 4),
            "tpo_count_above_poc": int(self.tpo_count_above_poc),
            "tpo_count_below_poc": int(self.tpo_count_below_poc),
            "period_count": int(self.period_count),
            "tick_size": round(float(self.tick_size), 4),
            "levels": [level.to_dict() for level in self.levels],
        }


@dataclass(frozen=True)
class HourlyProfile(ProfileWindow):
    va_migration_vs_prev: MigrationType = "none"
    poc_change_vs_prev: float = 0.0
    consecutive_direction_hours: int = 0
    va_overlap_ratio: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload.update(
            {
                "va_migration_vs_prev": self.va_migration_vs_prev,
                "poc_change_vs_prev": round(float(self.poc_change_vs_prev), 4),
                "consecutive_direction_hours": int(self.consecutive_direction_hours),
                "va_overlap_ratio": round(float(self.va_overlap_ratio), 4),
            }
        )
        return payload


@dataclass(frozen=True)
class OptionFlowSummary:
    snapshot_time: Optional[str]
    nearest_expiry: Optional[str]
    dominant_side: str
    call_oi_change: float
    put_oi_change: float
    avg_call_iv: float
    avg_put_iv: float
    supportive: bool
    suggested_contract: Optional[str]
    suggested_delta: Optional[float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_time": self.snapshot_time,
            "nearest_expiry": self.nearest_expiry,
            "dominant_side": self.dominant_side,
            "call_oi_change": round(float(self.call_oi_change), 2),
            "put_oi_change": round(float(self.put_oi_change), 2),
            "avg_call_iv": round(float(self.avg_call_iv), 4),
            "avg_put_iv": round(float(self.avg_put_iv), 4),
            "supportive": bool(self.supportive),
            "suggested_contract": self.suggested_contract,
            "suggested_delta": None if self.suggested_delta is None else round(float(self.suggested_delta), 4),
        }


@dataclass(frozen=True)
class TradeCandidate:
    symbol: str
    direction: DirectionType
    hourly_shape: str
    consecutive_migration_hours: int
    setup_type: SetupType
    value_acceptance: AcceptanceType
    daily_alignment: bool
    approaching_single_prints: bool
    oi_direction_confirmed: bool
    iv_behavior: Literal["supportive", "neutral", "adverse"]
    aggressive_flow_detected: bool
    entry_trigger: float
    stop_reference: float
    target_reference: Optional[float]
    suggested_contract: Optional[str]
    suggested_delta: Optional[float]
    conviction: int
    position_size_multiplier: float
    adaptive_risk_reward: float
    exhaustion_warning: bool
    rationale: str
    orderflow_summary: dict[str, Any] = field(default_factory=dict)
    option_flow: Optional[OptionFlowSummary] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "hourly_shape": self.hourly_shape,
            "consecutive_migration_hours": int(self.consecutive_migration_hours),
            "setup_type": self.setup_type,
            "value_acceptance": self.value_acceptance,
            "daily_alignment": bool(self.daily_alignment),
            "approaching_single_prints": bool(self.approaching_single_prints),
            "oi_direction_confirmed": bool(self.oi_direction_confirmed),
            "iv_behavior": self.iv_behavior,
            "aggressive_flow_detected": bool(self.aggressive_flow_detected),
            "entry_trigger": round(float(self.entry_trigger), 4),
            "stop_reference": round(float(self.stop_reference), 4),
            "target_reference": None if self.target_reference is None else round(float(self.target_reference), 4),
            "suggested_contract": self.suggested_contract,
            "suggested_delta": None if self.suggested_delta is None else round(float(self.suggested_delta), 4),
            "conviction": int(self.conviction),
            "position_size_multiplier": round(float(self.position_size_multiplier), 3),
            "adaptive_risk_reward": round(float(self.adaptive_risk_reward), 3),
            "exhaustion_warning": bool(self.exhaustion_warning),
            "rationale": self.rationale,
            "orderflow_summary": dict(self.orderflow_summary),
            "option_flow": None if self.option_flow is None else self.option_flow.to_dict(),
        }


@dataclass(frozen=True)
class FractalAssessment:
    bias: BiasType
    current_hour_shape: ProfileShape
    current_migration: MigrationType
    consecutive_direction_hours: int
    prior_directional_streak: int
    daily_shape: ProfileShape
    setup_type: SetupType
    value_acceptance: AcceptanceType
    no_trade_reasons: list[str] = field(default_factory=list)
    exhaustion_warning: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "bias": self.bias,
            "current_hour_shape": self.current_hour_shape,
            "current_migration": self.current_migration,
            "consecutive_direction_hours": int(self.consecutive_direction_hours),
            "prior_directional_streak": int(self.prior_directional_streak),
            "daily_shape": self.daily_shape,
            "setup_type": self.setup_type,
            "value_acceptance": self.value_acceptance,
            "no_trade_reasons": list(self.no_trade_reasons),
            "exhaustion_warning": bool(self.exhaustion_warning),
        }


@dataclass(frozen=True)
class DailyFractalContext:
    symbol: str
    market: str
    session_date: str
    daily_profile: ProfileWindow
    prev_day_profile: Optional[ProfileWindow]
    hourly_profiles: list[HourlyProfile] = field(default_factory=list)
    assessment: Optional[FractalAssessment] = None
    candidate: Optional[TradeCandidate] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "market": self.market,
            "session_date": self.session_date,
            "daily_profile": self.daily_profile.to_dict(),
            "prev_day_profile": None if self.prev_day_profile is None else self.prev_day_profile.to_dict(),
            "hourly_profiles": [profile.to_dict() for profile in self.hourly_profiles],
            "assessment": None if self.assessment is None else self.assessment.to_dict(),
            "candidate": None if self.candidate is None else self.candidate.to_dict(),
        }


def _candle_value(candle: Any, field: str, default: Any = None) -> Any:
    if isinstance(candle, dict):
        return candle.get(field, default)
    return getattr(candle, field, default)


def normalize_timestamp(value: Any, market: str) -> datetime:
    """Normalize mixed timestamp formats into IST-naive datetimes."""
    if isinstance(value, str):
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    elif isinstance(value, datetime):
        ts = value
    else:
        raise TypeError(f"Unsupported timestamp type: {type(value)!r}")

    if ts.tzinfo is not None:
        return ts.astimezone(IST).replace(tzinfo=None)

    if market == "NSE" and ts.hour < 6:
        return ts + _IST_OFFSET
    return ts


def market_session_start(session_date: datetime, market: str, candles: list[Any]) -> datetime:
    base = session_date.replace(second=0, microsecond=0)
    if market == "NSE":
        return base.replace(hour=9, minute=15)
    if market == "US":
        eastern_open = datetime.combine(base.date(), datetime.min.time(), tzinfo=US_EASTERN).replace(hour=9, minute=30)
        return eastern_open.astimezone(IST).replace(tzinfo=None)
    earliest = normalize_timestamp(_candle_value(candles[0], "timestamp"), market)
    return earliest.replace(minute=0, second=0, microsecond=0)


def market_session_end(session_start: datetime, market: str, candles: list[Any]) -> datetime:
    if market == "NSE":
        return session_start.replace(hour=15, minute=30)
    if market == "US":
        session_start_ist = session_start.replace(tzinfo=IST)
        eastern_day = session_start_ist.astimezone(US_EASTERN).date()
        eastern_close = datetime.combine(eastern_day, datetime.min.time(), tzinfo=US_EASTERN).replace(hour=16, minute=0)
        return eastern_close.astimezone(IST).replace(tzinfo=None)
    latest = normalize_timestamp(_candle_value(candles[-1], "timestamp"), market)
    return latest.replace(second=0, microsecond=0) + timedelta(minutes=1)


def infer_tick_size(candles: list[Any], market: str) -> float:
    if not candles:
        return 0.05 if market == "NSE" else 0.01

    closes = [
        float(_candle_value(c, "close", 0.0) or 0.0)
        for c in candles
        if float(_candle_value(c, "close", 0.0) or 0.0) > 0
    ]
    high = max(float(_candle_value(c, "high", 0.0) or 0.0) for c in candles)
    low = min(float(_candle_value(c, "low", 0.0) or 0.0) for c in candles)
    range_points = max(high - low, 0.0)
    reference_price = closes[len(closes) // 2] if closes else max((high + low) / 2.0, 1.0)

    if market == "NSE":
        floor_tick = 0.05
        estimated = max(range_points / 48.0, floor_tick)
        snapped = round(estimated / floor_tick) * floor_tick
        return round(max(snapped, floor_tick), 2)

    if market == "US":
        if reference_price >= 500:
            step = 0.10
        elif reference_price >= 100:
            step = 0.05
        else:
            step = 0.01
        estimated = max(range_points / 160.0, reference_price * 0.0002, step)
        snapped = round(estimated / step) * step
        return round(max(snapped, step), 4)

    if reference_price >= 10_000:
        step = 0.50
    elif reference_price >= 1_000:
        step = 0.05
    elif reference_price >= 100:
        step = 0.01
    elif reference_price >= 1:
        step = 0.001
    else:
        step = 0.0001
    estimated = max(range_points / 160.0, reference_price * 0.0002, step)
    snapped = round(estimated / step) * step
    precision = max(len(str(step).split(".")[1].rstrip("0")) if "." in str(step) else 0, 1)
    return round(max(snapped, step), precision)


def _snap_price(price: float, tick_size: float) -> float:
    return round(round(price / tick_size) * tick_size, 6)


def _period_label(index: int, prefix: str) -> str:
    return f"{prefix}{index + 1:02d}"


def _calculate_value_area(price_tpos: Counter[float], poc_price: float, value_area_pct: float) -> tuple[float, float]:
    total_tpos = sum(price_tpos.values())
    target = total_tpos * value_area_pct
    sorted_prices = sorted(price_tpos.keys())
    poc_idx = sorted_prices.index(poc_price)
    low_idx = poc_idx
    high_idx = poc_idx
    va_tpos = price_tpos[poc_price]

    while va_tpos < target:
        expand_up = price_tpos[sorted_prices[high_idx + 1]] if high_idx + 1 < len(sorted_prices) else 0
        expand_down = price_tpos[sorted_prices[low_idx - 1]] if low_idx - 1 >= 0 else 0
        if expand_up == 0 and expand_down == 0:
            break
        if expand_up >= expand_down and high_idx + 1 < len(sorted_prices):
            high_idx += 1
            va_tpos += price_tpos[sorted_prices[high_idx]]
        elif low_idx - 1 >= 0:
            low_idx -= 1
            va_tpos += price_tpos[sorted_prices[low_idx]]
        else:
            break

    return sorted_prices[high_idx], sorted_prices[low_idx]


def _classify_shape(
    price_tpos: Counter[float],
    poc: float,
    high: float,
    low: float,
    open_price: float,
    close_price: float,
    tick_size: float,
) -> ProfileShape:
    total_range = max(high - low, tick_size)
    poc_position = (poc - low) / total_range
    close_position = (close_price - low) / total_range
    directional_efficiency = abs(close_price - open_price) / total_range

    # Trend hours often still overlap enough to create a bulky POC.
    # Treat them as elongated when the session closes near an extreme
    # and net movement consumes most of the hour's range.
    if total_range >= tick_size * 8 and directional_efficiency >= 0.65:
        if close_position >= 0.72 and close_price >= open_price:
            return "elongated_up"
        if close_position <= 0.28 and close_price <= open_price:
            return "elongated_down"

    if poc_position >= 0.62:
        return "P"
    if poc_position <= 0.38:
        return "b"
    return "D"


def _single_print_ranges(levels: list[ProfileLevel], tick_size: float) -> list[tuple[float, float]]:
    singles = sorted(level.price for level in levels if level.tpo_count == 1)
    if not singles:
        return []

    out: list[tuple[float, float]] = []
    start = singles[0]
    prev = singles[0]
    tolerance = tick_size * 1.05
    for price in singles[1:]:
        if abs(price - prev - tick_size) <= tolerance:
            prev = price
            continue
        out.append((start, prev))
        start = prev = price
    out.append((start, prev))
    return out


def _va_overlap_ratio(prev_profile: ProfileWindow, profile: ProfileWindow) -> float:
    overlap_high = min(prev_profile.vah, profile.vah)
    overlap_low = max(prev_profile.val, profile.val)
    overlap = max(overlap_high - overlap_low, 0.0)
    base_width = max(
        min(prev_profile.vah - prev_profile.val, profile.vah - profile.val),
        min(profile.tick_size, prev_profile.tick_size),
    )
    return overlap / base_width if base_width > 0 else 0.0


def compute_profile_window(
    candles: list[Any],
    market: str,
    window_start: datetime,
    window_end: datetime,
    period_minutes: int,
    ib_periods: int,
    tick_size: Optional[float] = None,
    period_prefix: str = "",
    value_area_pct: float = 0.70,
) -> Optional[ProfileWindow]:
    """Compute one TPO profile window from raw intraday candles."""
    normalized: list[dict[str, Any]] = []
    for candle in candles:
        ts = normalize_timestamp(_candle_value(candle, "timestamp"), market)
        if ts < window_start or ts >= window_end:
            continue
        normalized.append(
            {
                "timestamp": ts,
                "open": float(_candle_value(candle, "open", 0.0) or 0.0),
                "high": float(_candle_value(candle, "high", 0.0) or 0.0),
                "low": float(_candle_value(candle, "low", 0.0) or 0.0),
                "close": float(_candle_value(candle, "close", 0.0) or 0.0),
                "volume": int(float(_candle_value(candle, "volume", 0) or 0)),
            }
        )

    if not normalized:
        return None

    normalized.sort(key=lambda row: row["timestamp"])
    bucket_seconds = period_minutes * 60
    buckets: dict[int, list[dict[str, Any]]] = {}
    for row in normalized:
        idx = int((row["timestamp"] - window_start).total_seconds() // bucket_seconds)
        if idx < 0:
            continue
        buckets.setdefault(idx, []).append(row)

    periods: list[dict[str, Any]] = []
    for idx in sorted(buckets.keys()):
        rows = buckets[idx]
        periods.append(
            {
                "index": idx,
                "label": _period_label(idx, period_prefix),
                "timestamp": rows[0]["timestamp"],
                "open": rows[0]["open"],
                "close": rows[-1]["close"],
                "high": max(row["high"] for row in rows),
                "low": min(row["low"] for row in rows),
                "volume": sum(row["volume"] for row in rows),
            }
        )

    if not periods:
        return None

    use_tick = tick_size or infer_tick_size(normalized, market)
    session_high = max(period["high"] for period in periods)
    session_low = min(period["low"] for period in periods)
    open_price = periods[0]["open"]
    close_price = periods[-1]["close"]

    price_tpos: Counter[float] = Counter()
    price_periods: dict[float, list[str]] = {}
    price_volume: Counter[float] = Counter()

    for period in periods:
        low_bin = _snap_price(period["low"], use_tick)
        high_bin = _snap_price(period["high"], use_tick)
        steps = max(int(round((high_bin - low_bin) / use_tick)), 0)
        price = low_bin
        for _ in range(steps + 1):
            snapped = _snap_price(price, use_tick)
            price_tpos[snapped] += 1
            price_periods.setdefault(snapped, []).append(str(period["label"]))
            price_volume[snapped] += int(period["volume"] / max(steps + 1, 1))
            price = _snap_price(price + use_tick, use_tick)

    if not price_tpos:
        return None

    poc = max(price_tpos.items(), key=lambda item: (item[1], -abs(item[0] - close_price)))[0]
    vah, val = _calculate_value_area(price_tpos, poc, value_area_pct=value_area_pct)

    ib_slice = periods[: max(ib_periods, 1)]
    ib_high = max(period["high"] for period in ib_slice)
    ib_low = min(period["low"] for period in ib_slice)
    later_periods = periods[max(ib_periods, 1) :]
    ib_broken_above = any(period["high"] > ib_high for period in later_periods)
    ib_broken_below = any(period["low"] < ib_low for period in later_periods)

    sorted_prices = sorted(price_tpos.keys())
    levels = [
        ProfileLevel(
            price=price,
            tpo_count=int(price_tpos[price]),
            periods=list(price_periods.get(price, [])),
            volume=int(price_volume[price]),
            single_print=price_tpos[price] == 1,
        )
        for price in sorted_prices
    ]
    single_prints = _single_print_ranges(levels, tick_size=use_tick)
    shape = _classify_shape(
        price_tpos=price_tpos,
        poc=poc,
        high=session_high,
        low=session_low,
        open_price=open_price,
        close_price=close_price,
        tick_size=use_tick,
    )
    range_points = max(session_high - session_low, use_tick)
    tpo_above = sum(count for price, count in price_tpos.items() if price > poc)
    tpo_below = sum(count for price, count in price_tpos.items() if price < poc)

    return ProfileWindow(
        start=window_start,
        end=window_end,
        open_price=open_price,
        close_price=close_price,
        high=session_high,
        low=session_low,
        poc=poc,
        vah=vah,
        val=val,
        ib_high=ib_high,
        ib_low=ib_low,
        ib_broken_above=ib_broken_above,
        ib_broken_below=ib_broken_below,
        shape=shape,
        levels=levels,
        single_prints=single_prints,
        va_width_pct=(vah - val) / range_points if range_points > 0 else 0.0,
        poc_position=(poc - session_low) / range_points if range_points > 0 else 0.5,
        tpo_count_above_poc=tpo_above,
        tpo_count_below_poc=tpo_below,
        period_count=len(periods),
        tick_size=use_tick,
    )


def _migration(prev_profile: ProfileWindow, profile: ProfileWindow, tick_size: float) -> MigrationType:
    tolerance = tick_size * 0.5
    vah_delta = profile.vah - prev_profile.vah
    val_delta = profile.val - prev_profile.val
    if abs(vah_delta) <= tolerance and abs(val_delta) <= tolerance:
        return "flat"
    if profile.val > prev_profile.vah + tolerance:
        return "gap_up"
    if profile.vah < prev_profile.val - tolerance:
        return "gap_down"
    if profile.vah >= prev_profile.vah + tolerance and profile.val >= prev_profile.val + tolerance:
        return "up"
    if profile.vah <= prev_profile.vah - tolerance and profile.val <= prev_profile.val - tolerance:
        return "down"
    return "overlapping"


def build_hourly_profiles(
    candles: list[Any],
    market: str,
    session_start: datetime,
    session_end: datetime,
    tick_size: Optional[float] = None,
) -> list[HourlyProfile]:
    if not candles:
        return []

    last_seen = max(normalize_timestamp(_candle_value(c, "timestamp"), market) for c in candles)
    hourly_profiles: list[HourlyProfile] = []
    current_start = session_start
    counter = 0

    while current_start < session_end and current_start <= last_seen:
        current_end = min(current_start + timedelta(hours=1), session_end)
        base_profile = compute_profile_window(
            candles=candles,
            market=market,
            window_start=current_start,
            window_end=current_end,
            period_minutes=3,
            ib_periods=2,
            tick_size=tick_size,
            period_prefix=f"h{counter + 1}_",
        )
        if base_profile is not None and base_profile.period_count >= 2:
            if not hourly_profiles:
                migration = "none"
                poc_change = 0.0
                consecutive = 1
            else:
                prev = hourly_profiles[-1]
                migration = _migration(prev, base_profile, tick_size=base_profile.tick_size)
                poc_change = base_profile.poc - prev.poc
                overlap_ratio = _va_overlap_ratio(prev, base_profile)
                if migration in {"up", "gap_up"} and prev.va_migration_vs_prev in {"up", "gap_up"}:
                    consecutive = prev.consecutive_direction_hours + 1
                elif migration in {"down", "gap_down"} and prev.va_migration_vs_prev in {"down", "gap_down"}:
                    consecutive = prev.consecutive_direction_hours + 1
                elif migration in {"up", "gap_up", "down", "gap_down"}:
                    consecutive = 1
                else:
                    consecutive = 0

            hourly_profiles.append(
                HourlyProfile(
                    **base_profile.__dict__,
                    va_migration_vs_prev=migration,
                    poc_change_vs_prev=poc_change,
                    consecutive_direction_hours=consecutive,
                    va_overlap_ratio=0.0 if not hourly_profiles else overlap_ratio,
                )
            )

        current_start = current_end
        counter += 1

    return hourly_profiles


def _single_print_target(
    price: float,
    direction: DirectionType,
    prev_day_profile: Optional[ProfileWindow],
) -> Optional[float]:
    if prev_day_profile is None or not prev_day_profile.single_prints:
        return None
    if direction == "bullish":
        above = [start for start, _ in prev_day_profile.single_prints if start > price]
        return min(above) if above else None
    below = [end for _, end in prev_day_profile.single_prints if end < price]
    return max(below) if below else None


def _daily_alignment(direction: DirectionType, current_hour: HourlyProfile, daily_profile: ProfileWindow) -> bool:
    if direction == "bullish":
        return (
            current_hour.close_price >= daily_profile.poc
            and (current_hour.high >= daily_profile.ib_high or current_hour.val >= daily_profile.poc)
        )
    return (
        current_hour.close_price <= daily_profile.poc
        and (current_hour.low <= daily_profile.ib_low or current_hour.vah <= daily_profile.poc)
    )


def _current_bias(current: HourlyProfile) -> BiasType:
    if current.shape == "elongated_up" and current.va_migration_vs_prev in {"up", "gap_up", "flat"}:
        return "bullish"
    if current.shape == "elongated_down" and current.va_migration_vs_prev in {"down", "gap_down", "flat"}:
        return "bearish"
    return "neutral"


def _directional_streak(hourly_profiles: list[HourlyProfile], direction: DirectionType) -> int:
    target_shape = "elongated_up" if direction == "bullish" else "elongated_down"
    target_migrations = {"up", "gap_up", "flat"} if direction == "bullish" else {"down", "gap_down", "flat"}
    streak = 0
    for profile in reversed(hourly_profiles):
        if profile.shape == target_shape and profile.va_migration_vs_prev in target_migrations:
            streak += 1
            continue
        break
    return streak


def _value_acceptance(current: HourlyProfile) -> AcceptanceType:
    if current.va_migration_vs_prev in {"gap_up", "gap_down"}:
        return "fast"
    if current.va_migration_vs_prev in {"overlapping", "flat", "none"}:
        return "balanced"
    if current.va_overlap_ratio >= 0.45:
        return "accepted"
    if current.va_overlap_ratio <= 0.15:
        return "fast"
    return "mixed"


def _is_oscillating(hourly_profiles: list[HourlyProfile]) -> bool:
    directions: list[int] = []
    for profile in hourly_profiles:
        if profile.va_migration_vs_prev in {"up", "gap_up"}:
            directions.append(1)
        elif profile.va_migration_vs_prev in {"down", "gap_down"}:
            directions.append(-1)
    if len(directions) < 4:
        return False
    tail = directions[-4:]
    changes = sum(1 for idx in range(1, len(tail)) if tail[idx] != tail[idx - 1])
    return changes >= 3


def _daily_ib_is_wide(daily_profile: ProfileWindow, hourly_profiles: list[HourlyProfile]) -> bool:
    reference = [profile.range_points for profile in hourly_profiles[:3] if profile.range_points > 0]
    if not reference:
        reference = [profile.range_points for profile in hourly_profiles if profile.range_points > 0]
    if not reference:
        return False
    avg_hour_range = sum(reference) / len(reference)
    return daily_profile.ib_range > (avg_hour_range * 1.5)


def _is_ledge(profile: HourlyProfile) -> bool:
    if profile.period_count < 8:
        return False
    if profile.va_width_pct > 0.18:
        return False
    if not profile.levels:
        return False
    concentration = max(level.tpo_count for level in profile.levels) / max(profile.period_count, 1)
    return concentration >= 0.35


def assess_trade_setup(
    daily_profile: ProfileWindow,
    hourly_profiles: list[HourlyProfile],
) -> Optional[FractalAssessment]:
    if not hourly_profiles:
        return None

    current = hourly_profiles[-1]
    bias = _current_bias(current)
    prior_bullish = _directional_streak(hourly_profiles[:-1], "bullish")
    prior_bearish = _directional_streak(hourly_profiles[:-1], "bearish")
    exhaustion_warning = (prior_bullish >= 2 and current.shape == "P") or (
        prior_bearish >= 2 and current.shape == "b"
    )

    no_trade_reasons: list[str] = []
    if daily_profile.shape == "D" and current.shape == "D":
        no_trade_reasons.append("Daily and active hourly profiles are balanced.")
    if _is_oscillating(hourly_profiles):
        no_trade_reasons.append("Hourly value areas are oscillating instead of migrating cleanly.")
    if _daily_ib_is_wide(daily_profile, hourly_profiles):
        no_trade_reasons.append("Daily initial balance is already stretched relative to hourly range.")
    if _is_ledge(current):
        no_trade_reasons.append("Active hour is coiling in a ledge-like balance.")
    if exhaustion_warning:
        no_trade_reasons.append("Current hour is showing profile exhaustion after a directional run.")

    acceptance = _value_acceptance(current)
    if bias == "neutral":
        setup_type: SetupType = "exhaustion_watch" if exhaustion_warning else "balance"
    elif current.va_migration_vs_prev in {"gap_up", "gap_down"}:
        setup_type = "gap_and_go"
    elif acceptance == "accepted":
        setup_type = "acceptance_trend"
    else:
        setup_type = "breakout_drive"

    if bias == "neutral":
        prior_streak = max(prior_bullish, prior_bearish)
    else:
        prior_streak = prior_bullish if bias == "bullish" else prior_bearish

    return FractalAssessment(
        bias=bias,
        current_hour_shape=current.shape,
        current_migration=current.va_migration_vs_prev,
        consecutive_direction_hours=int(current.consecutive_direction_hours),
        prior_directional_streak=int(prior_streak),
        daily_shape=daily_profile.shape,
        setup_type=setup_type,
        value_acceptance=acceptance,
        no_trade_reasons=no_trade_reasons,
        exhaustion_warning=exhaustion_warning,
    )


def _candidate_size_multiplier(
    conviction: int,
    assessment: FractalAssessment,
    daily_ok: bool,
    aggressive_flow: bool,
    iv_behavior: Literal["supportive", "neutral", "adverse"],
) -> float:
    if conviction >= 84:
        size = 1.25
    elif conviction >= 74:
        size = 1.10
    elif conviction >= 66:
        size = 1.00
    else:
        size = 0.85

    if assessment.setup_type == "acceptance_trend":
        size += 0.05
    elif assessment.setup_type == "gap_and_go" and not aggressive_flow:
        size -= 0.10
    if not daily_ok:
        size -= 0.10
    if iv_behavior == "adverse":
        size -= 0.08
    if assessment.exhaustion_warning:
        size -= 0.12
    return max(0.60, min(round(size, 3), 1.35))


def _candidate_risk_reward(
    assessment: FractalAssessment,
    conviction: int,
    aggressive_flow: bool,
    iv_behavior: Literal["supportive", "neutral", "adverse"],
) -> float:
    if assessment.setup_type == "gap_and_go":
        rr = 2.1 if aggressive_flow else 1.7
    elif assessment.setup_type == "acceptance_trend":
        rr = 1.9
    elif assessment.setup_type == "breakout_drive":
        rr = 1.7
    else:
        rr = 1.4

    if conviction >= 82:
        rr += 0.1
    if iv_behavior == "adverse":
        rr -= 0.2
    if assessment.exhaustion_warning:
        rr -= 0.2
    return max(1.2, min(round(rr, 3), 2.4))


def build_trade_candidate(
    symbol: str,
    daily_profile: ProfileWindow,
    hourly_profiles: list[HourlyProfile],
    prev_day_profile: Optional[ProfileWindow],
    assessment: Optional[FractalAssessment] = None,
    orderflow_summary: Optional[dict[str, Any]] = None,
    option_flow: Optional[OptionFlowSummary] = None,
) -> Optional[TradeCandidate]:
    if not hourly_profiles:
        return None

    current = hourly_profiles[-1]
    setup = assessment or assess_trade_setup(daily_profile, hourly_profiles)
    if setup is None or setup.bias == "neutral" or setup.no_trade_reasons:
        return None
    direction: DirectionType = "bullish" if setup.bias == "bullish" else "bearish"

    daily_ok = _daily_alignment(direction, current, daily_profile)
    consecutive = max(current.consecutive_direction_hours, 1)
    target = _single_print_target(current.close_price, direction, prev_day_profile)
    approaching_single_prints = target is not None

    orderflow = dict(orderflow_summary or {})
    delta_trend = str(orderflow.get("delta_trend", "flat"))
    avg_pressure = float(orderflow.get("avg_buying_pressure", 0.5) or 0.5)
    latest_delta = float(orderflow.get("latest_delta", 0.0) or 0.0)
    imbalance_ratio = float(orderflow.get("imbalance_ratio", 0.0) or 0.0)

    if direction == "bullish":
        aggressive_flow = delta_trend == "up" and latest_delta > 0 and avg_pressure >= 0.53
    else:
        aggressive_flow = delta_trend == "down" and latest_delta < 0 and avg_pressure <= 0.47

    oi_confirmed = bool(option_flow.supportive) if option_flow is not None else False
    iv_behavior: Literal["supportive", "neutral", "adverse"] = "neutral"
    if option_flow is not None:
        if option_flow.supportive:
            iv_behavior = "supportive"
        elif (
            direction == "bullish" and option_flow.avg_call_iv > option_flow.avg_put_iv * 1.15
        ) or (
            direction == "bearish" and option_flow.avg_put_iv > option_flow.avg_call_iv * 1.15
        ):
            iv_behavior = "adverse"

    conviction = 35
    conviction += min(max(consecutive - 1, 0) * 12, 24)
    if daily_ok:
        conviction += 15
    if aggressive_flow:
        conviction += 12
    if approaching_single_prints:
        conviction += 8
    if oi_confirmed:
        conviction += 10
    if imbalance_ratio >= 0.22:
        conviction += 5
    if setup.value_acceptance == "accepted":
        conviction += 6
    elif setup.value_acceptance == "mixed":
        conviction += 2
    elif setup.value_acceptance == "fast" and not aggressive_flow:
        conviction -= 4
    if setup.setup_type == "acceptance_trend":
        conviction += 4
    elif setup.setup_type == "gap_and_go":
        conviction += 3
    if iv_behavior == "adverse":
        conviction -= 8
    if setup.exhaustion_warning:
        conviction -= 15
    conviction = max(0, min(int(round(conviction)), 100))
    size_multiplier = _candidate_size_multiplier(conviction, setup, daily_ok, aggressive_flow, iv_behavior)
    adaptive_risk_reward = _candidate_risk_reward(setup, conviction, aggressive_flow, iv_behavior)

    if direction == "bullish":
        entry_trigger = max(current.high, current.vah)
        stop_reference = min(current.val, current.ib_low)
    else:
        entry_trigger = min(current.low, current.val)
        stop_reference = max(current.vah, current.ib_high)

    rationale_bits = [
        f"{current.shape} hourly profile",
        f"{consecutive} consecutive migration hour(s)",
        f"{setup.setup_type.replace('_', ' ')} structure",
        f"value acceptance {setup.value_acceptance}",
        "daily aligned" if daily_ok else "daily mixed",
        "order-flow confirmed" if aggressive_flow else "order-flow mixed",
    ]
    if approaching_single_prints:
        rationale_bits.append("previous-day single prints in play")
    if oi_confirmed:
        rationale_bits.append("options flow supportive")

    return TradeCandidate(
        symbol=symbol,
        direction=direction,
        hourly_shape=current.shape,
        consecutive_migration_hours=consecutive,
        setup_type=setup.setup_type,
        value_acceptance=setup.value_acceptance,
        daily_alignment=daily_ok,
        approaching_single_prints=approaching_single_prints,
        oi_direction_confirmed=oi_confirmed,
        iv_behavior=iv_behavior,
        aggressive_flow_detected=aggressive_flow,
        entry_trigger=entry_trigger,
        stop_reference=stop_reference,
        target_reference=target,
        suggested_contract=option_flow.suggested_contract if option_flow is not None else None,
        suggested_delta=option_flow.suggested_delta if option_flow is not None else None,
        conviction=conviction,
        position_size_multiplier=size_multiplier,
        adaptive_risk_reward=adaptive_risk_reward,
        exhaustion_warning=setup.exhaustion_warning,
        rationale=", ".join(rationale_bits),
        orderflow_summary=orderflow,
        option_flow=option_flow,
    )


def build_daily_fractal_context(
    symbol: str,
    market: str,
    session_date: datetime,
    current_day_candles: list[Any],
    prev_day_candles: list[Any],
    orderflow_summary: Optional[dict[str, Any]] = None,
    option_flow: Optional[OptionFlowSummary] = None,
) -> Optional[DailyFractalContext]:
    if not current_day_candles:
        return None

    use_tick = infer_tick_size(current_day_candles + prev_day_candles, market)
    current_session_start = market_session_start(session_date, market, current_day_candles)
    current_session_end = market_session_end(current_session_start, market, current_day_candles)
    daily_profile = compute_profile_window(
        candles=current_day_candles,
        market=market,
        window_start=current_session_start,
        window_end=current_session_end,
        period_minutes=30,
        ib_periods=2,
        tick_size=use_tick,
        period_prefix="D_",
    )
    if daily_profile is None:
        return None

    prev_day_profile: Optional[ProfileWindow] = None
    if prev_day_candles:
        prev_session_date = normalize_timestamp(_candle_value(prev_day_candles[0], "timestamp"), market)
        prev_session_start = market_session_start(prev_session_date, market, prev_day_candles)
        prev_session_end = market_session_end(prev_session_start, market, prev_day_candles)
        prev_day_profile = compute_profile_window(
            candles=prev_day_candles,
            market=market,
            window_start=prev_session_start,
            window_end=prev_session_end,
            period_minutes=30,
            ib_periods=2,
            tick_size=use_tick,
            period_prefix="P_",
        )

    hourly_profiles = build_hourly_profiles(
        candles=current_day_candles,
        market=market,
        session_start=current_session_start,
        session_end=current_session_end,
        tick_size=use_tick,
    )
    assessment = assess_trade_setup(daily_profile, hourly_profiles)
    candidate = build_trade_candidate(
        symbol=symbol,
        daily_profile=daily_profile,
        hourly_profiles=hourly_profiles,
        prev_day_profile=prev_day_profile,
        assessment=assessment,
        orderflow_summary=orderflow_summary,
        option_flow=option_flow,
    )

    return DailyFractalContext(
        symbol=symbol,
        market=market,
        session_date=current_session_start.date().isoformat(),
        daily_profile=daily_profile,
        prev_day_profile=prev_day_profile,
        hourly_profiles=hourly_profiles,
        assessment=assessment,
        candidate=candidate,
    )
