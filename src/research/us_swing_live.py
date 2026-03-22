"""Live scoring helpers for US swing-research artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.config.agent_universe import us_symbol_to_ticker
from src.config.us_swing_universe import (
    US_SWING_BENCHMARK_SYMBOL,
    US_SWING_SECTOR_BY_SYMBOL,
    US_SWING_SECTOR_BY_TICKER,
    US_SWING_SYMBOLS,
)
from src.research.fno_swing_live import (
    HorizonAssessment,
    _normalize_history_frame,
    _safe_float,
    build_live_nifty_regime,
    load_condition_stats,
    load_latest_dataset_snapshot,
    load_model_bundle,
    load_research_config as _load_fno_config,
    load_research_summary as _load_fno_summary,
)
from src.research.fno_swing_research import ResearchConfig, build_condition_table, build_feature_frame
from src.research.paths import resolve_report_dir
from src.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_US_SWING_REPORT_DIR = resolve_report_dir(
    None,
    folder_name="us_swing",
    legacy_fallback="tmp/us_swing_research_full",
)


def load_research_summary(report_dir: str) -> dict[str, Any]:
    return _load_fno_summary(report_dir)


def load_research_config(report_dir: str) -> ResearchConfig:
    summary = load_research_summary(report_dir)
    payload = summary.get("config", {})
    if isinstance(payload, dict):
        supported = {field.name for field in ResearchConfig.__dataclass_fields__.values()}
        filtered = {key: value for key, value in payload.items() if key in supported}
        try:
            return ResearchConfig(**filtered)
        except TypeError:
            logger.warning("us_swing_live_config_fallback", report_dir=report_dir)
    return ResearchConfig(report_dir=report_dir)


class USSwingLiveScorer:
    """Score current US swing candidates from stored research artifacts."""

    def __init__(self, report_dir: str | Path = DEFAULT_US_SWING_REPORT_DIR) -> None:
        self.report_dir = str(
            resolve_report_dir(
                report_dir,
                folder_name="us_swing",
                legacy_fallback="tmp/us_swing_research_full",
            )
        )
        self.config: ResearchConfig = load_research_config(self.report_dir)
        self.summary = load_research_summary(self.report_dir)
        self._selected_targets = self.summary.get("selected_targets", {})

    def research_status(self) -> dict[str, Any]:
        summary = self.summary
        if not summary:
            return {
                "ready": False,
                "report_dir": self.report_dir,
            }
        return {
            "ready": True,
            "report_dir": self.report_dir,
            "requested_symbols": int(summary.get("download", {}).get("symbols_requested", 0) or 0),
            "downloaded_symbols": int(summary.get("download", {}).get("symbols_downloaded", 0) or 0),
            "failed_symbols": list(summary.get("download", {}).get("symbols_failed", []) or []),
            "dataset_rows": int(summary.get("dataset", {}).get("rows", 0) or 0),
            "dataset_symbols": int(summary.get("dataset", {}).get("symbols", 0) or 0),
            "start_date": summary.get("dataset", {}).get("start"),
            "end_date": summary.get("dataset", {}).get("end"),
            "selected_short": self._selected_targets.get("selected_short", {}),
            "selected_long": self._selected_targets.get("selected_long", {}),
            "tuning": summary.get("tuning", {}),
        }

    def list_latest_candidates(
        self,
        *,
        limit: int = 40,
        min_score: float = 0.0,
    ) -> list[dict[str, Any]]:
        latest = load_latest_dataset_snapshot(self.report_dir)
        if latest.empty:
            return []

        rows: list[dict[str, Any]] = []
        for _, row in latest.iterrows():
            candidate = self._build_candidate(row, source="research_snapshot")
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
        daily_frame: pd.DataFrame | None = None,
        benchmark_daily_frame: pd.DataFrame | None = None,
        allow_dataset_fallback: bool = False,
    ) -> dict[str, Any] | None:
        spot_symbol = str(symbol or "").strip().upper()
        ticker = us_symbol_to_ticker(spot_symbol)

        if daily_frame is not None and benchmark_daily_frame is not None:
            candidate = self._score_live_frames(
                spot_symbol=spot_symbol,
                ticker=ticker,
                daily_frame=daily_frame,
                benchmark_daily_frame=benchmark_daily_frame,
            )
            if candidate is not None:
                return candidate

        if not allow_dataset_fallback:
            return None

        latest = load_latest_dataset_snapshot(self.report_dir)
        if latest.empty:
            return None
        fallback = latest.loc[latest["symbol"].astype(str) == ticker]
        if fallback.empty:
            return None
        return self._build_candidate(fallback.iloc[-1], source="research_snapshot")

    def _score_live_frames(
        self,
        *,
        spot_symbol: str,
        ticker: str,
        daily_frame: pd.DataFrame,
        benchmark_daily_frame: pd.DataFrame,
    ) -> dict[str, Any] | None:
        if spot_symbol not in US_SWING_SECTOR_BY_SYMBOL and ticker not in US_SWING_SECTOR_BY_TICKER:
            return None

        symbol_history = _normalize_history_frame(
            daily_frame,
            symbol_root=ticker,
            sector_override=US_SWING_SECTOR_BY_TICKER.get(ticker, "UNKNOWN"),
        )
        benchmark_history = _normalize_history_frame(
            benchmark_daily_frame,
            symbol_root=us_symbol_to_ticker(US_SWING_BENCHMARK_SYMBOL),
            sector_override="INDEX",
        )
        if symbol_history.empty or benchmark_history.empty:
            return None

        regime = build_live_nifty_regime(benchmark_history)
        if regime.empty:
            return None

        feature_frame = build_feature_frame(symbol_history, regime, self.config)
        if feature_frame.empty:
            return None

        latest = feature_frame.replace([np.inf, -np.inf], np.nan).iloc[-1].copy()
        latest["date"] = str(feature_frame.index[-1].date())
        latest["symbol"] = ticker
        latest["sector"] = US_SWING_SECTOR_BY_TICKER.get(ticker, "UNKNOWN")

        candidate = self._build_candidate(latest, source="live_market_data")
        if candidate is not None:
            candidate["spot_symbol"] = spot_symbol
        return candidate

    def _predict_probabilities(self, target_name: str, row: pd.Series | dict[str, Any]) -> dict[str, float]:
        bundle = load_model_bundle(self.report_dir, target_name)
        model = bundle.get("model")
        feature_columns = list(bundle.get("feature_columns", []) or [])
        if model is None or not feature_columns:
            return {}

        medians = pd.Series(bundle.get("feature_medians", {}), dtype=float)
        record = pd.DataFrame([{column: row.get(column, np.nan) for column in feature_columns}])
        record = record.replace([np.inf, -np.inf], np.nan)
        for column in feature_columns:
            if column not in record.columns:
                record[column] = medians.get(column, 0.0)
        record = record[feature_columns].fillna(medians).fillna(0.0)

        try:
            probabilities = model.predict_proba(record)[0]
        except Exception as exc:
            logger.warning("us_swing_live_predict_failed", target=target_name, error=str(exc))
            return {}

        classes = [str(value) for value in getattr(model, "classes_", [])]
        return {
            label: round(_safe_float(prob), 6)
            for label, prob in zip(classes, probabilities, strict=False)
        }

    def _active_conditions(self, row: pd.Series | dict[str, Any]) -> set[str]:
        frame = pd.DataFrame([row]).replace([np.inf, -np.inf], np.nan)
        try:
            conditions = build_condition_table(frame)
        except KeyError:
            return set()
        return {
            name
            for name, series in conditions.items()
            if not series.empty and bool(series.iloc[-1])
        }

    def _matched_conditions(self, horizon: str, active_conditions: set[str]) -> list[dict[str, Any]]:
        stats = load_condition_stats(self.report_dir, horizon)
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
                    "support": int(row.get("support", 0) or 0),
                    "hit_rate": round(_safe_float(row.get("hit_rate")), 6),
                    "lift": round(_safe_float(row.get("lift")), 6),
                    "up_share": round(_safe_float(row.get("up_share")), 6),
                    "down_share": round(_safe_float(row.get("down_share")), 6),
                    "type": str(row.get("type") or ""),
                }
            )

        matches.sort(
            key=lambda item: (
                float(item.get("lift", 0.0) or 0.0),
                int(item.get("support", 0) or 0),
            ),
            reverse=True,
        )
        return matches[:5]

    def _assess_horizon(
        self,
        *,
        horizon: str,
        probabilities: dict[str, float],
        matched_conditions: list[dict[str, Any]],
    ) -> HorizonAssessment:
        up_probability = _safe_float(probabilities.get("up"))
        down_probability = _safe_float(probabilities.get("down"))
        neutral_probability = _safe_float(probabilities.get("neutral"))
        direction = "up" if up_probability >= down_probability else "down"
        direction_probability = up_probability if direction == "up" else down_probability
        direction_edge = direction_probability - neutral_probability
        best_lift = max((_safe_float(item.get("lift"), 1.0) for item in matched_conditions), default=1.0)
        lift_bonus = min(max(best_lift - 1.0, 0.0) * 12.0, 12.0)
        score = min(
            100.0,
            max(0.0, ((direction_probability + max(direction_edge, 0.0)) * 100.0) + lift_bonus),
        )
        return HorizonAssessment(
            horizon=horizon,
            direction=direction,
            direction_probability=round(direction_probability, 6),
            neutral_probability=round(neutral_probability, 6),
            direction_edge=round(direction_edge, 6),
            score=round(score, 2),
            matched_conditions=matched_conditions,
        )

    def _threshold_move_pct(self, row: pd.Series | dict[str, Any], selected: dict[str, Any], base_move_pct: float) -> float:
        atr_pct = max(_safe_float(row.get("atr_pct")), 0.0)
        multiplier = max(_safe_float(selected.get("multiplier"), 0.0), 0.0)
        return max(float(base_move_pct), atr_pct * multiplier)

    def _build_candidate(self, row: pd.Series | dict[str, Any], *, source: str) -> dict[str, Any] | None:
        ticker = str(row.get("symbol") or "").strip().upper()
        if not ticker:
            return None

        spot_symbol = f"US:{ticker}"
        if spot_symbol not in US_SWING_SYMBOLS and ticker not in US_SWING_SECTOR_BY_TICKER:
            return None

        active_conditions = self._active_conditions(row)
        short_matches = self._matched_conditions("short", active_conditions)
        long_matches = self._matched_conditions("long", active_conditions)
        short_probabilities = self._predict_probabilities("short_direction", row)
        long_probabilities = self._predict_probabilities("long_direction", row)
        if not short_probabilities and not long_probabilities:
            return None

        short_assessment = self._assess_horizon(
            horizon="2D",
            probabilities=short_probabilities,
            matched_conditions=short_matches,
        )
        long_assessment = self._assess_horizon(
            horizon="10_15D",
            probabilities=long_probabilities,
            matched_conditions=long_matches,
        )
        primary = long_assessment if long_assessment.score >= short_assessment.score else short_assessment

        short_target = self._selected_targets.get("selected_short", {})
        long_target = self._selected_targets.get("selected_long", {})
        if primary.horizon == "2D":
            move_pct = self._threshold_move_pct(row, short_target, self.config.short_move_pct)
            planned_holding_days = int(self.config.short_horizon_days)
            baseline_hit_rate = _safe_float(short_target.get("positive_rate"))
        else:
            move_pct = self._threshold_move_pct(row, long_target, self.config.long_move_pct)
            planned_holding_days = int(self.config.long_horizon_max_days)
            baseline_hit_rate = _safe_float(long_target.get("positive_rate"))

        price = _safe_float(row.get("close"))
        atr_pct = _safe_float(row.get("atr_pct"))
        if price <= 0:
            return None

        stop_move_pct = max(min(move_pct * 0.5, 0.08), atr_pct * 1.1, 0.02)
        if primary.direction == "up":
            stop_loss = price * (1.0 - stop_move_pct)
            target = price * (1.0 + move_pct)
        else:
            stop_loss = price * (1.0 + stop_move_pct)
            target = price * (1.0 - move_pct)

        market_regime = "neutral"
        if _safe_float(row.get("nifty_bull_regime")) >= 1.0:
            market_regime = "bull"
        elif _safe_float(row.get("nifty_bear_regime")) >= 1.0:
            market_regime = "bear"

        sector = US_SWING_SECTOR_BY_TICKER.get(ticker, str(row.get("sector") or "UNKNOWN"))
        return {
            "symbol": ticker,
            "spot_symbol": spot_symbol,
            "sector": sector,
            "price": round(price, 2),
            "date": str(row.get("date") or ""),
            "source": source,
            "direction": primary.direction,
            "horizon": primary.horizon,
            "score": primary.score,
            "strength": "strong" if primary.score >= 80 else "moderate" if primary.score >= 65 else "weak",
            "direction_probability": primary.direction_probability,
            "neutral_probability": primary.neutral_probability,
            "direction_edge": primary.direction_edge,
            "allow_overnight": True,
            "planned_holding_days": planned_holding_days,
            "expected_move_pct": round(move_pct * 100.0, 2),
            "stop_loss": round(stop_loss, 2),
            "target": round(target, 2),
            "atr_pct": round(atr_pct * 100.0, 2),
            "market_regime": market_regime,
            "baseline_hit_rate": round(baseline_hit_rate * 100.0, 2),
            "matched_conditions": primary.matched_conditions,
            "matched_short_conditions": short_matches,
            "matched_long_conditions": long_matches,
            "short_probabilities": short_probabilities,
            "long_probabilities": long_probabilities,
            "secondary_horizon": {
                "horizon": short_assessment.horizon if primary.horizon == "10_15D" else long_assessment.horizon,
                "score": short_assessment.score if primary.horizon == "10_15D" else long_assessment.score,
            },
        }
