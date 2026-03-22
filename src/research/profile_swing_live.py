"""Live scoring helpers for profile-based swing strategies."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import math
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from src.config.constants import INDEX_INSTRUMENTS
from src.research.paths import research_root_dir
from src.research.profile_interaction_research import (
    _build_condition_table,
    _build_symbol_daily_rows,
    _market_timezone,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

_US_INDEX_TICKERS = {"SPY", "QQQ", "IWM", "DIA"}
_STOCK_TARGETS: tuple[tuple[str, float], ...] = (("5pct", 0.05), ("10pct", 0.10))
_INDEX_TARGETS: tuple[tuple[str, float], ...] = (("2pct", 0.02),)


def _resolve_profile_report_dir(explicit: str | Path | None) -> Path:
    if explicit:
        return Path(explicit)

    primary = research_root_dir() / "profile_interaction_research"
    fallbacks = [
        primary,
        Path("tmp/profile_interaction_full"),
        Path("tmp/profile_interaction_research"),
        Path("tmp/profile_interaction_smoke"),
    ]
    for candidate in fallbacks:
        if candidate.exists():
            return candidate
    return primary


DEFAULT_PROFILE_SWING_REPORT_DIR = _resolve_profile_report_dir(None)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if not np.isfinite(numeric):
        return default
    return numeric


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("profile_swing_live_json_load_failed", path=str(path), error=str(exc))
        return {}


def _symbol_market(symbol: str) -> str:
    token = str(symbol or "").strip().upper()
    if token.startswith("US:"):
        return "US"
    if token.startswith("CRYPTO:"):
        return "CRYPTO"
    return "NSE"


def _display_symbol(symbol: str) -> str:
    return str(symbol or "").split(":")[-1].split("-")[0]


def _asset_type_for_symbol(symbol: str, market: str) -> str:
    short_name = _display_symbol(symbol).upper()
    if market == "NSE" and short_name in INDEX_INSTRUMENTS:
        return "index"
    if market == "US" and short_name in _US_INDEX_TICKERS:
        return "index"
    if str(symbol or "").upper().endswith("-INDEX"):
        return "index"
    return "stock"


def _load_dataset(report_dir: str) -> pd.DataFrame:
    path = Path(report_dir) / "profile_dataset.csv.gz"
    if not path.exists():
        return pd.DataFrame()
    try:
        dataset = pd.read_csv(path, compression="gzip", low_memory=False)
    except Exception as exc:
        logger.warning("profile_swing_live_dataset_load_failed", report_dir=report_dir, error=str(exc))
        return pd.DataFrame()

    if "session_date" in dataset.columns:
        dataset["session_date"] = pd.to_datetime(dataset["session_date"], errors="coerce")
    elif "date" in dataset.columns:
        dataset["session_date"] = pd.to_datetime(dataset["date"], errors="coerce")
    else:
        dataset["session_date"] = pd.NaT
    return dataset.replace([np.inf, -np.inf], np.nan)


@lru_cache(maxsize=4)
def load_research_summary(report_dir: str) -> dict[str, Any]:
    return _load_json(Path(report_dir) / "summary.json")


@lru_cache(maxsize=4)
def load_condition_stats(report_dir: str, market: str, asset_type: str, target_name: str) -> pd.DataFrame:
    path = Path(report_dir) / f"{market.lower()}_{asset_type}_{target_name}_conditions.csv"
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception as exc:
        logger.warning(
            "profile_swing_live_condition_load_failed",
            report_dir=report_dir,
            market=market,
            asset_type=asset_type,
            target=target_name,
            error=str(exc),
        )
        return pd.DataFrame()


@lru_cache(maxsize=8)
def load_model_bundle(report_dir: str, market: str, asset_type: str, target_name: str) -> dict[str, Any]:
    path = Path(report_dir) / "models" / f"{market.lower()}_{asset_type}_{target_name}_direction_rf.joblib"
    if not path.exists():
        return {}
    try:
        bundle = joblib.load(path)
        return bundle if isinstance(bundle, dict) else {}
    except Exception as exc:
        logger.warning(
            "profile_swing_live_model_load_failed",
            report_dir=report_dir,
            market=market,
            asset_type=asset_type,
            target=target_name,
            error=str(exc),
        )
        return {}


@lru_cache(maxsize=4)
def load_latest_dataset_snapshot(report_dir: str) -> pd.DataFrame:
    dataset = _load_dataset(report_dir)
    if dataset.empty or "symbol" not in dataset.columns:
        return pd.DataFrame()
    dataset = dataset.dropna(subset=["session_date", "symbol"]).sort_values(["symbol", "session_date"])
    latest = dataset.groupby("symbol", as_index=False, sort=True).tail(1).reset_index(drop=True)
    return latest


@lru_cache(maxsize=4)
def load_dataset_metadata(report_dir: str) -> dict[str, Any]:
    dataset = _load_dataset(report_dir)
    if dataset.empty:
        return {
            "rows": 0,
            "symbols": 0,
            "start_date": None,
            "end_date": None,
        }
    return {
        "rows": int(len(dataset)),
        "symbols": int(dataset["symbol"].astype(str).nunique()) if "symbol" in dataset.columns else 0,
        "start_date": str(dataset["session_date"].min().date()) if dataset["session_date"].notna().any() else None,
        "end_date": str(dataset["session_date"].max().date()) if dataset["session_date"].notna().any() else None,
    }


@lru_cache(maxsize=4)
def load_coverage(report_dir: str) -> list[dict[str, Any]]:
    path = Path(report_dir) / "coverage.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, list) else []
    except Exception as exc:
        logger.warning("profile_swing_live_coverage_load_failed", report_dir=report_dir, error=str(exc))
        return []


def _normalize_hourly_frame(
    frame: pd.DataFrame,
    *,
    symbol: str,
    market: str,
    asset_type: str,
) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()

    working = frame.copy()
    if "timestamp" not in working.columns:
        working = working.reset_index()
        if "timestamp" not in working.columns and "index" in working.columns:
            working = working.rename(columns={"index": "timestamp"})
    if "timestamp" not in working.columns:
        return pd.DataFrame()

    working["timestamp"] = pd.to_datetime(working["timestamp"], errors="coerce", utc=True)
    for column in ("open", "high", "low", "close"):
        working[column] = pd.to_numeric(working.get(column), errors="coerce")
    working["volume"] = pd.to_numeric(working.get("volume"), errors="coerce").fillna(0.0)
    working = (
        working.dropna(subset=["timestamp", "open", "high", "low", "close"])
        .sort_values("timestamp")
        .drop_duplicates(subset=["timestamp"], keep="last")
    )
    if working.empty:
        return pd.DataFrame()

    normalized = working[["timestamp", "open", "high", "low", "close", "volume"]].copy()
    normalized["symbol"] = str(symbol or "").strip()
    normalized["market"] = str(market or "").strip().upper()
    normalized["asset_type"] = str(asset_type or "").strip().lower()
    return normalized.reset_index(drop=True)


def _append_daily_volatility(row: dict[str, Any], history: pd.DataFrame, market: str) -> dict[str, Any]:
    local_tz = _market_timezone(market)
    working = history.copy()
    working["local_timestamp"] = working["timestamp"].dt.tz_convert(local_tz)
    working["session_date"] = working["local_timestamp"].dt.strftime("%Y-%m-%d")
    daily = (
        working.groupby("session_date", sort=True)
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
        .reset_index()
    )
    if len(daily) < 5:
        row["daily_atr_pct_14"] = np.nan
        row["daily_range_pct_20"] = np.nan
        return row

    close = pd.to_numeric(daily["close"], errors="coerce")
    high = pd.to_numeric(daily["high"], errors="coerce")
    low = pd.to_numeric(daily["low"], errors="coerce")
    prev_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr_14 = true_range.rolling(14, min_periods=5).mean()
    row["daily_atr_pct_14"] = float((atr_14.iloc[-1] / max(close.iloc[-1], 1e-6)) if not atr_14.empty else np.nan)
    row["daily_range_pct_20"] = float(((high - low) / close.replace(0, np.nan)).tail(20).mean())
    return row


def _build_live_profile_row(
    *,
    symbol: str,
    market: str,
    asset_type: str,
    hourly_frame: pd.DataFrame,
) -> dict[str, Any] | None:
    history = _normalize_hourly_frame(hourly_frame, symbol=symbol, market=market, asset_type=asset_type)
    if history.empty or len(history) < 90:
        return None

    rows = _build_symbol_daily_rows(history)
    if not rows:
        return None

    latest = dict(rows[-1])
    latest["session_date"] = str(latest.get("session_date") or "")
    latest["symbol"] = symbol
    latest["market"] = market
    latest["asset_type"] = asset_type
    return _append_daily_volatility(latest, history, market)


def _condition_weight(row: dict[str, Any]) -> float:
    support = max(int(row.get("support", 0) or 0), 1)
    lift = max(_safe_float(row.get("lift"), 1.0), 1.0)
    return lift * max(math.log1p(support), 1.0)


def _target_config(asset_type: str) -> tuple[tuple[str, float], ...]:
    return _INDEX_TARGETS if asset_type == "index" else _STOCK_TARGETS


def _research_summary_lookup(report_dir: str) -> dict[tuple[str, str, str], dict[str, Any]]:
    summary = load_research_summary(report_dir)
    rows = summary.get("summary", [])
    lookup: dict[tuple[str, str, str], dict[str, Any]] = {}
    if not isinstance(rows, list):
        return lookup
    for item in rows:
        if not isinstance(item, dict):
            continue
        key = (
            str(item.get("market") or "").upper(),
            str(item.get("asset_type") or "").lower(),
            str(item.get("target") or "").lower(),
        )
        lookup[key] = item
    return lookup


def _active_conditions(row: pd.Series | dict[str, Any]) -> set[str]:
    frame = pd.DataFrame([row]).replace([np.inf, -np.inf], np.nan)
    try:
        conditions = _build_condition_table(frame)
    except Exception:
        return set()
    return {
        name
        for name, series in conditions.items()
        if not series.empty and bool(series.iloc[-1])
    }


def _matched_conditions(
    *,
    report_dir: str,
    market: str,
    asset_type: str,
    target_name: str,
    active_conditions: set[str],
) -> list[dict[str, Any]]:
    stats = load_condition_stats(report_dir, market, asset_type, target_name)
    if stats.empty:
        return []

    matches: list[dict[str, Any]] = []
    for _, row in stats.iterrows():
        condition = str(row.get("condition") or "").strip()
        if not condition:
            continue
        parts = [part.strip() for part in condition.split("&")]
        if any(part not in active_conditions for part in parts):
            continue
        matches.append(
            {
                "condition": condition,
                "type": str(row.get("type") or ""),
                "support": int(row.get("support", 0) or 0),
                "hit_rate": round(_safe_float(row.get("hit_rate")), 6),
                "lift": round(_safe_float(row.get("lift"), 1.0), 6),
                "up_share": round(_safe_float(row.get("up_share")), 6),
                "down_share": round(_safe_float(row.get("down_share")), 6),
                "avg_abs_move_2d": round(_safe_float(row.get("avg_abs_move_2d")), 6),
            }
        )

    matches.sort(key=lambda item: (_condition_weight(item), item["hit_rate"]), reverse=True)
    return matches[:6]


def _encode_model_record(
    row: pd.Series | dict[str, Any],
    feature_columns: list[str],
    medians: pd.Series,
) -> pd.DataFrame:
    base = pd.DataFrame([dict(row)])
    encoded = pd.get_dummies(base, dtype=float)
    encoded = encoded.reindex(columns=feature_columns, fill_value=0.0)
    encoded = encoded.replace([np.inf, -np.inf], np.nan)
    return encoded.fillna(medians).fillna(0.0)


def _predict_probabilities(
    *,
    report_dir: str,
    market: str,
    asset_type: str,
    target_name: str,
    row: pd.Series | dict[str, Any],
) -> dict[str, float]:
    bundle = load_model_bundle(report_dir, market, asset_type, target_name)
    model = bundle.get("model")
    feature_columns = list(bundle.get("feature_columns", []) or [])
    if model is None or not feature_columns:
        return {}

    medians = pd.Series(bundle.get("feature_medians", {}), dtype=float)
    record = _encode_model_record(row, feature_columns, medians)
    try:
        probabilities = model.predict_proba(record)[0]
    except Exception as exc:
        logger.warning(
            "profile_swing_live_predict_failed",
            report_dir=report_dir,
            market=market,
            asset_type=asset_type,
            target=target_name,
            error=str(exc),
        )
        return {}

    classes = [str(value) for value in getattr(model, "classes_", [])]
    return {
        label: round(_safe_float(probability), 6)
        for label, probability in zip(classes, probabilities, strict=False)
    }


def _condition_probabilities(
    matched_conditions: list[dict[str, Any]],
    baseline_hit_rate: float,
) -> dict[str, float]:
    if not matched_conditions:
        return {}

    weights = np.array([_condition_weight(row) for row in matched_conditions], dtype=float)
    total_weight = float(weights.sum())
    if total_weight <= 0:
        return {}

    hit_rate = float(np.average([_safe_float(item.get("hit_rate")) for item in matched_conditions], weights=weights))
    up_share = float(np.average([_safe_float(item.get("up_share")) for item in matched_conditions], weights=weights))
    down_share = float(np.average([_safe_float(item.get("down_share")) for item in matched_conditions], weights=weights))
    best_lift = max((_safe_float(item.get("lift"), 1.0) for item in matched_conditions), default=1.0)

    dominant_direction = "up" if up_share >= down_share else "down"
    dominant_share = max(up_share, down_share)
    baseline = max(float(baseline_hit_rate), 0.01)
    hit_edge = max(hit_rate - baseline, 0.0)
    confidence = 0.34 + (dominant_share * 0.28) + (min(hit_rate, 0.45) * 0.52) + (hit_edge * 0.9)
    confidence += min(max(best_lift - 1.0, 0.0) * 0.08, 0.08)
    direction_probability = _clamp(confidence, 0.38, 0.88)
    opposite_probability = _clamp((1.0 - direction_probability) * 0.28, 0.04, 0.18)
    neutral_probability = _clamp(1.0 - direction_probability - opposite_probability, 0.08, 0.48)

    if dominant_direction == "up":
        up_probability = direction_probability
        down_probability = opposite_probability
    else:
        up_probability = opposite_probability
        down_probability = direction_probability

    return {
        "up": round(up_probability, 6),
        "down": round(down_probability, 6),
        "neutral": round(neutral_probability, 6),
    }


def _learning_adjustment(learning_profile: dict[str, Any] | None) -> dict[str, float]:
    profile = learning_profile if isinstance(learning_profile, dict) else {}
    trade_count = max(int(profile.get("trade_count", 0) or 0), 0)
    if trade_count < 5:
        return {"score_bonus": 0.0, "probability_delta": 0.0, "neutral_delta": 0.0}

    reward_ema = float(profile.get("reward_ema", 0.0) or 0.0)
    rolling_sharpe = float(profile.get("rolling_sharpe", 0.0) or 0.0)
    win_rate = float(profile.get("win_rate", 0.0) or 0.0)
    performance_edge = ((win_rate - 0.5) * 0.18) + (reward_ema * 0.008) + (rolling_sharpe * 0.035)
    probability_delta = _clamp(performance_edge, -0.05, 0.05)
    score_bonus = _clamp(performance_edge * 120.0, -8.0, 8.0)
    neutral_delta = -probability_delta * 0.75 if probability_delta > 0 else abs(probability_delta) * 0.45
    return {
        "score_bonus": score_bonus,
        "probability_delta": probability_delta,
        "neutral_delta": neutral_delta,
    }


@dataclass
class TargetAssessment:
    target_name: str
    threshold_pct: float
    direction: str
    direction_probability: float
    neutral_probability: float
    direction_edge: float
    score: float
    baseline_hit_rate: float
    matched_conditions: list[dict[str, Any]]
    model_available: bool
    ai_adjustment: float


def _assess_target(
    *,
    report_dir: str,
    market: str,
    asset_type: str,
    target_name: str,
    threshold_pct: float,
    row: pd.Series | dict[str, Any],
    matched_conditions: list[dict[str, Any]],
    baseline_hit_rate: float,
    variant: str,
    learning_profile: dict[str, Any] | None,
) -> TargetAssessment | None:
    probabilities = {}
    model_available = False
    if variant == "ai":
        probabilities = _predict_probabilities(
            report_dir=report_dir,
            market=market,
            asset_type=asset_type,
            target_name=target_name,
            row=row,
        )
        model_available = bool(probabilities)

    if not probabilities:
        probabilities = _condition_probabilities(matched_conditions, baseline_hit_rate)
    if not probabilities:
        return None

    up_probability = _safe_float(probabilities.get("up"))
    down_probability = _safe_float(probabilities.get("down"))
    neutral_probability = _safe_float(probabilities.get("neutral"))

    ai_adjustment = 0.0
    if variant == "ai":
        learning = _learning_adjustment(learning_profile)
        if up_probability >= down_probability:
            up_probability = _clamp(up_probability + learning["probability_delta"], 0.0, 0.95)
        else:
            down_probability = _clamp(down_probability + learning["probability_delta"], 0.0, 0.95)
        neutral_probability = _clamp(neutral_probability + learning["neutral_delta"], 0.03, 0.55)
        total = up_probability + down_probability + neutral_probability
        if total > 0:
            up_probability /= total
            down_probability /= total
            neutral_probability /= total
        ai_adjustment = learning["score_bonus"]

    direction = "up" if up_probability >= down_probability else "down"
    direction_probability = up_probability if direction == "up" else down_probability
    direction_edge = direction_probability - neutral_probability
    best_lift = max((_safe_float(item.get("lift"), 1.0) for item in matched_conditions), default=1.0)
    support_bonus = min(sum(math.log1p(max(int(item.get("support", 0) or 0), 1)) for item in matched_conditions), 8.0)

    score = ((direction_probability + max(direction_edge, 0.0)) * 100.0) + min(max(best_lift - 1.0, 0.0) * 12.0, 12.0)
    score += support_bonus
    if target_name == "10pct":
        score += 2.5
    if target_name == "2pct":
        score -= 2.0
    score += ai_adjustment

    return TargetAssessment(
        target_name=target_name,
        threshold_pct=threshold_pct,
        direction=direction,
        direction_probability=round(direction_probability, 6),
        neutral_probability=round(neutral_probability, 6),
        direction_edge=round(direction_edge, 6),
        score=round(_clamp(score, 0.0, 100.0), 2),
        baseline_hit_rate=round(baseline_hit_rate, 6),
        matched_conditions=matched_conditions,
        model_available=model_available,
        ai_adjustment=round(ai_adjustment, 4),
    )


def _market_regime(row: pd.Series | dict[str, Any]) -> str:
    if _safe_float(row.get("day_value_stack_bullish")) >= 1 or (
        str(row.get("week_va_migration_prev") or "") in {"up", "gap_up"}
        and str(row.get("month_va_migration_prev") or "") in {"up", "gap_up"}
    ):
        return "bull"
    if _safe_float(row.get("day_value_stack_bearish")) >= 1 or (
        str(row.get("week_va_migration_prev") or "") in {"down", "gap_down"}
        and str(row.get("month_va_migration_prev") or "") in {"down", "gap_down"}
    ):
        return "bear"
    return "neutral"


def _expected_move_pct(assessment: TargetAssessment) -> float:
    observed = max((_safe_float(item.get("avg_abs_move_2d")) for item in assessment.matched_conditions), default=0.0)
    raw = max(assessment.threshold_pct, observed)
    cap = 0.14 if assessment.target_name == "10pct" else 0.085 if assessment.target_name == "5pct" else 0.03
    return _clamp(raw, assessment.threshold_pct, cap)


class ProfileSwingLiveScorer:
    """Score live candidates from multi-timeframe profile interaction artifacts."""

    def __init__(self, report_dir: str | Path = DEFAULT_PROFILE_SWING_REPORT_DIR) -> None:
        self.report_dir = str(_resolve_profile_report_dir(report_dir))

    def research_status(self) -> dict[str, Any]:
        summary = load_research_summary(self.report_dir)
        metadata = load_dataset_metadata(self.report_dir)
        coverage = load_coverage(self.report_dir)
        model_dir = Path(self.report_dir) / "models"
        model_files = sorted(path.name for path in model_dir.glob("*.joblib")) if model_dir.exists() else []
        return {
            "ready": bool(summary) or bool(metadata["rows"]),
            "report_dir": self.report_dir,
            "dataset_rows": metadata["rows"],
            "dataset_symbols": metadata["symbols"],
            "start_date": metadata["start_date"],
            "end_date": metadata["end_date"],
            "coverage_symbols": len(coverage),
            "summary": summary.get("summary", []),
            "models_available": model_files,
        }

    def list_latest_candidates(
        self,
        *,
        limit: int = 40,
        min_score: float = 0.0,
        market: str | None = None,
        variant: str = "classic",
    ) -> list[dict[str, Any]]:
        latest = load_latest_dataset_snapshot(self.report_dir)
        if latest.empty:
            return []

        market_key = str(market or "").strip().upper()
        if market_key:
            latest = latest.loc[latest["market"].astype(str).str.upper() == market_key].copy()

        rows: list[dict[str, Any]] = []
        for _, row in latest.iterrows():
            candidate = self._build_candidate(
                row,
                source="research_snapshot",
                variant=variant,
                learning_profile=None,
            )
            if candidate is None:
                continue
            if float(candidate.get("score", 0.0) or 0.0) < float(min_score):
                continue
            rows.append(candidate)

        rows.sort(
            key=lambda item: (
                float(item.get("score", 0.0) or 0.0),
                float(item.get("direction_probability", 0.0) or 0.0),
            ),
            reverse=True,
        )
        return rows[: max(int(limit), 1)]

    def score_latest(
        self,
        *,
        symbol: str,
        hourly_frame: pd.DataFrame | None = None,
        market: str | None = None,
        learning_profile: dict[str, Any] | None = None,
        allow_dataset_fallback: bool = False,
        variant: str = "classic",
    ) -> dict[str, Any] | None:
        market_key = str(market or _symbol_market(symbol)).strip().upper()
        asset_type = _asset_type_for_symbol(symbol, market_key)

        if hourly_frame is not None:
            row = _build_live_profile_row(
                symbol=symbol,
                market=market_key,
                asset_type=asset_type,
                hourly_frame=hourly_frame,
            )
            if row is not None:
                candidate = self._build_candidate(
                    row,
                    source="live_market_data",
                    variant=variant,
                    learning_profile=learning_profile,
                )
                if candidate is not None:
                    return candidate

        if not allow_dataset_fallback:
            return None

        latest = load_latest_dataset_snapshot(self.report_dir)
        if latest.empty:
            return None
        fallback = latest.loc[latest["symbol"].astype(str) == str(symbol)]
        if fallback.empty:
            fallback = latest.loc[latest["symbol"].astype(str).map(_display_symbol) == _display_symbol(symbol)]
        if fallback.empty:
            return None
        return self._build_candidate(
            fallback.iloc[-1],
            source="research_snapshot",
            variant=variant,
            learning_profile=learning_profile,
        )

    def _build_candidate(
        self,
        row: pd.Series | dict[str, Any],
        *,
        source: str,
        variant: str,
        learning_profile: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        symbol = str(row.get("symbol") or "").strip()
        market = str(row.get("market") or _symbol_market(symbol)).strip().upper()
        asset_type = str(row.get("asset_type") or _asset_type_for_symbol(symbol, market)).strip().lower()
        if not symbol or market not in {"NSE", "US"}:
            return None

        active_conditions = _active_conditions(row)
        if not active_conditions:
            return None

        summary_lookup = _research_summary_lookup(self.report_dir)
        assessments: list[TargetAssessment] = []
        for target_name, threshold_pct in _target_config(asset_type):
            summary_row = summary_lookup.get((market, asset_type, target_name), {})
            baseline_hit_rate = _safe_float(summary_row.get("hit_rate"))
            matches = _matched_conditions(
                report_dir=self.report_dir,
                market=market,
                asset_type=asset_type,
                target_name=target_name,
                active_conditions=active_conditions,
            )
            assessment = _assess_target(
                report_dir=self.report_dir,
                market=market,
                asset_type=asset_type,
                target_name=target_name,
                threshold_pct=threshold_pct,
                row=row,
                matched_conditions=matches,
                baseline_hit_rate=baseline_hit_rate,
                variant=variant,
                learning_profile=learning_profile,
            )
            if assessment is not None:
                assessments.append(assessment)

        if not assessments:
            return None

        primary = max(
            assessments,
            key=lambda item: (
                item.score,
                item.direction_probability,
                item.threshold_pct,
            ),
        )
        price = _safe_float(row.get("close"))
        if price <= 0:
            return None

        expected_move_pct = _expected_move_pct(primary)
        atr_pct = max(_safe_float(row.get("daily_atr_pct_14")), 0.0)
        range_pct = max(_safe_float(row.get("daily_range_pct_20")), 0.0)
        stop_move_pct = max(min(expected_move_pct * 0.45, 0.07), atr_pct * 1.1, range_pct * 0.65, 0.02)
        stop_move_pct = min(stop_move_pct, expected_move_pct * 0.72)

        if primary.direction == "up":
            stop_loss = price * (1.0 - stop_move_pct)
            target = price * (1.0 + expected_move_pct)
        else:
            stop_loss = price * (1.0 + stop_move_pct)
            target = price * (1.0 - expected_move_pct)

        planned_holding_days = 3 if primary.target_name == "10pct" else 2
        strength = "strong" if primary.score >= 78 else "moderate" if primary.score >= 62 else "weak"

        return {
            "symbol": _display_symbol(symbol),
            "spot_symbol": symbol,
            "market": market,
            "asset_type": asset_type,
            "price": round(price, 2),
            "date": str(row.get("session_date") or row.get("date") or ""),
            "source": source,
            "variant": variant,
            "direction": primary.direction,
            "target_name": primary.target_name,
            "score": primary.score,
            "strength": strength,
            "direction_probability": primary.direction_probability,
            "neutral_probability": primary.neutral_probability,
            "direction_edge": primary.direction_edge,
            "allow_overnight": True,
            "planned_holding_days": planned_holding_days,
            "expected_move_pct": round(expected_move_pct * 100.0, 2),
            "stop_loss": round(stop_loss, 2),
            "target": round(target, 2),
            "atr_pct": round(atr_pct * 100.0, 2),
            "market_regime": _market_regime(row),
            "baseline_hit_rate": round(primary.baseline_hit_rate * 100.0, 2),
            "matched_conditions": primary.matched_conditions,
            "active_conditions": sorted(active_conditions),
            "model_available": primary.model_available,
            "ai_adjustment": primary.ai_adjustment,
            "learning_profile": learning_profile or {},
        }
