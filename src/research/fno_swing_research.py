"""Offline FnO swing research pipeline.

This module pulls long-history daily data for the NSE FnO equity universe,
labels large directional swings, computes technical plus profile-style
features, mines high-lift conditions, and trains simple directional models
that can later be integrated into the trading agent.

The research design is intentionally daily-bar based so it can cover the full
10-year universe reproducibly without needing institutional intraday history.
Market-profile structure is approximated with a rolling composite value area,
POC, and skew/range based shape proxy built from daily OHLCV.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from itertools import combinations
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score
import yfinance as yf

from src.analysis.indicators.momentum import MACD, ROC, RSI
from src.analysis.indicators.trend import ADX
from src.analysis.indicators.volatility import ATR, BollingerBands, DonchianChannels
from src.analysis.indicators.volume import ChaikinMoneyFlow, MFI, OBV
from src.config.fno_constants import EQUITY_FNO, FNO_SYMBOLS
from src.utils.logger import get_logger

logger = get_logger(__name__)

_PRICE_RENAME = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adj_close",
    "Volume": "volume",
}


@dataclass(frozen=True)
class ResearchConfig:
    """Configuration for the FnO swing research run."""

    start_date: str = "2016-01-01"
    end_date: str | None = None
    batch_size: int = 40
    min_history_days: int = 750
    profile_window: int = 20
    profile_context_window: int = 60
    volume_window: int = 20
    volatility_window: int = 20
    long_trend_window: int = 50
    short_move_pct: float = 0.05
    short_horizon_days: int = 2
    long_move_pct: float = 0.10
    long_horizon_min_days: int = 10
    long_horizon_max_days: int = 15
    short_atr_multipliers: tuple[float, ...] = (1.0, 1.25, 1.5, 1.75, 2.0)
    long_atr_multipliers: tuple[float, ...] = (1.5, 2.0, 2.5, 3.0, 3.5)
    desired_short_hit_rate: float = 0.10
    desired_long_hit_rate: float = 0.06
    min_condition_support: int = 150
    top_condition_count: int = 12
    top_feature_count: int = 20
    model_train_fraction: float = 0.80
    random_state: int = 42
    report_dir: str = "tmp/fno_swing_research"


@dataclass
class ModelArtifacts:
    """Serializable model metadata."""

    target_column: str
    label_column: str
    rows: int
    train_rows: int
    test_rows: int
    accuracy: float
    balanced_accuracy: float
    f1_macro: float
    class_distribution: dict[str, int]
    top_features: list[dict[str, float]]
    model_path: str


def yahoo_equity_ticker(symbol: str) -> str:
    """Map an NSE equity symbol to the Yahoo Finance ticker."""
    return f"{symbol}.NS"


def _batched(values: Sequence[str], size: int) -> Iterable[list[str]]:
    for idx in range(0, len(values), max(size, 1)):
        yield list(values[idx : idx + size])


def _normalize_price_frame(
    frame: pd.DataFrame,
    symbol: str,
    *,
    ticker: str | None = None,
    sector: str | None = None,
) -> pd.DataFrame:
    """Normalize one symbol's raw Yahoo price frame to adjusted OHLCV."""
    if frame.empty:
        return pd.DataFrame()

    if isinstance(frame.columns, pd.MultiIndex):
        level_zero = frame.columns.get_level_values(0)
        level_last = frame.columns.get_level_values(-1)
        expected = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}

        # yfinance may return a single-ticker MultiIndex in either
        # (price, ticker) or (ticker, price) order.
        if expected.intersection(level_zero):
            frame = frame.copy()
            frame.columns = level_zero
        elif expected.intersection(level_last):
            frame = frame.copy()
            frame.columns = level_last

    normalized = frame.rename(columns=_PRICE_RENAME).copy()
    expected_columns = {"open", "high", "low", "close", "volume"}
    if not expected_columns.issubset(normalized.columns):
        return pd.DataFrame()

    normalized.index = pd.to_datetime(normalized.index).tz_localize(None)
    normalized = normalized[~normalized.index.duplicated(keep="last")]
    normalized = normalized.sort_index()
    normalized = normalized.dropna(subset=["open", "high", "low", "close"])
    if normalized.empty:
        return pd.DataFrame()

    adj_close = normalized.get("adj_close", normalized["close"]).astype(float)
    close = normalized["close"].astype(float).replace(0, np.nan)
    factor = (adj_close / close).replace([np.inf, -np.inf], np.nan).fillna(1.0)

    adjusted = pd.DataFrame(index=normalized.index)
    adjusted["open"] = normalized["open"].astype(float) * factor
    adjusted["high"] = normalized["high"].astype(float) * factor
    adjusted["low"] = normalized["low"].astype(float) * factor
    adjusted["close"] = adj_close.astype(float)
    adjusted["volume"] = normalized["volume"].astype(float) / factor.replace(0, np.nan)
    equity_meta = EQUITY_FNO.get(symbol)
    adjusted["symbol"] = symbol
    adjusted["sector"] = sector or (equity_meta.sector if equity_meta is not None else "UNKNOWN")
    adjusted["ticker"] = ticker or (yahoo_equity_ticker(symbol) if equity_meta is not None else symbol)
    return adjusted.dropna(subset=["open", "high", "low", "close", "volume"])


