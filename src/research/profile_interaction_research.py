"""Profile-interaction research from saved hourly candles.

Builds daily, week-to-date, and month-to-date market profiles from 1h candles,
derives auction-structure features, labels large 2-day moves, and mines
high-lift profile interactions for NSE and US stocks / indices.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from itertools import combinations
import json
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence
from zoneinfo import ZoneInfo

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score

from src.analysis.fractal_profile import (
    ProfileLevel,
    ProfileWindow,
    _calculate_value_area,
    _classify_shape,
    _migration,
    _single_print_ranges,
    _va_overlap_ratio,
    infer_tick_size,
)
from src.research.paths import resolve_report_dir
from src.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_REPORT_DIR = resolve_report_dir(
    None,
    folder_name="profile_interaction_research",
    legacy_fallback="tmp/profile_interaction_research",
)


def _default_input_dataset() -> str:
    candidates = [
        Path("tmp/hourly_large_move_full/labeled_dataset.csv.gz"),
        Path("tmp/hourly_large_move/labeled_dataset.csv.gz"),
        Path("data/research/hourly_large_move/labeled_dataset.csv.gz"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return str(candidates[0])


@dataclass(frozen=True)
class ProfileInteractionConfig:
    input_dataset: str = _default_input_dataset()
    report_dir: str = str(DEFAULT_REPORT_DIR)
    market: str = "ALL"
    horizon_days: int = 2
    stock_targets: tuple[float, ...] = (0.05, 0.10)
    index_target: float = 0.02
    min_daily_rows_per_symbol: int = 120
    min_condition_support: int = 100
    top_condition_count: int = 12
    max_stock_symbols_per_market: int = 0


@dataclass(frozen=True)
class ModelArtifacts:
    target_column: str
    label_column: str
    rows: int
    train_rows: int
    test_rows: int
    accuracy: float
    balanced_accuracy: float
    f1_macro: float
    class_distribution: dict[str, int]
    top_features: list[dict[str, Any]]
    model_path: str | None


def _market_timezone(market: str) -> ZoneInfo:
    return ZoneInfo("Asia/Kolkata") if market == "NSE" else ZoneInfo("America/New_York")


def _hours_per_session(market: str) -> int:
    if market == "NSE":
        return 7
    if market == "US":
        return 7
    return 6


def _load_hourly_history(config: ProfileInteractionConfig) -> pd.DataFrame:
    usecols = ["timestamp", "symbol", "market", "asset_type", "open", "high", "low", "close", "volume"]
    dataset_path = Path(config.input_dataset)
    if not dataset_path.exists():
        raise FileNotFoundError(f"Hourly dataset not found: {dataset_path}")

    frame = pd.read_csv(dataset_path, usecols=usecols)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "symbol", "market", "asset_type", "open", "high", "low", "close"])
    frame = frame.sort_values(["market", "symbol", "timestamp"]).reset_index(drop=True)

    market_key = str(config.market).strip().upper()
    if market_key in {"NSE", "US"}:
        frame = frame.loc[frame["market"].astype(str) == market_key].copy()

    if config.max_stock_symbols_per_market > 0:
        keep_symbols: set[str] = set()
        for market in sorted(frame["market"].astype(str).unique()):
            market_frame = frame.loc[frame["market"].astype(str) == market]
            stocks = sorted(market_frame.loc[market_frame["asset_type"].astype(str) == "stock", "symbol"].astype(str).unique())
            indices = sorted(market_frame.loc[market_frame["asset_type"].astype(str) == "index", "symbol"].astype(str).unique())
            keep_symbols.update(stocks[: int(config.max_stock_symbols_per_market)])
            keep_symbols.update(indices)
        frame = frame.loc[frame["symbol"].astype(str).isin(keep_symbols)].copy()

    if frame.empty:
        raise RuntimeError("No hourly history available after applying filters.")
    return frame


def _safe_class_distribution(labels: pd.Series) -> dict[str, int]:
    counts = labels.value_counts()
    return {str(key): int(value) for key, value in counts.items()}


def _build_profile_from_hourly_frame(
    frame: pd.DataFrame,
    *,
    market: str,
    ib_periods: int,
    tick_size: Optional[float] = None,
) -> Optional[ProfileWindow]:
    if frame.empty:
        return None

    ordered = frame.sort_values("local_timestamp").reset_index(drop=True)
    candles = ordered[["local_timestamp", "open", "high", "low", "close", "volume"]].to_dict("records")
    use_tick = tick_size or infer_tick_size(candles, market)
    session_high = float(ordered["high"].max())
    session_low = float(ordered["low"].min())
    open_price = float(ordered["open"].iloc[0])
    close_price = float(ordered["close"].iloc[-1])

    price_tpos: Counter[float] = Counter()
    price_periods: dict[float, list[str]] = {}
    price_volume: Counter[float] = Counter()

    for idx, row in enumerate(ordered.itertuples(index=False), start=1):
        low_bin = round(round(float(row.low) / use_tick) * use_tick, 6)
        high_bin = round(round(float(row.high) / use_tick) * use_tick, 6)
        steps = max(int(round((high_bin - low_bin) / use_tick)), 0)
        price = low_bin
        label = f"h{idx:02d}"
        for _ in range(steps + 1):
            snapped = round(round(price / use_tick) * use_tick, 6)
            price_tpos[snapped] += 1
            price_periods.setdefault(snapped, []).append(label)
            price_volume[snapped] += int(float(row.volume) / max(steps + 1, 1))
            price = round(price + use_tick, 6)

    if not price_tpos:
        return None

    sorted_prices = sorted(price_tpos.keys())
    poc = max(price_tpos.items(), key=lambda item: (item[1], -abs(item[0] - close_price)))[0]
    vah, val = _calculate_value_area(price_tpos, poc, value_area_pct=0.70)

    ib_slice = ordered.head(max(int(ib_periods), 1))
    ib_high = float(ib_slice["high"].max())
    ib_low = float(ib_slice["low"].min())
    later = ordered.iloc[max(int(ib_periods), 1) :]
    ib_broken_above = bool((later["high"] > ib_high).any()) if not later.empty else False
    ib_broken_below = bool((later["low"] < ib_low).any()) if not later.empty else False

    levels = [
        ProfileLevel(
            price=float(price),
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

    start = pd.Timestamp(ordered["local_timestamp"].iloc[0]).to_pydatetime()
    end = pd.Timestamp(ordered["local_timestamp"].iloc[-1]).to_pydatetime()
    return ProfileWindow(
        start=start,
        end=end,
        open_price=open_price,
        close_price=close_price,
        high=session_high,
        low=session_low,
        poc=float(poc),
        vah=float(vah),
        val=float(val),
        ib_high=ib_high,
        ib_low=ib_low,
        ib_broken_above=ib_broken_above,
        ib_broken_below=ib_broken_below,
        shape=shape,
        levels=levels,
        single_prints=single_prints,
        va_width_pct=(float(vah) - float(val)) / range_points if range_points > 0 else 0.0,
        poc_position=(float(poc) - session_low) / range_points if range_points > 0 else 0.5,
        tpo_count_above_poc=int(tpo_above),
        tpo_count_below_poc=int(tpo_below),
        period_count=int(len(ordered)),
        tick_size=float(use_tick),
    )


def _single_print_count(profile: ProfileWindow) -> int:
    return int(sum(1 for level in profile.levels if level.single_print))


def _single_print_width(profile: ProfileWindow) -> float:
    if not profile.single_prints:
        return 0.0
    return float(sum((end - start) + profile.tick_size for start, end in profile.single_prints))


def _tail_single_print_count(profile: ProfileWindow, side: str) -> int:
    levels = profile.levels if side == "low" else list(reversed(profile.levels))
    count = 0
    for level in levels:
        if level.single_print:
            count += 1
            continue
        break
    return count


def _incomplete_auction(profile: ProfileWindow, side: str) -> bool:
    if not profile.levels:
        return False
    level = profile.levels[0] if side == "low" else profile.levels[-1]
    return int(level.tpo_count) > 1


def _failed_auction(profile: ProfileWindow, prev_profile: Optional[ProfileWindow], side: str) -> bool:
    if prev_profile is None:
        return False
    tolerance = profile.tick_size * 0.5
    if side == "high":
        return bool(profile.high > (prev_profile.high + tolerance) and profile.close_price < (prev_profile.high - tolerance))
    return bool(profile.low < (prev_profile.low - tolerance) and profile.close_price > (prev_profile.low + tolerance))


def _profile_band_relation(inner: ProfileWindow, outer: ProfileWindow, tolerance: float) -> str:
    if inner.val > outer.vah + tolerance:
        return "above"
    if inner.vah < outer.val - tolerance:
        return "below"
    if inner.val >= outer.val - tolerance and inner.vah <= outer.vah + tolerance:
        return "inside"
    if inner.vah > outer.vah + tolerance and inner.val < outer.val - tolerance:
        return "outside"
    return "overlapping"


def _price_position(price: float, profile: ProfileWindow, tolerance: float) -> str:
    if price > profile.vah + tolerance:
        return "above_value"
    if price < profile.val - tolerance:
        return "below_value"
    if profile.val - tolerance <= price <= profile.vah + tolerance:
        return "inside_value"
    return "unknown"


def _price_vs_profile(price: float, profile: ProfileWindow) -> dict[str, float]:
    tick = max(float(profile.tick_size), 1e-6)
    return {
        "vs_poc_ticks": (price - profile.poc) / tick,
        "vs_vah_ticks": (price - profile.vah) / tick,
        "vs_val_ticks": (price - profile.val) / tick,
        "vs_ib_high_ticks": (price - profile.ib_high) / tick,
        "vs_ib_low_ticks": (price - profile.ib_low) / tick,
    }


def _daily_open_type(
    day_frame: pd.DataFrame,
    prev_profile: Optional[ProfileWindow],
    *,
    tolerance: float,
) -> str:
    if prev_profile is None or day_frame.empty:
        return "unknown"

    first = day_frame.sort_values("local_timestamp").iloc[0]
    open_price = float(first["open"])
    high = float(first["high"])
    low = float(first["low"])
    close = float(first["close"])
    range_points = max(high - low, tolerance * 2.0)
    close_position = (close - low) / range_points

    if open_price > prev_profile.high + tolerance and close < prev_profile.high - tolerance:
        return "rejection_down"
    if open_price < prev_profile.low - tolerance and close > prev_profile.low + tolerance:
        return "rejection_up"
    if low >= open_price - tolerance and close_position >= 0.70:
        return "drive_up"
    if high <= open_price + tolerance and close_position <= 0.30:
        return "drive_down"
    if open_price > prev_profile.high + tolerance:
        return "above_prev_range"
    if open_price < prev_profile.low - tolerance:
        return "below_prev_range"
    if open_price > prev_profile.vah + tolerance:
        return "above_prev_value"
    if open_price < prev_profile.val - tolerance:
        return "below_prev_value"
    return "in_prev_value"


def _ib_break_state(profile: ProfileWindow) -> str:
    if profile.ib_broken_above and profile.ib_broken_below:
        return "both"
    if profile.ib_broken_above:
        return "up"
    if profile.ib_broken_below:
        return "down"
    return "none"


def _shape_name(profile: ProfileWindow) -> str:
    return str(profile.shape)


def _extract_profile_row(
    *,
    symbol: str,
    market: str,
    asset_type: str,
    session_date: str,
    day_frame: pd.DataFrame,
    daily_profile: ProfileWindow,
    prev_day_profile: Optional[ProfileWindow],
    week_profile: ProfileWindow,
    prev_week_profile: Optional[ProfileWindow],
    month_profile: ProfileWindow,
    prev_month_profile: Optional[ProfileWindow],
) -> dict[str, Any]:
    close_price = float(day_frame["close"].iloc[-1])
    open_price = float(day_frame["open"].iloc[0])
    first_hour_high = float(day_frame["high"].iloc[0])
    first_hour_low = float(day_frame["low"].iloc[0])
    tolerance = max(daily_profile.tick_size * 0.5, 1e-6)
    prev_for_open = prev_day_profile or daily_profile

    daily_close_levels = _price_vs_profile(close_price, daily_profile)
    week_close_levels = _price_vs_profile(close_price, week_profile)
    month_close_levels = _price_vs_profile(close_price, month_profile)
    day_vs_week_tolerance = max(daily_profile.tick_size, week_profile.tick_size) * 0.5
    week_vs_month_tolerance = max(week_profile.tick_size, month_profile.tick_size) * 0.5

    return {
        "symbol": symbol,
        "market": market,
        "asset_type": asset_type,
        "session_date": session_date,
        "open": open_price,
        "close": close_price,
        "high": float(day_frame["high"].max()),
        "low": float(day_frame["low"].min()),
        "volume": float(day_frame["volume"].sum()),
        "daily_open_type": _daily_open_type(day_frame, prev_day_profile, tolerance=tolerance),
        "day_shape": _shape_name(daily_profile),
        "week_shape": _shape_name(week_profile),
        "month_shape": _shape_name(month_profile),
        "day_single_print_count": _single_print_count(daily_profile),
        "week_single_print_count": _single_print_count(week_profile),
        "month_single_print_count": _single_print_count(month_profile),
        "day_single_print_width": _single_print_width(daily_profile),
        "week_single_print_width": _single_print_width(week_profile),
        "month_single_print_width": _single_print_width(month_profile),
        "day_excess_high_ticks": _tail_single_print_count(daily_profile, "high"),
        "day_excess_low_ticks": _tail_single_print_count(daily_profile, "low"),
        "week_excess_high_ticks": _tail_single_print_count(week_profile, "high"),
        "week_excess_low_ticks": _tail_single_print_count(week_profile, "low"),
        "month_excess_high_ticks": _tail_single_print_count(month_profile, "high"),
        "month_excess_low_ticks": _tail_single_print_count(month_profile, "low"),
        "day_incomplete_high": _incomplete_auction(daily_profile, "high"),
        "day_incomplete_low": _incomplete_auction(daily_profile, "low"),
        "week_incomplete_high": _incomplete_auction(week_profile, "high"),
        "week_incomplete_low": _incomplete_auction(week_profile, "low"),
        "month_incomplete_high": _incomplete_auction(month_profile, "high"),
        "month_incomplete_low": _incomplete_auction(month_profile, "low"),
        "day_failed_high_auction": _failed_auction(daily_profile, prev_day_profile, "high"),
        "day_failed_low_auction": _failed_auction(daily_profile, prev_day_profile, "low"),
        "week_failed_high_auction": _failed_auction(week_profile, prev_week_profile, "high"),
        "week_failed_low_auction": _failed_auction(week_profile, prev_week_profile, "low"),
        "month_failed_high_auction": _failed_auction(month_profile, prev_month_profile, "high"),
        "month_failed_low_auction": _failed_auction(month_profile, prev_month_profile, "low"),
        "day_ib_break_state": _ib_break_state(daily_profile),
        "week_ib_break_state": _ib_break_state(week_profile),
        "month_ib_break_state": _ib_break_state(month_profile),
        "day_va_relation_week": _profile_band_relation(daily_profile, week_profile, tolerance=day_vs_week_tolerance),
        "week_va_relation_month": _profile_band_relation(week_profile, month_profile, tolerance=week_vs_month_tolerance),
        "day_poc_position_week": _price_position(daily_profile.poc, week_profile, tolerance=day_vs_week_tolerance),
        "week_poc_position_month": _price_position(week_profile.poc, month_profile, tolerance=week_vs_month_tolerance),
        "open_position_prev_day": _price_position(open_price, prev_for_open, tolerance=tolerance),
        "close_position_day": _price_position(close_price, daily_profile, tolerance=tolerance),
        "close_position_week": _price_position(close_price, week_profile, tolerance=day_vs_week_tolerance),
        "close_position_month": _price_position(close_price, month_profile, tolerance=week_vs_month_tolerance),
        "day_va_overlap_prev": 0.0 if prev_day_profile is None else _va_overlap_ratio(prev_day_profile, daily_profile),
        "week_va_overlap_prev": 0.0 if prev_week_profile is None else _va_overlap_ratio(prev_week_profile, week_profile),
        "month_va_overlap_prev": 0.0 if prev_month_profile is None else _va_overlap_ratio(prev_month_profile, month_profile),
        "day_va_overlap_week": _va_overlap_ratio(daily_profile, week_profile),
        "week_va_overlap_month": _va_overlap_ratio(week_profile, month_profile),
        "day_va_migration_prev": "none" if prev_day_profile is None else _migration(prev_day_profile, daily_profile, tick_size=daily_profile.tick_size),
        "week_va_migration_prev": "none" if prev_week_profile is None else _migration(prev_week_profile, week_profile, tick_size=week_profile.tick_size),
        "month_va_migration_prev": "none" if prev_month_profile is None else _migration(prev_month_profile, month_profile, tick_size=month_profile.tick_size),
        "day_value_width_pct": float(daily_profile.va_width_pct),
        "week_value_width_pct": float(week_profile.va_width_pct),
        "month_value_width_pct": float(month_profile.va_width_pct),
        "day_poc_position": float(daily_profile.poc_position),
        "week_poc_position": float(week_profile.poc_position),
        "month_poc_position": float(month_profile.poc_position),
        "day_ib_range_pct": float(daily_profile.ib_range) / max(float(daily_profile.range_points), daily_profile.tick_size),
        "week_ib_range_pct": float(week_profile.ib_range) / max(float(week_profile.range_points), week_profile.tick_size),
        "month_ib_range_pct": float(month_profile.ib_range) / max(float(month_profile.range_points), month_profile.tick_size),
        "first_hour_range_pct": (first_hour_high - first_hour_low) / max(close_price, 1e-6),
        "day_close_vs_day_poc_ticks": daily_close_levels["vs_poc_ticks"],
        "day_close_vs_day_vah_ticks": daily_close_levels["vs_vah_ticks"],
        "day_close_vs_day_val_ticks": daily_close_levels["vs_val_ticks"],
        "day_close_vs_day_ib_high_ticks": daily_close_levels["vs_ib_high_ticks"],
        "day_close_vs_day_ib_low_ticks": daily_close_levels["vs_ib_low_ticks"],
        "day_close_vs_week_poc_ticks": week_close_levels["vs_poc_ticks"],
        "day_close_vs_week_vah_ticks": week_close_levels["vs_vah_ticks"],
        "day_close_vs_week_val_ticks": week_close_levels["vs_val_ticks"],
        "day_close_vs_month_poc_ticks": month_close_levels["vs_poc_ticks"],
        "day_close_vs_month_vah_ticks": month_close_levels["vs_vah_ticks"],
        "day_close_vs_month_val_ticks": month_close_levels["vs_val_ticks"],
        "day_open_vs_prev_poc_ticks": _price_vs_profile(open_price, prev_for_open)["vs_poc_ticks"],
        "day_open_vs_prev_vah_ticks": _price_vs_profile(open_price, prev_for_open)["vs_vah_ticks"],
        "day_open_vs_prev_val_ticks": _price_vs_profile(open_price, prev_for_open)["vs_val_ticks"],
        "day_value_stack_bullish": int(
            _profile_band_relation(daily_profile, week_profile, tolerance=day_vs_week_tolerance) == "above"
            and _profile_band_relation(week_profile, month_profile, tolerance=week_vs_month_tolerance) == "above"
        ),
        "day_value_stack_bearish": int(
            _profile_band_relation(daily_profile, week_profile, tolerance=day_vs_week_tolerance) == "below"
            and _profile_band_relation(week_profile, month_profile, tolerance=week_vs_month_tolerance) == "below"
        ),
    }


def _build_symbol_daily_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []

    market = str(frame["market"].iloc[0])
    asset_type = str(frame["asset_type"].iloc[0])
    symbol = str(frame["symbol"].iloc[0])
    local_tz = _market_timezone(market)
    session_hours = _hours_per_session(market)

    ordered = frame.copy()
    ordered["local_timestamp"] = ordered["timestamp"].dt.tz_convert(local_tz)
    ordered["session_date"] = ordered["local_timestamp"].dt.strftime("%Y-%m-%d")
    iso = ordered["local_timestamp"].dt.isocalendar()
    ordered["week_key"] = iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)
    ordered["month_key"] = ordered["local_timestamp"].dt.strftime("%Y-%m")
    ordered = ordered.sort_values("local_timestamp").reset_index(drop=True)

    rows: list[dict[str, Any]] = []
    prev_day_profile: Optional[ProfileWindow] = None
    prev_week_profile: Optional[ProfileWindow] = None
    prev_month_profile: Optional[ProfileWindow] = None
    week_frames: list[pd.DataFrame] = []
    month_frames: list[pd.DataFrame] = []
    active_week_key: Optional[str] = None
    active_month_key: Optional[str] = None

    for session_date, day_frame in ordered.groupby("session_date", sort=True):
        day_frame = day_frame.sort_values("local_timestamp").reset_index(drop=True)
        week_key = str(day_frame["week_key"].iloc[0])
        month_key = str(day_frame["month_key"].iloc[0])

        if active_week_key is None or week_key != active_week_key:
            if week_frames:
                prev_week_profile = _build_profile_from_hourly_frame(
                    pd.concat(week_frames, ignore_index=True),
                    market=market,
                    ib_periods=session_hours,
                )
            week_frames = []
            active_week_key = week_key

        if active_month_key is None or month_key != active_month_key:
            if month_frames:
                prev_month_profile = _build_profile_from_hourly_frame(
                    pd.concat(month_frames, ignore_index=True),
                    market=market,
                    ib_periods=session_hours,
                )
            month_frames = []
            active_month_key = month_key

        week_frames.append(day_frame)
        month_frames.append(day_frame)

        daily_profile = _build_profile_from_hourly_frame(day_frame, market=market, ib_periods=1)
        week_profile = _build_profile_from_hourly_frame(
            pd.concat(week_frames, ignore_index=True),
            market=market,
            ib_periods=session_hours,
        )
        month_profile = _build_profile_from_hourly_frame(
            pd.concat(month_frames, ignore_index=True),
            market=market,
            ib_periods=session_hours,
        )
        if daily_profile is None or week_profile is None or month_profile is None:
            continue

        rows.append(
            _extract_profile_row(
                symbol=symbol,
                market=market,
                asset_type=asset_type,
                session_date=str(session_date),
                day_frame=day_frame,
                daily_profile=daily_profile,
                prev_day_profile=prev_day_profile,
                week_profile=week_profile,
                prev_week_profile=prev_week_profile,
                month_profile=month_profile,
                prev_month_profile=prev_month_profile,
            )
        )
        prev_day_profile = daily_profile

    return rows


def _label_targets(dataset: pd.DataFrame, config: ProfileInteractionConfig) -> pd.DataFrame:
    if dataset.empty:
        return dataset

    labeled = dataset.copy()
    for column in ("future_up_move_2d", "future_down_move_2d", "future_abs_move_2d"):
        labeled[column] = np.nan

    targets = [float(value) for value in config.stock_targets]
    for target in targets:
        labeled[f"target_{int(round(target * 100))}pct_hit"] = np.nan
        labeled[f"target_{int(round(target * 100))}pct_direction"] = "neutral"
    labeled[f"target_{int(round(config.index_target * 100))}pct_hit"] = np.nan
    labeled[f"target_{int(round(config.index_target * 100))}pct_direction"] = "neutral"

    frames: list[pd.DataFrame] = []
    horizon = max(int(config.horizon_days), 1)
    for _, group in labeled.groupby("symbol", sort=False):
        symbol_frame = group.sort_values("session_date").copy()
        high = symbol_frame["high"].astype(float)
        low = symbol_frame["low"].astype(float)
        close = symbol_frame["close"].astype(float)
        future_high = pd.concat({offset: high.shift(-offset) / close - 1.0 for offset in range(1, horizon + 1)}, axis=1)
        future_low = pd.concat({offset: 1.0 - (low.shift(-offset) / close) for offset in range(1, horizon + 1)}, axis=1)
        up_move = future_high.max(axis=1)
        down_move = future_low.max(axis=1)
        abs_move = pd.concat([up_move, down_move], axis=1).max(axis=1)
        symbol_frame["future_up_move_2d"] = up_move
        symbol_frame["future_down_move_2d"] = down_move
        symbol_frame["future_abs_move_2d"] = abs_move

        if str(symbol_frame["asset_type"].iloc[0]) == "stock":
            for target in targets:
                label = f"target_{int(round(target * 100))}pct"
                symbol_frame[f"{label}_hit"] = (abs_move >= target).astype(float)
                symbol_frame[f"{label}_direction"] = np.where(
                    (up_move >= target) & (up_move >= down_move),
                    "up",
                    np.where((down_move >= target) & (down_move > up_move), "down", "neutral"),
                )
        else:
            label = f"target_{int(round(config.index_target * 100))}pct"
            symbol_frame[f"{label}_hit"] = (abs_move >= float(config.index_target)).astype(float)
            symbol_frame[f"{label}_direction"] = np.where(
                (up_move >= config.index_target) & (up_move >= down_move),
                "up",
                np.where((down_move >= config.index_target) & (down_move > up_move), "down", "neutral"),
            )
        frames.append(symbol_frame)

    output = pd.concat(frames, ignore_index=True)
    output = output.dropna(subset=["future_abs_move_2d"]).reset_index(drop=True)
    return output


def _select_model_feature_columns(dataset: pd.DataFrame) -> list[str]:
    excluded = {
        "symbol",
        "market",
        "asset_type",
        "session_date",
    }
    return [
        column
        for column in dataset.columns
        if column not in excluded
        and not column.startswith("target_")
        and not column.startswith("future_")
    ]


def _train_direction_model(
    dataset: pd.DataFrame,
    *,
    feature_columns: Sequence[str],
    label_column: str,
    target_name: str,
    output_dir: Path,
    random_state: int,
) -> ModelArtifacts:
    working = dataset[list(feature_columns) + ["session_date", label_column]].copy()
    working = working.replace([np.inf, -np.inf], np.nan).dropna(subset=["session_date", label_column])
    working["session_date"] = pd.to_datetime(working["session_date"], errors="coerce")
    working = working.dropna(subset=["session_date"])
    if working.empty:
        return ModelArtifacts(
            target_column=target_name,
            label_column=label_column,
            rows=0,
            train_rows=0,
            test_rows=0,
            accuracy=0.0,
            balanced_accuracy=0.0,
            f1_macro=0.0,
            class_distribution={},
            top_features=[],
            model_path=None,
        )

    features = pd.get_dummies(working[list(feature_columns)], dtype=float)
    working = pd.concat([working[["session_date", label_column]].reset_index(drop=True), features.reset_index(drop=True)], axis=1)

    train_cutoff = working["session_date"].quantile(0.80)
    train_mask = working["session_date"] <= train_cutoff
    test_mask = working["session_date"] > train_cutoff

    train = working.loc[train_mask].copy()
    test = working.loc[test_mask].copy()
    if train.empty:
        train = working.copy()
    if test.empty:
        test = working.tail(min(len(working), max(len(working) // 5, 1))).copy()

    encoded_columns = [column for column in working.columns if column not in {"session_date", label_column}]
    medians = train[encoded_columns].median(numeric_only=True)
    X_train = train[encoded_columns].fillna(medians).fillna(0.0)
    X_test = test[encoded_columns].fillna(medians).fillna(0.0)
    y_train = train[label_column].astype(str)
    y_test = test[label_column].astype(str)

    if y_train.nunique() < 2:
        return ModelArtifacts(
            target_column=target_name,
            label_column=label_column,
            rows=int(len(working)),
            train_rows=int(len(train)),
            test_rows=int(len(test)),
            accuracy=0.0,
            balanced_accuracy=0.0,
            f1_macro=0.0,
            class_distribution=_safe_class_distribution(working[label_column].astype(str)),
            top_features=[],
            model_path=None,
        )

    model = RandomForestClassifier(
        n_estimators=320,
        max_depth=10,
        min_samples_leaf=40,
        class_weight="balanced_subsample",
        random_state=random_state,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)
    predictions = model.predict(X_test)

    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / f"{target_name}_direction_rf.joblib"
    joblib.dump(
        {
            "model": model,
            "feature_columns": list(encoded_columns),
            "feature_medians": medians.to_dict(),
            "label_column": label_column,
            "target_column": target_name,
        },
        model_path,
    )

    importances = pd.Series(model.feature_importances_, index=encoded_columns)
    top_features = [
        {"feature": str(name), "importance": float(value)}
        for name, value in importances.sort_values(ascending=False).head(20).items()
    ]

    return ModelArtifacts(
        target_column=target_name,
        label_column=label_column,
        rows=int(len(working)),
        train_rows=int(len(train)),
        test_rows=int(len(test)),
        accuracy=float(accuracy_score(y_test, predictions)),
        balanced_accuracy=float(balanced_accuracy_score(y_test, predictions)),
        f1_macro=float(f1_score(y_test, predictions, average="macro")),
        class_distribution=_safe_class_distribution(working[label_column].astype(str)),
        top_features=top_features,
        model_path=str(model_path),
    )


def _build_condition_table(dataset: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        "open_in_prev_value": dataset["daily_open_type"] == "in_prev_value",
        "open_above_prev_value": dataset["daily_open_type"] == "above_prev_value",
        "open_below_prev_value": dataset["daily_open_type"] == "below_prev_value",
        "open_above_prev_range": dataset["daily_open_type"] == "above_prev_range",
        "open_below_prev_range": dataset["daily_open_type"] == "below_prev_range",
        "open_drive_up": dataset["daily_open_type"] == "drive_up",
        "open_drive_down": dataset["daily_open_type"] == "drive_down",
        "open_rejection_up": dataset["daily_open_type"] == "rejection_up",
        "open_rejection_down": dataset["daily_open_type"] == "rejection_down",
        "day_shape_p": dataset["day_shape"] == "P",
        "day_shape_b": dataset["day_shape"] == "b",
        "day_shape_d": dataset["day_shape"] == "D",
        "day_shape_elongated_up": dataset["day_shape"] == "elongated_up",
        "day_shape_elongated_down": dataset["day_shape"] == "elongated_down",
        "week_shape_p": dataset["week_shape"] == "P",
        "week_shape_b": dataset["week_shape"] == "b",
        "week_shape_elongated_up": dataset["week_shape"] == "elongated_up",
        "week_shape_elongated_down": dataset["week_shape"] == "elongated_down",
        "month_shape_p": dataset["month_shape"] == "P",
        "month_shape_b": dataset["month_shape"] == "b",
        "month_shape_elongated_up": dataset["month_shape"] == "elongated_up",
        "month_shape_elongated_down": dataset["month_shape"] == "elongated_down",
        "day_single_prints": dataset["day_single_print_count"] > 0,
        "week_single_prints": dataset["week_single_print_count"] > 0,
        "month_single_prints": dataset["month_single_print_count"] > 0,
        "day_excess_high": dataset["day_excess_high_ticks"] >= 2,
        "day_excess_low": dataset["day_excess_low_ticks"] >= 2,
        "week_excess_high": dataset["week_excess_high_ticks"] >= 2,
        "week_excess_low": dataset["week_excess_low_ticks"] >= 2,
        "month_excess_high": dataset["month_excess_high_ticks"] >= 2,
        "month_excess_low": dataset["month_excess_low_ticks"] >= 2,
        "day_incomplete_high": dataset["day_incomplete_high"].astype(bool),
        "day_incomplete_low": dataset["day_incomplete_low"].astype(bool),
        "week_incomplete_high": dataset["week_incomplete_high"].astype(bool),
        "week_incomplete_low": dataset["week_incomplete_low"].astype(bool),
        "month_incomplete_high": dataset["month_incomplete_high"].astype(bool),
        "month_incomplete_low": dataset["month_incomplete_low"].astype(bool),
        "day_failed_high_auction": dataset["day_failed_high_auction"].astype(bool),
        "day_failed_low_auction": dataset["day_failed_low_auction"].astype(bool),
        "week_failed_high_auction": dataset["week_failed_high_auction"].astype(bool),
        "week_failed_low_auction": dataset["week_failed_low_auction"].astype(bool),
        "month_failed_high_auction": dataset["month_failed_high_auction"].astype(bool),
        "month_failed_low_auction": dataset["month_failed_low_auction"].astype(bool),
        "day_ib_break_up": dataset["day_ib_break_state"] == "up",
        "day_ib_break_down": dataset["day_ib_break_state"] == "down",
        "day_ib_break_both": dataset["day_ib_break_state"] == "both",
        "week_ib_break_up": dataset["week_ib_break_state"] == "up",
        "week_ib_break_down": dataset["week_ib_break_state"] == "down",
        "month_ib_break_up": dataset["month_ib_break_state"] == "up",
        "month_ib_break_down": dataset["month_ib_break_state"] == "down",
        "day_value_above_week": dataset["day_va_relation_week"] == "above",
        "day_value_below_week": dataset["day_va_relation_week"] == "below",
        "day_value_inside_week": dataset["day_va_relation_week"] == "inside",
        "day_value_overlapping_week": dataset["day_va_relation_week"] == "overlapping",
        "week_value_above_month": dataset["week_va_relation_month"] == "above",
        "week_value_below_month": dataset["week_va_relation_month"] == "below",
        "week_value_inside_month": dataset["week_va_relation_month"] == "inside",
        "day_poc_above_week_value": dataset["day_poc_position_week"] == "above_value",
        "day_poc_below_week_value": dataset["day_poc_position_week"] == "below_value",
        "day_poc_inside_week_value": dataset["day_poc_position_week"] == "inside_value",
        "week_poc_above_month_value": dataset["week_poc_position_month"] == "above_value",
        "week_poc_below_month_value": dataset["week_poc_position_month"] == "below_value",
        "week_poc_inside_month_value": dataset["week_poc_position_month"] == "inside_value",
        "close_above_day_vah": dataset["day_close_vs_day_vah_ticks"] >= 0,
        "close_below_day_val": dataset["day_close_vs_day_val_ticks"] <= 0,
        "close_above_week_vah": dataset["day_close_vs_week_vah_ticks"] >= 0,
        "close_below_week_val": dataset["day_close_vs_week_val_ticks"] <= 0,
        "close_above_month_vah": dataset["day_close_vs_month_vah_ticks"] >= 0,
        "close_below_month_val": dataset["day_close_vs_month_val_ticks"] <= 0,
        "day_va_up": dataset["day_va_migration_prev"].isin({"up", "gap_up"}),
        "day_va_down": dataset["day_va_migration_prev"].isin({"down", "gap_down"}),
        "week_va_up": dataset["week_va_migration_prev"].isin({"up", "gap_up"}),
        "week_va_down": dataset["week_va_migration_prev"].isin({"down", "gap_down"}),
        "month_va_up": dataset["month_va_migration_prev"].isin({"up", "gap_up"}),
        "month_va_down": dataset["month_va_migration_prev"].isin({"down", "gap_down"}),
        "day_week_overlap_low": dataset["day_va_overlap_week"] <= 0.20,
        "day_week_overlap_high": dataset["day_va_overlap_week"] >= 0.60,
        "week_month_overlap_low": dataset["week_va_overlap_month"] <= 0.20,
        "week_month_overlap_high": dataset["week_va_overlap_month"] >= 0.60,
        "value_stack_bullish": dataset["day_value_stack_bullish"] >= 1,
        "value_stack_bearish": dataset["day_value_stack_bearish"] >= 1,
    }


def _evaluate_conditions(
    dataset: pd.DataFrame,
    *,
    target_column: str,
    label_column: str,
    config: ProfileInteractionConfig,
) -> pd.DataFrame:
    conditions = {name: series.fillna(False) for name, series in _build_condition_table(dataset).items()}
    target = dataset[target_column].astype(float)
    labels = dataset[label_column].astype(str)
    baseline = float(target.mean()) if len(target) else 0.0
    rows: list[dict[str, Any]] = []

    def add_row(name: str, mask: pd.Series, condition_type: str) -> None:
        support = int(mask.sum())
        if support < int(config.min_condition_support):
            return
        hit_rate = float(target[mask].mean())
        if baseline <= 0 or hit_rate <= 0:
            return
        label_counts = labels[mask & (labels != "neutral")].value_counts(normalize=True)
        rows.append(
            {
                "condition": name,
                "type": condition_type,
                "support": support,
                "support_pct": support / max(len(dataset), 1),
                "hit_rate": hit_rate,
                "baseline_hit_rate": baseline,
                "lift": hit_rate / baseline,
                "up_share": float(label_counts.get("up", 0.0)),
                "down_share": float(label_counts.get("down", 0.0)),
                "avg_abs_move_2d": float(dataset.loc[mask, "future_abs_move_2d"].mean()),
            }
        )

    for name, mask in conditions.items():
        add_row(name, mask, "single")

    ranked = sorted(rows, key=lambda row: (row["lift"], row["support"]), reverse=True)
    shortlisted = [row["condition"] for row in ranked[: int(config.top_condition_count)]]
    for left, right in combinations(shortlisted, 2):
        add_row(f"{left} & {right}", conditions[left] & conditions[right], "pair")

    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values(["lift", "support"], ascending=[False, False]).reset_index(drop=True)


def _iter_market_target_jobs(dataset: pd.DataFrame, config: ProfileInteractionConfig) -> Iterable[tuple[str, str, str, str]]:
    index_label = f"target_{int(round(config.index_target * 100))}pct"
    for market in sorted(dataset["market"].astype(str).unique()):
        market_frame = dataset.loc[dataset["market"].astype(str) == market]
        stock_frame = market_frame.loc[market_frame["asset_type"].astype(str) == "stock"]
        if not stock_frame.empty:
            for target in config.stock_targets:
                label = f"target_{int(round(target * 100))}pct"
                yield market, "stock", f"{int(round(target * 100))}pct", label
        index_frame = market_frame.loc[market_frame["asset_type"].astype(str) == "index"]
        if not index_frame.empty:
            yield market, "index", f"{int(round(config.index_target * 100))}pct", index_label


class ProfileInteractionResearchRunner:
    def __init__(self, config: ProfileInteractionConfig) -> None:
        self.config = config

    def run(self) -> dict[str, Any]:
        hourly = _load_hourly_history(self.config)
        daily_rows: list[dict[str, Any]] = []
        coverage_rows: list[dict[str, Any]] = []

        for (market, symbol), group in hourly.groupby(["market", "symbol"], sort=True):
            symbol_rows = _build_symbol_daily_rows(group)
            coverage_rows.append(
                {
                    "market": str(market),
                    "symbol": str(symbol),
                    "asset_type": str(group["asset_type"].iloc[0]),
                    "hourly_rows": int(len(group)),
                    "daily_rows": int(len(symbol_rows)),
                }
            )
            if len(symbol_rows) >= int(self.config.min_daily_rows_per_symbol):
                daily_rows.extend(symbol_rows)

        if not daily_rows:
            raise RuntimeError("No symbols produced enough profile rows for research.")

        dataset = pd.DataFrame(daily_rows)
        dataset = _label_targets(dataset, self.config)
        dataset = dataset.replace([np.inf, -np.inf], np.nan)

        report_dir = Path(self.config.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        dataset_path = report_dir / "profile_dataset.csv.gz"
        coverage_path = report_dir / "coverage.json"
        dataset.to_csv(dataset_path, index=False, compression="gzip")
        coverage_path.write_text(json.dumps(coverage_rows, indent=2), encoding="utf-8")

        summary_rows: list[dict[str, Any]] = []
        artifact_rows: dict[str, str] = {}
        model_rows: dict[str, dict[str, Any]] = {}
        models_dir = report_dir / "models"
        for market, asset_type, target_name, label_root in _iter_market_target_jobs(dataset, self.config):
            subset = dataset.loc[
                (dataset["market"].astype(str) == market)
                & (dataset["asset_type"].astype(str) == asset_type)
            ].copy()
            if subset.empty:
                continue
            target_column = f"{label_root}_hit"
            label_column = f"{label_root}_direction"
            conditions = _evaluate_conditions(
                subset,
                target_column=target_column,
                label_column=label_column,
                config=self.config,
            )
            artifact_key = f"{market.lower()}_{asset_type}_{target_name}_conditions"
            artifact_path = report_dir / f"{artifact_key}.csv"
            conditions.to_csv(artifact_path, index=False)
            artifact_rows[artifact_key] = str(artifact_path)

            feature_columns = _select_model_feature_columns(subset)
            model_key = f"{market.lower()}_{asset_type}_{target_name}"
            model_summary = _train_direction_model(
                subset,
                feature_columns=feature_columns,
                label_column=label_column,
                target_name=model_key,
                output_dir=models_dir,
                random_state=42,
            )
            model_rows[model_key] = asdict(model_summary)
            if model_summary.model_path:
                artifact_rows[f"{model_key}_model"] = str(model_summary.model_path)
            summary_rows.append(
                {
                    "market": market,
                    "asset_type": asset_type,
                    "target": target_name,
                    "rows": int(len(subset)),
                    "symbols": int(subset["symbol"].nunique()),
                    "hit_rate": round(float(subset[target_column].mean()), 4),
                    "up_share": round(float((subset[label_column] == "up").mean()), 4),
                    "down_share": round(float((subset[label_column] == "down").mean()), 4),
                    "avg_abs_move_2d": round(float(subset["future_abs_move_2d"].mean()), 4),
                    "top_condition": str(conditions.iloc[0]["condition"]) if not conditions.empty else None,
                    "top_condition_hit_rate": round(float(conditions.iloc[0]["hit_rate"]), 4) if not conditions.empty else None,
                    "top_condition_lift": round(float(conditions.iloc[0]["lift"]), 4) if not conditions.empty else None,
                }
            )

        summary = {
            "config": asdict(self.config),
            "summary": summary_rows,
            "artifacts": {
                "dataset": str(dataset_path),
                "coverage": str(coverage_path),
                **artifact_rows,
            },
            "models": model_rows,
        }
        summary_path = report_dir / "summary.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary


def build_parser() -> Any:
    import argparse

    parser = argparse.ArgumentParser(description="Research profile interactions from saved 1h candles.")
    parser.add_argument("--input-dataset", default=_default_input_dataset())
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--market", choices=["NSE", "US", "ALL"], default="ALL")
    parser.add_argument("--horizon-days", type=int, default=2)
    parser.add_argument("--min-daily-rows-per-symbol", type=int, default=120)
    parser.add_argument("--min-condition-support", type=int, default=100)
    parser.add_argument("--top-condition-count", type=int, default=12)
    parser.add_argument("--max-stock-symbols-per-market", type=int, default=0)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    runner = ProfileInteractionResearchRunner(
        ProfileInteractionConfig(
            input_dataset=args.input_dataset,
            report_dir=args.report_dir,
            market=args.market,
            horizon_days=args.horizon_days,
            min_daily_rows_per_symbol=args.min_daily_rows_per_symbol,
            min_condition_support=args.min_condition_support,
            top_condition_count=args.top_condition_count,
            max_stock_symbols_per_market=args.max_stock_symbols_per_market,
        )
    )
    result = runner.run()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