def _download_batch(
    symbols: Sequence[str],
    start_date: str,
    end_date: str | None,
) -> tuple[list[pd.DataFrame], list[str]]:
    tickers = [yahoo_equity_ticker(symbol) for symbol in symbols]
    raw = yf.download(
        tickers=tickers,
        start=start_date,
        end=end_date,
        auto_adjust=False,
        progress=False,
        threads=True,
        group_by="ticker",
    )

    frames: list[pd.DataFrame] = []
    failures: list[str] = []
    for symbol, ticker in zip(symbols, tickers):
        try:
            symbol_frame = (
                raw[ticker].copy()
                if isinstance(raw.columns, pd.MultiIndex)
                else raw.copy()
            )
        except KeyError:
            failures.append(symbol)
            continue

        normalized = _normalize_price_frame(symbol_frame, symbol)
        if normalized.empty:
            failures.append(symbol)
            continue
        frames.append(normalized)

    return frames, failures


def download_history(
    symbols: Sequence[str],
    config: ResearchConfig,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Download and normalize daily history for the requested symbols."""
    frames: list[pd.DataFrame] = []
    failed: list[str] = []

    for batch in _batched(list(symbols), config.batch_size):
        batch_frames, batch_failures = _download_batch(
            batch,
            start_date=config.start_date,
            end_date=config.end_date,
        )
        frames.extend(batch_frames)
        failed.extend(batch_failures)

    # Retry batch failures individually to recover transient Yahoo misses.
    retried_failed: list[str] = []
    for symbol in failed:
        batch_frames, batch_failures = _download_batch(
            [symbol],
            start_date=config.start_date,
            end_date=config.end_date,
        )
        frames.extend(batch_frames)
        retried_failed.extend(batch_failures)

    if not frames:
        raise RuntimeError("No historical data downloaded for the FnO universe.")

    history = pd.concat(frames).sort_index()
    history.index.name = "date"

    coverage_rows: list[dict[str, Any]] = []
    for symbol, group in history.groupby("symbol"):
        coverage_rows.append(
            {
                "symbol": symbol,
                "sector": str(group["sector"].iloc[0]),
                "rows": int(len(group)),
                "start": str(group.index.min().date()),
                "end": str(group.index.max().date()),
            }
        )

    metadata = {
        "symbols_requested": len(symbols),
        "symbols_downloaded": len(coverage_rows),
        "symbols_failed": sorted(set(retried_failed)),
        "coverage": coverage_rows,
    }
    return history, metadata


def download_nifty_regime(config: ResearchConfig) -> pd.DataFrame:
    """Download Nifty 50 benchmark data and build regime features."""
    raw = yf.download(
        tickers="^NSEI",
        start=config.start_date,
        end=config.end_date,
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    normalized = _normalize_price_frame(
        raw,
        "NIFTY_BENCH",
        ticker="^NSEI",
        sector="INDEX",
    )
    if normalized.empty:
        raise RuntimeError("Failed to download ^NSEI benchmark history.")

    close = normalized["close"]
    rsi_14 = RSI(period=14).calculate(close)
    atr_14 = ATR(period=14).calculate(
        close,
        high=normalized["high"],
        low=normalized["low"],
    )
    ema_20 = close.ewm(span=20, adjust=False).mean()
    ema_50 = close.ewm(span=50, adjust=False).mean()

    regime = pd.DataFrame(index=normalized.index)
    regime["nifty_return_5"] = close.pct_change(5)
    regime["nifty_return_20"] = close.pct_change(20)
    regime["nifty_rsi_14"] = rsi_14
    regime["nifty_atr_pct"] = atr_14 / close.replace(0, np.nan)
    regime["nifty_trend_bias"] = (ema_20 / ema_50) - 1.0
    regime["nifty_above_ema50"] = (close > ema_50).astype(float)
    regime["nifty_bull_regime"] = (
        (close > ema_50) & (rsi_14 >= 55)
    ).astype(float)
    regime["nifty_bear_regime"] = (
        (close < ema_50) & (rsi_14 <= 45)
    ).astype(float)
    return regime


def classify_profile_shape_proxy(
    skew_value: float,
    poc_position: float,
    range_to_atr: float,
) -> str:
    """Classify a rolling composite profile proxy into coarse structures."""
    if not np.isfinite(skew_value) or not np.isfinite(poc_position):
        return "unknown"

    if np.isfinite(range_to_atr) and range_to_atr >= 7.0 and abs(skew_value) <= 0.25:
        return "trend"
    if skew_value <= -0.35 and poc_position >= 0.55:
        return "p_shape"
    if skew_value >= 0.35 and poc_position <= 0.45:
        return "b_shape"
    if abs(skew_value) <= 0.20 and 0.35 <= poc_position <= 0.65:
        return "balanced"
    return "normal"


def build_profile_proxy_features(
    data: pd.DataFrame,
    profile_window: int,
) -> pd.DataFrame:
    """Build rolling composite profile-style features from daily bars."""
    typical = (data["high"] + data["low"] + data["close"]) / 3.0
    roll_low = data["low"].rolling(profile_window, min_periods=profile_window).min().shift(1)
    roll_high = data["high"].rolling(profile_window, min_periods=profile_window).max().shift(1)
    profile_poc = typical.rolling(profile_window, min_periods=profile_window).median().shift(1)
    profile_val = typical.rolling(profile_window, min_periods=profile_window).quantile(0.15).shift(1)
    profile_vah = typical.rolling(profile_window, min_periods=profile_window).quantile(0.85).shift(1)
    profile_skew = typical.rolling(profile_window, min_periods=profile_window).skew().shift(1)

    atr = ATR(period=14).calculate(
        data["close"],
        high=data["high"],
        low=data["low"],
    )
    total_range = (roll_high - roll_low).replace(0, np.nan)
    poc_position = (profile_poc - roll_low) / total_range
    range_to_atr = total_range / atr.replace(0, np.nan)

    shape = [
        classify_profile_shape_proxy(float(skew), float(position), float(range_ratio))
        for skew, position, range_ratio in zip(
            profile_skew.fillna(np.nan),
            poc_position.fillna(np.nan),
            range_to_atr.fillna(np.nan),
            strict=False,
        )
    ]

    profile = pd.DataFrame(index=data.index)
    profile["profile_poc"] = profile_poc
    profile["profile_val"] = profile_val
    profile["profile_vah"] = profile_vah
    profile["profile_width_pct"] = (profile_vah - profile_val) / data["close"].replace(0, np.nan)
    profile["profile_skew"] = profile_skew
    profile["profile_poc_position"] = poc_position
    profile["profile_range_atr"] = range_to_atr
    profile["profile_close_to_poc_atr"] = (data["close"] - profile_poc) / atr.replace(0, np.nan)
    profile["profile_above_vah"] = (data["close"] > profile_vah).astype(float)
    profile["profile_below_val"] = (data["close"] < profile_val).astype(float)
    profile["profile_in_value"] = (
        (data["close"] >= profile_val) & (data["close"] <= profile_vah)
    ).astype(float)
    profile["profile_shape_trend"] = pd.Series([1.0 if s == "trend" else 0.0 for s in shape], index=data.index)
    profile["profile_shape_p"] = pd.Series([1.0 if s == "p_shape" else 0.0 for s in shape], index=data.index)
    profile["profile_shape_b"] = pd.Series([1.0 if s == "b_shape" else 0.0 for s in shape], index=data.index)
    profile["profile_shape_balanced"] = pd.Series(
        [1.0 if s == "balanced" else 0.0 for s in shape],
        index=data.index,
    )
    profile["profile_shape_code"] = pd.Series(shape, index=data.index)
    return profile


def build_feature_frame(
    data: pd.DataFrame,
    regime: pd.DataFrame,
    config: ResearchConfig,
) -> pd.DataFrame:
    """Build the research feature frame for one symbol."""
    close = data["close"]
    high = data["high"]
    low = data["low"]
    volume = data["volume"]
    returns = close.pct_change()

    atr = ATR(period=14).calculate(close, high=high, low=low)
    bb = BollingerBands(period=20, std_dev=2.0).calculate(close)
    adx = ADX(period=14).calculate(data)
    macd = MACD().calculate(close)
    donchian = DonchianChannels(period=20).calculate(data)
    cmf = ChaikinMoneyFlow(period=20).calculate(data)
    mfi = MFI(period=14).calculate(data)
    obv = OBV().calculate(data)
    rsi = RSI(period=14).calculate(close)
    roc_12 = ROC(period=12).calculate(close)
    profile = build_profile_proxy_features(data, profile_window=config.profile_window)

    ema_10 = close.ewm(span=10, adjust=False).mean()
    ema_20 = close.ewm(span=20, adjust=False).mean()
    ema_50 = close.ewm(span=50, adjust=False).mean()
    volume_mean = volume.rolling(config.volume_window, min_periods=config.volume_window).mean()
    volume_std = volume.rolling(config.volume_window, min_periods=config.volume_window).std()
    range_pct = (high - low) / close.replace(0, np.nan)
    bb_width = bb["bandwidth"]
    bb_width_median = bb_width.rolling(config.profile_context_window, min_periods=20).median()
    atr_pct = atr / close.replace(0, np.nan)
    atr_pct_median = atr_pct.rolling(config.profile_context_window, min_periods=20).median()

    features = pd.DataFrame(index=data.index)
    features["symbol"] = data["symbol"]
    features["sector"] = data["sector"]
    features["open"] = data["open"]
    features["high"] = high
    features["low"] = low
    features["close"] = close
    features["volume"] = volume
    features["return_1"] = returns
    features["return_3"] = close.pct_change(3)
    features["return_5"] = close.pct_change(5)
    features["return_10"] = close.pct_change(10)
    features["return_20"] = close.pct_change(20)
    features["gap_pct"] = (data["open"] - close.shift(1)) / close.shift(1).replace(0, np.nan)
    features["range_pct"] = range_pct
    features["close_position"] = (close - low) / (high - low).replace(0, np.nan)
    features["atr_pct"] = atr_pct
    features["atr_ratio_60"] = atr_pct / atr_pct_median.replace(0, np.nan)
    features["realized_vol_10"] = returns.rolling(10, min_periods=10).std() * np.sqrt(252)
    features["realized_vol_20"] = returns.rolling(20, min_periods=20).std() * np.sqrt(252)
    features["realized_vol_ratio"] = (
        features["realized_vol_10"] / features["realized_vol_20"].replace(0, np.nan)
    )
    features["ema_gap_10"] = (close / ema_10) - 1.0
    features["ema_gap_20"] = (close / ema_20) - 1.0
    features["ema_gap_50"] = (close / ema_50) - 1.0
    features["ema_trend_20_50"] = (ema_20 / ema_50) - 1.0
    features["rsi_14"] = rsi
    features["adx_14"] = adx["adx"]
    features["plus_di_14"] = adx["plus_di"]
    features["minus_di_14"] = adx["minus_di"]
    features["macd_hist"] = macd["histogram"]
    features["bb_width"] = bb_width
    features["bb_width_ratio_60"] = bb_width / bb_width_median.replace(0, np.nan)
    features["bb_position"] = (close - bb["lower"]) / (bb["upper"] - bb["lower"]).replace(0, np.nan)
    features["volume_ratio_20"] = volume / volume_mean.replace(0, np.nan)
    features["volume_zscore_20"] = (volume - volume_mean) / volume_std.replace(0, np.nan)
    features["cmf_20"] = cmf
    features["mfi_14"] = mfi
    features["obv_slope_20"] = obv.diff(20) / 20.0
    features["roc_12"] = roc_12 / 100.0
    features["prior_high_breakout_20"] = close / high.shift(1).rolling(20, min_periods=20).max() - 1.0
    features["prior_low_breakdown_20"] = close / low.shift(1).rolling(20, min_periods=20).min() - 1.0
    features["donchian_width"] = donchian["width"]
    features["nr7"] = (range_pct <= range_pct.rolling(7, min_periods=7).min()).astype(float)
    features["inside_day"] = (
        (high <= high.shift(1)) & (low >= low.shift(1))
    ).astype(float)

    for column in profile.columns:
        if column == "profile_shape_code":
            continue
        features[column] = profile[column]

    joined = features.join(regime, how="left")
    return joined


def _future_move_matrix(series: pd.Series, horizon: int, kind: str) -> pd.DataFrame:
    matrices = []
    for offset in range(1, horizon + 1):
        shifted = series.shift(-offset)
        matrices.append(shifted.rename(offset))
    matrix = pd.concat(matrices, axis=1)
    matrix.columns = list(range(1, horizon + 1))
    if kind == "up":
        return matrix
    return matrix


def add_swing_targets(
    frame: pd.DataFrame,
    config: ResearchConfig,
) -> pd.DataFrame:
    """Label future swings for multiple ATR-normalized thresholds."""
    close = frame["close"]
    high = frame["high"]
    low = frame["low"]
    atr_pct = frame["atr_pct"]

    max_horizon = max(config.short_horizon_days, config.long_horizon_max_days)
    future_high = pd.concat(
        {
            offset: high.shift(-offset) / close - 1.0
            for offset in range(1, max_horizon + 1)
        },
        axis=1,
    )
    future_low = pd.concat(
        {
            offset: 1.0 - (low.shift(-offset) / close)
            for offset in range(1, max_horizon + 1)
        },
        axis=1,
    )

    short_up = future_high.loc[:, 1 : config.short_horizon_days].max(axis=1)
    short_down = future_low.loc[:, 1 : config.short_horizon_days].max(axis=1)
    short_abs = pd.concat([short_up, short_down], axis=1).max(axis=1)

    long_up = future_high.loc[:, config.long_horizon_min_days : config.long_horizon_max_days].max(axis=1)
    long_down = future_low.loc[:, config.long_horizon_min_days : config.long_horizon_max_days].max(axis=1)
    long_abs = pd.concat([long_up, long_down], axis=1).max(axis=1)

    targets = frame.copy()
    targets["future_up_2d"] = short_up
    targets["future_down_2d"] = short_down
    targets["future_abs_2d"] = short_abs
    targets["future_up_10_15d"] = long_up
    targets["future_down_10_15d"] = long_down
    targets["future_abs_10_15d"] = long_abs
    targets["future_return_2d"] = close.shift(-config.short_horizon_days) / close - 1.0
    targets["future_return_10d"] = close.shift(-config.long_horizon_min_days) / close - 1.0
    targets["future_return_15d"] = close.shift(-config.long_horizon_max_days) / close - 1.0
    targets["future_move_atr_multiple_2d"] = short_abs / atr_pct.replace(0, np.nan)
    targets["future_move_atr_multiple_10_15d"] = long_abs / atr_pct.replace(0, np.nan)

    for multiplier in config.short_atr_multipliers:
        threshold = np.maximum(config.short_move_pct, atr_pct * multiplier)
        column_key = str(multiplier).replace(".", "_")
        hit_column = f"target_short_hit_atr_{column_key}"
        label_column = f"target_short_direction_atr_{column_key}"
        short_up_hit = short_up >= threshold
        short_down_hit = short_down >= threshold
        targets[hit_column] = (short_up_hit | short_down_hit).astype(float)
        targets[label_column] = np.where(
            short_up_hit & (short_up >= short_down),
            "up",
            np.where(short_down_hit & (short_down > short_up), "down", "neutral"),
        )

    for multiplier in config.long_atr_multipliers:
        threshold = np.maximum(config.long_move_pct, atr_pct * multiplier)
        column_key = str(multiplier).replace(".", "_")
        hit_column = f"target_long_hit_atr_{column_key}"
        label_column = f"target_long_direction_atr_{column_key}"
        long_up_hit = long_up >= threshold
        long_down_hit = long_down >= threshold
        targets[hit_column] = (long_up_hit | long_down_hit).astype(float)
        targets[label_column] = np.where(
            long_up_hit & (long_up >= long_down),
            "up",
            np.where(long_down_hit & (long_down > long_up), "down", "neutral"),
        )

    return targets


def choose_target_columns(
    dataset: pd.DataFrame,
    config: ResearchConfig,
) -> dict[str, Any]:
    """Choose working target columns based on desired positive rates."""
    short_candidates: list[dict[str, Any]] = []
    for multiplier in config.short_atr_multipliers:
        key = str(multiplier).replace(".", "_")
        column = f"target_short_hit_atr_{key}"
        rate = float(dataset[column].mean())
        short_candidates.append(
            {
                "multiplier": multiplier,
                "hit_column": column,
                "label_column": f"target_short_direction_atr_{key}",
                "positive_rate": rate,
            }
        )

    long_candidates: list[dict[str, Any]] = []
    for multiplier in config.long_atr_multipliers:
        key = str(multiplier).replace(".", "_")
        column = f"target_long_hit_atr_{key}"
        rate = float(dataset[column].mean())
        long_candidates.append(
            {
                "multiplier": multiplier,
                "hit_column": column,
                "label_column": f"target_long_direction_atr_{key}",
                "positive_rate": rate,
            }
        )

    selected_short = min(
        short_candidates,
        key=lambda row: abs(row["positive_rate"] - config.desired_short_hit_rate),
    )
    selected_long = min(
        long_candidates,
        key=lambda row: abs(row["positive_rate"] - config.desired_long_hit_rate),
    )

    return {
        "short_grid": short_candidates,
        "long_grid": long_candidates,
        "selected_short": selected_short,
        "selected_long": selected_long,
    }


def build_condition_table(dataset: pd.DataFrame) -> dict[str, pd.Series]:
    """Construct binary conditions for lift analysis."""
    conditions = {
        "bullish_ema_stack": (
            (dataset["ema_gap_20"] > 0)
            & (dataset["ema_gap_50"] > 0)
            & (dataset["ema_trend_20_50"] > 0)
        ),
        "bearish_ema_stack": (
            (dataset["ema_gap_20"] < 0)
            & (dataset["ema_gap_50"] < 0)
            & (dataset["ema_trend_20_50"] < 0)
        ),
        "rsi_breakout": dataset["rsi_14"] >= 60,
        "rsi_breakdown": dataset["rsi_14"] <= 40,
        "adx_trending": dataset["adx_14"] >= 25,
        "volume_expansion": dataset["volume_ratio_20"] >= 1.5,
        "volume_surge": dataset["volume_zscore_20"] >= 2.0,
        "atr_compression": dataset["atr_ratio_60"] <= 0.90,
        "bb_squeeze": dataset["bb_width_ratio_60"] <= 0.85,
        "nr7_setup": dataset["nr7"] >= 1.0,
        "donchian_breakout": dataset["prior_high_breakout_20"] >= 0.0,
        "donchian_breakdown": dataset["prior_low_breakdown_20"] <= 0.0,
        "profile_above_value": dataset["profile_above_vah"] >= 1.0,
        "profile_below_value": dataset["profile_below_val"] >= 1.0,
        "profile_trend": dataset["profile_shape_trend"] >= 1.0,
        "profile_p_shape": dataset["profile_shape_p"] >= 1.0,
        "profile_b_shape": dataset["profile_shape_b"] >= 1.0,
        "profile_balanced": dataset["profile_shape_balanced"] >= 1.0,
        "cmf_positive": dataset["cmf_20"] >= 0.10,
        "cmf_negative": dataset["cmf_20"] <= -0.10,
        "nifty_bull_regime": dataset["nifty_bull_regime"] >= 1.0,
        "nifty_bear_regime": dataset["nifty_bear_regime"] >= 1.0,
    }
    return {name: series.fillna(False) for name, series in conditions.items()}


def evaluate_conditions(
    dataset: pd.DataFrame,
    target_column: str,
    label_column: str,
    min_support: int,
    top_condition_count: int,
) -> pd.DataFrame:
    """Rank high-lift single and pair conditions for a target."""
    conditions = build_condition_table(dataset)
    target = dataset[target_column].astype(float)
    labels = dataset[label_column].astype(str)
    baseline = float(target.mean()) if len(target) else 0.0
    rows: list[dict[str, Any]] = []

    def add_row(name: str, mask: pd.Series, condition_type: str) -> None:
        support = int(mask.sum())
        if support < min_support:
            return
        hit_rate = float(target[mask].mean())
        if hit_rate <= 0 or baseline <= 0:
            return
        label_counts = labels[mask & (labels != "neutral")].value_counts(normalize=True)
        rows.append(
            {
                "condition": name,
                "type": condition_type,
                "support": support,
                "support_pct": support / len(dataset),
                "hit_rate": hit_rate,
                "baseline_hit_rate": baseline,
                "lift": hit_rate / baseline,
                "up_share": float(label_counts.get("up", 0.0)),
                "down_share": float(label_counts.get("down", 0.0)),
                "avg_abs_move_2d": float(dataset.loc[mask, "future_abs_2d"].mean()),
                "avg_abs_move_10_15d": float(dataset.loc[mask, "future_abs_10_15d"].mean()),
            }
        )

    for name, mask in conditions.items():
        add_row(name, mask, "single")

    single_rank = sorted(rows, key=lambda row: (row["lift"], row["support"]), reverse=True)
    shortlisted = [row["condition"] for row in single_rank[:top_condition_count]]
    for left_name, right_name in combinations(shortlisted, 2):
        add_row(
            f"{left_name} & {right_name}",
            conditions[left_name] & conditions[right_name],
            "pair",
        )

    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values(["lift", "support"], ascending=[False, False]).reset_index(drop=True)


def _safe_class_distribution(labels: pd.Series) -> dict[str, int]:
    counts = labels.value_counts()
    return {str(key): int(value) for key, value in counts.items()}


def train_direction_model(
    dataset: pd.DataFrame,
    feature_columns: Sequence[str],
    label_column: str,
    target_column: str,
    output_dir: Path,
    random_state: int,
) -> ModelArtifacts:
    """Train a pooled time-split random forest direction model."""
    working = dataset[list(feature_columns) + ["date", label_column]].copy()
    working = working.replace([np.inf, -np.inf], np.nan)

    train_cutoff = working["date"].quantile(0.80)
    train_mask = working["date"] <= train_cutoff
    test_mask = working["date"] > train_cutoff

    train = working.loc[train_mask].copy()
    test = working.loc[test_mask].copy()

    medians = train[list(feature_columns)].median(numeric_only=True)
    X_train = train[list(feature_columns)].fillna(medians)
    X_test = test[list(feature_columns)].fillna(medians)
    y_train = train[label_column].astype(str)
    y_test = test[label_column].astype(str)

    model = RandomForestClassifier(
        n_estimators=400,
        max_depth=10,
        min_samples_leaf=50,
        class_weight="balanced_subsample",
        random_state=random_state,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)
    predictions = model.predict(X_test)

    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / f"{target_column}_rf.joblib"
    joblib.dump(
        {
            "model": model,
            "feature_columns": list(feature_columns),
            "feature_medians": medians.to_dict(),
            "label_column": label_column,
            "target_column": target_column,
        },
        model_path,
    )

    importances = pd.Series(model.feature_importances_, index=feature_columns)
    top_features = [
        {"feature": str(name), "importance": float(value)}
        for name, value in importances.sort_values(ascending=False).head(20).items()
    ]

    return ModelArtifacts(
        target_column=target_column,
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


def select_model_feature_columns(
    dataset: pd.DataFrame,
    *,
    excluded_labels: Sequence[str],
) -> list[str]:
    """Return trainable feature columns with target leakage removed."""
    excluded = {
        "symbol",
        "sector",
        "ticker",
        "date",
        "profile_shape_code",
        *excluded_labels,
    }
    return [
        column
        for column in dataset.columns
        if column not in excluded
        and not column.startswith("target_")
        and not column.startswith("future_")
    ]


def render_report(summary: dict[str, Any]) -> str:
    """Render a compact markdown report from the research summary."""
    short_selection = summary["selected_targets"]["selected_short"]
    long_selection = summary["selected_targets"]["selected_long"]
    short_conditions = summary["top_conditions"]["short"][:8]
    long_conditions = summary["top_conditions"]["long"][:8]
    short_model = summary["models"]["short_direction"]
    long_model = summary["models"]["long_direction"]

    def format_conditions(rows: Sequence[dict[str, Any]]) -> str:
        if not rows:
            return "- none"
        return "\n".join(
            (
                f"- `{row['condition']}`: hit {row['hit_rate']:.2%}, "
                f"lift {row['lift']:.2f}, support {row['support']}"
            )
            for row in rows
        )

    def format_features(rows: Sequence[dict[str, Any]]) -> str:
        if not rows:
            return "- none"
        return "\n".join(
            f"- `{row['feature']}`: {row['importance']:.4f}"
            for row in rows[:10]
        )

    return (
        "# FnO Swing Research\n\n"
        f"- Symbols requested: {summary['download']['symbols_requested']}\n"
        f"- Symbols downloaded: {summary['download']['symbols_downloaded']}\n"
        f"- Dataset rows after filtering: {summary['dataset']['rows']}\n"
        f"- Research period: {summary['dataset']['start']} to {summary['dataset']['end']}\n\n"
        "## Targets\n\n"
        f"- 2-day target uses ATR multiplier `{short_selection['multiplier']}` "
        f"with positive rate `{short_selection['positive_rate']:.2%}`\n"
        f"- 10-15 day target uses ATR multiplier `{long_selection['multiplier']}` "
        f"with positive rate `{long_selection['positive_rate']:.2%}`\n\n"
        "## Highest-Lift Conditions For 2-Day Swings\n\n"
        f"{format_conditions(short_conditions)}\n\n"
        "## Highest-Lift Conditions For 10-15 Day Swings\n\n"
        f"{format_conditions(long_conditions)}\n\n"
        "## Direction Models\n\n"
        f"- Short horizon: accuracy `{short_model['accuracy']:.3f}`, "
        f"balanced accuracy `{short_model['balanced_accuracy']:.3f}`, "
        f"macro F1 `{short_model['f1_macro']:.3f}`\n"
        f"- Long horizon: accuracy `{long_model['accuracy']:.3f}`, "
        f"balanced accuracy `{long_model['balanced_accuracy']:.3f}`, "
        f"macro F1 `{long_model['f1_macro']:.3f}`\n\n"
        "### Top Short-Horizon Features\n\n"
        f"{format_features(short_model['top_features'])}\n\n"
        "### Top Long-Horizon Features\n\n"
        f"{format_features(long_model['top_features'])}\n"
    )


@dataclass
class FnOSwingResearchRunner:
    """Coordinator for the full FnO swing research workflow."""

    config: ResearchConfig = field(default_factory=ResearchConfig)

    def run(self, symbols: Sequence[str] | None = None) -> dict[str, Any]:
        selected_symbols = list(symbols or FNO_SYMBOLS)
        logger.info("fno_swing_research_start", symbols=len(selected_symbols))

        history, download_meta = download_history(selected_symbols, self.config)
        regime = download_nifty_regime(self.config)

        enriched_frames: list[pd.DataFrame] = []
        for symbol, group in history.groupby("symbol"):
            if len(group) < self.config.min_history_days:
                continue
            features = build_feature_frame(group.copy(), regime, self.config)
            labeled = add_swing_targets(features, self.config)
            labeled["date"] = labeled.index
            enriched_frames.append(labeled)

        if not enriched_frames:
            raise RuntimeError("No symbol had enough history after feature engineering.")

        dataset = pd.concat(enriched_frames, ignore_index=True).sort_values(["date", "symbol"]).reset_index(drop=True)
        dataset = dataset.replace([np.inf, -np.inf], np.nan)

        selected_targets = choose_target_columns(dataset, self.config)
        short_target = selected_targets["selected_short"]["hit_column"]
        short_label = selected_targets["selected_short"]["label_column"]
        long_target = selected_targets["selected_long"]["hit_column"]
        long_label = selected_targets["selected_long"]["label_column"]

        model_dataset = dataset.dropna(
            subset=[
                "atr_pct",
                "rsi_14",
                "adx_14",
                "ema_gap_20",
                "ema_gap_50",
                "profile_close_to_poc_atr",
                "nifty_return_20",
            ]
        ).copy()

        feature_columns = select_model_feature_columns(
            model_dataset,
            excluded_labels=[short_label, long_label],
        )

        sector_dummies = pd.get_dummies(model_dataset["sector"], prefix="sector", dtype=float)
        model_dataset = pd.concat([model_dataset, sector_dummies], axis=1)
        feature_columns.extend(list(sector_dummies.columns))

        report_dir = Path(self.config.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        models_dir = report_dir / "models"

        short_conditions = evaluate_conditions(
            model_dataset,
            target_column=short_target,
            label_column=short_label,
            min_support=self.config.min_condition_support,
            top_condition_count=self.config.top_condition_count,
        )
        long_conditions = evaluate_conditions(
            model_dataset,
            target_column=long_target,
            label_column=long_label,
            min_support=self.config.min_condition_support,
            top_condition_count=self.config.top_condition_count,
        )

        short_model = train_direction_model(
            model_dataset,
            feature_columns=feature_columns,
            label_column=short_label,
            target_column="short_direction",
            output_dir=models_dir,
            random_state=self.config.random_state,
        )
        long_model = train_direction_model(
            model_dataset,
            feature_columns=feature_columns,
            label_column=long_label,
            target_column="long_direction",
            output_dir=models_dir,
            random_state=self.config.random_state,
        )

        dataset_path = report_dir / "labeled_dataset.csv.gz"
        coverage_path = report_dir / "download_coverage.json"
        short_conditions_path = report_dir / "condition_stats_short.csv"
        long_conditions_path = report_dir / "condition_stats_long.csv"
        summary_path = report_dir / "summary.json"
        report_path = report_dir / "report.md"

        dataset.to_csv(dataset_path, index=False, compression="gzip")
        coverage_path.write_text(json.dumps(download_meta, indent=2), encoding="utf-8")
        short_conditions.to_csv(short_conditions_path, index=False)
        long_conditions.to_csv(long_conditions_path, index=False)

        summary = {
            "config": asdict(self.config),
            "download": {
                "symbols_requested": download_meta["symbols_requested"],
                "symbols_downloaded": download_meta["symbols_downloaded"],
                "symbols_failed": download_meta["symbols_failed"],
            },
            "dataset": {
                "rows": int(len(dataset)),
                "symbols": int(dataset["symbol"].nunique()),
                "start": str(pd.to_datetime(dataset["date"]).min().date()),
                "end": str(pd.to_datetime(dataset["date"]).max().date()),
            },
            "selected_targets": selected_targets,
            "top_conditions": {
                "short": short_conditions.head(20).to_dict(orient="records"),
                "long": long_conditions.head(20).to_dict(orient="records"),
            },
            "models": {
                "short_direction": asdict(short_model),
                "long_direction": asdict(long_model),
            },
            "artifacts": {
                "dataset": str(dataset_path),
                "coverage": str(coverage_path),
                "short_conditions": str(short_conditions_path),
                "long_conditions": str(long_conditions_path),
                "report": str(report_path),
            },
        }

        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        report_path.write_text(render_report(summary), encoding="utf-8")
        logger.info("fno_swing_research_complete", rows=len(dataset), report=str(report_path))
        return summary
