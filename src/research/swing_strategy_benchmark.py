"""Benchmark FnO and US swing strategy research thresholds."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.research.fno_swing_live import (
    DEFAULT_FNO_SWING_REPORT_DIR,
    load_research_config as load_fno_research_config,
    load_research_summary as load_fno_research_summary,
)
from src.research.paths import resolve_report_dir
from src.research.us_swing_live import (
    DEFAULT_US_SWING_REPORT_DIR,
    load_research_config as load_us_research_config,
    load_research_summary as load_us_research_summary,
)
from src.research.us_swing_research import _batch_probabilities, _summarize_backtest


DEFAULT_REPORT_DIR = resolve_report_dir(
    None,
    folder_name="swing_benchmarks",
    legacy_fallback="tmp/swing_benchmarks",
)


def _research_loaders(strategy_name: str) -> tuple[Any, Any]:
    if str(strategy_name) == "US_Swing_Radar":
        return load_us_research_summary, load_us_research_config
    return load_fno_research_summary, load_fno_research_config


@dataclass(frozen=True)
class SwingBenchmarkConfig:
    report_dir: str = str(DEFAULT_REPORT_DIR)
    fno_report_dir: str = str(DEFAULT_FNO_SWING_REPORT_DIR)
    us_report_dir: str = str(DEFAULT_US_SWING_REPORT_DIR)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if not np.isfinite(numeric):
        return default
    return numeric


def _candidate_rows(
    *,
    report_dir: Path,
    strategy_name: str,
    min_score: float,
    min_probability: float,
    min_edge: float,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    load_summary, load_config = _research_loaders(strategy_name)
    summary = load_summary(str(report_dir))
    config = load_config(str(report_dir))
    dataset_path = report_dir / "labeled_dataset.csv.gz"
    dataset = pd.read_csv(dataset_path, compression="gzip", low_memory=False)
    dataset["date"] = pd.to_datetime(dataset["date"], errors="coerce")
    dataset = dataset.dropna(subset=["date"]).sort_values(["date", "symbol"]).reset_index(drop=True)
    cutoff = dataset["date"].quantile(config.model_train_fraction)
    test_rows = dataset.loc[dataset["date"] > cutoff].copy()
    selected_targets = summary.get("selected_targets", {})

    short_probabilities = _batch_probabilities(
        report_dir=report_dir,
        target_name="short_direction",
        dataset=test_rows,
    )
    long_probabilities = _batch_probabilities(
        report_dir=report_dir,
        target_name="long_direction",
        dataset=test_rows,
    )

    short_direction = np.where(short_probabilities["up"] >= short_probabilities["down"], "up", "down")
    long_direction = np.where(long_probabilities["up"] >= long_probabilities["down"], "up", "down")
    short_direction_probability = np.maximum(short_probabilities["up"], short_probabilities["down"])
    long_direction_probability = np.maximum(long_probabilities["up"], long_probabilities["down"])
    short_edge = short_direction_probability - short_probabilities["neutral"]
    long_edge = long_direction_probability - long_probabilities["neutral"]
    short_score = np.clip((short_direction_probability + np.maximum(short_edge, 0.0)) * 100.0, 0.0, 100.0)
    long_score = np.clip((long_direction_probability + np.maximum(long_edge, 0.0)) * 100.0, 0.0, 100.0)
    use_long = long_score >= short_score

    atr_pct = pd.to_numeric(test_rows["atr_pct"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    short_multiplier = float(selected_targets.get("selected_short", {}).get("multiplier", 1.5) or 1.5)
    long_multiplier = float(selected_targets.get("selected_long", {}).get("multiplier", 3.5) or 3.5)
    short_move = np.maximum(float(config.short_move_pct), atr_pct * short_multiplier)
    long_move = np.maximum(float(config.long_move_pct), atr_pct * long_multiplier)
    move_pct = np.where(use_long, long_move, short_move)
    stop_move = np.maximum(np.minimum(move_pct * 0.5, 0.08), np.maximum(atr_pct * 1.1, 0.02))

    future_return_2d = pd.to_numeric(test_rows["future_return_2d"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    future_return_10d = pd.to_numeric(test_rows["future_return_10d"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    future_return_15d = pd.to_numeric(test_rows["future_return_15d"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    long_terminal_up = np.maximum(future_return_10d, future_return_15d)
    long_terminal_down = np.minimum(future_return_10d, future_return_15d)
    direction = np.where(use_long, long_direction, short_direction)
    terminal_return = np.where(use_long, long_terminal_up, future_return_2d)
    terminal_return = np.where((direction == "down") & use_long, long_terminal_down, terminal_return)
    directional_return = np.where(direction == "up", terminal_return, -terminal_return)
    realized_return_pct = np.minimum(directional_return, move_pct)
    realized_return_pct = np.maximum(realized_return_pct, -stop_move) * 100.0

    candidate_rows = pd.DataFrame(
        {
            "strategy": strategy_name,
            "date": test_rows["date"].dt.date.astype(str),
            "symbol": test_rows["symbol"].astype(str),
            "score": np.where(use_long, long_score, short_score),
            "direction_probability": np.where(use_long, long_direction_probability, short_direction_probability),
            "direction_edge": np.where(use_long, long_edge, short_edge),
            "horizon": np.where(use_long, "10_15D", "2D"),
            "return_pct": realized_return_pct,
        }
    )
    filtered = candidate_rows.loc[
        (candidate_rows["score"] >= min_score)
        & (candidate_rows["direction_probability"] >= min_probability)
        & (candidate_rows["direction_edge"] >= min_edge)
    ].reset_index(drop=True)
    meta = {
        "report_dir": str(report_dir),
        "dataset_rows": int(len(dataset)),
        "test_rows": int(len(test_rows)),
        "test_start": str(test_rows["date"].min().date()) if not test_rows.empty else None,
        "current_thresholds": {
            "min_score": min_score,
            "min_probability": min_probability,
            "min_edge": min_edge,
        },
    }
    return filtered, meta


def _symbol_metrics(candidates: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame(
            columns=["symbol", "trades", "win_rate_pct", "avg_return_pct", "median_return_pct", "total_return_pct"]
        )
    rows: list[dict[str, Any]] = []
    for symbol, group in candidates.groupby("symbol", sort=True):
        returns = pd.to_numeric(group["return_pct"], errors="coerce").fillna(0.0)
        rows.append(
            {
                "symbol": symbol,
                "trades": int(len(group)),
                "win_rate_pct": round(float((returns > 0).mean() * 100.0), 2),
                "avg_return_pct": round(float(returns.mean()), 4),
                "median_return_pct": round(float(returns.median()), 4),
                "total_return_pct": round(float(returns.sum()), 4),
            }
        )
    return pd.DataFrame(rows).sort_values("total_return_pct", ascending=False).reset_index(drop=True)


def _grid_tune(report_dir: Path) -> list[dict[str, Any]]:
    strategy_name = "US_Swing_Radar" if "us_swing" in str(report_dir).lower() else "FnO_Swing_Radar"
    load_summary, load_config = _research_loaders(strategy_name)
    summary = load_summary(str(report_dir))
    config = load_config(str(report_dir))
    dataset_path = report_dir / "labeled_dataset.csv.gz"
    dataset = pd.read_csv(dataset_path, compression="gzip", low_memory=False)
    dataset["date"] = pd.to_datetime(dataset["date"], errors="coerce")
    dataset = dataset.dropna(subset=["date"]).sort_values(["date", "symbol"]).reset_index(drop=True)
    selected_targets = summary.get("selected_targets", {})

    cutoff = dataset["date"].quantile(config.model_train_fraction)
    test_rows = dataset.loc[dataset["date"] > cutoff].copy()
    short_probabilities = _batch_probabilities(report_dir=report_dir, target_name="short_direction", dataset=test_rows)
    long_probabilities = _batch_probabilities(report_dir=report_dir, target_name="long_direction", dataset=test_rows)
    short_direction = np.where(short_probabilities["up"] >= short_probabilities["down"], "up", "down")
    long_direction = np.where(long_probabilities["up"] >= long_probabilities["down"], "up", "down")
    short_direction_probability = np.maximum(short_probabilities["up"], short_probabilities["down"])
    long_direction_probability = np.maximum(long_probabilities["up"], long_probabilities["down"])
    short_edge = short_direction_probability - short_probabilities["neutral"]
    long_edge = long_direction_probability - long_probabilities["neutral"]
    short_score = np.clip((short_direction_probability + np.maximum(short_edge, 0.0)) * 100.0, 0.0, 100.0)
    long_score = np.clip((long_direction_probability + np.maximum(long_edge, 0.0)) * 100.0, 0.0, 100.0)
    use_long = long_score >= short_score

    atr_pct = pd.to_numeric(test_rows["atr_pct"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    short_multiplier = float(selected_targets.get("selected_short", {}).get("multiplier", 1.5) or 1.5)
    long_multiplier = float(selected_targets.get("selected_long", {}).get("multiplier", 3.5) or 3.5)
    short_move = np.maximum(float(config.short_move_pct), atr_pct * short_multiplier)
    long_move = np.maximum(float(config.long_move_pct), atr_pct * long_multiplier)
    move_pct = np.where(use_long, long_move, short_move)
    stop_move = np.maximum(np.minimum(move_pct * 0.5, 0.08), np.maximum(atr_pct * 1.1, 0.02))

    future_return_2d = pd.to_numeric(test_rows["future_return_2d"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    future_return_10d = pd.to_numeric(test_rows["future_return_10d"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    future_return_15d = pd.to_numeric(test_rows["future_return_15d"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    long_terminal = np.maximum(future_return_10d, future_return_15d)
    long_terminal_down = np.minimum(future_return_10d, future_return_15d)
    direction = np.where(use_long, long_direction, short_direction)
    terminal_return = np.where(use_long, long_terminal, future_return_2d)
    terminal_return = np.where((direction == "down") & use_long, long_terminal_down, terminal_return)
    directional_return = np.where(direction == "up", terminal_return, -terminal_return)
    realized_return_pct = np.minimum(directional_return, move_pct)
    realized_return_pct = np.maximum(realized_return_pct, -stop_move) * 100.0

    candidate_rows = pd.DataFrame(
        {
            "date": test_rows["date"].dt.date.astype(str),
            "symbol": test_rows["symbol"].astype(str),
            "score": np.where(use_long, long_score, short_score),
            "direction_probability": np.where(use_long, long_direction_probability, short_direction_probability),
            "direction_edge": np.where(use_long, long_edge, short_edge),
            "return_pct": realized_return_pct,
        }
    )

    score_grid = (60.0, 65.0, 70.0, 72.0, 75.0, 80.0)
    probability_grid = (0.42, 0.44, 0.46, 0.48, 0.52)
    edge_grid = (0.04, 0.06, 0.08, 0.10, 0.12)
    results: list[dict[str, Any]] = []
    for min_score in score_grid:
        for min_probability in probability_grid:
            for min_edge in edge_grid:
                filtered = candidate_rows.loc[
                    (candidate_rows["score"] >= min_score)
                    & (candidate_rows["direction_probability"] >= min_probability)
                    & (candidate_rows["direction_edge"] >= min_edge)
                ]
                trades = filtered.to_dict(orient="records")
                results.append(
                    _summarize_backtest(
                        trades,
                        min_score=min_score,
                        min_probability=min_probability,
                        min_edge=min_edge,
                    )
                )
    return sorted(results, key=lambda row: (float(row["objective"]), int(row["trades"])), reverse=True)


class SwingStrategyBenchmarkRunner:
    def __init__(self, config: SwingBenchmarkConfig) -> None:
        self.config = config

    def run(self) -> dict[str, Any]:
        report_dir = Path(self.config.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)

        strategy_configs = {
            "FnO_Swing_Radar": {
                "report_dir": Path(self.config.fno_report_dir),
                "thresholds": {"min_score": 72.0, "min_probability": 0.44, "min_edge": 0.08},
            },
            "US_Swing_Radar": {
                "report_dir": Path(self.config.us_report_dir),
                "thresholds": {"min_score": 60.0, "min_probability": 0.42, "min_edge": 0.04},
            },
        }

        summary_rows: list[dict[str, Any]] = []
        top_tuning: dict[str, Any] = {}

        for strategy_name, payload in strategy_configs.items():
            thresholds = payload["thresholds"]
            candidates, meta = _candidate_rows(
                report_dir=payload["report_dir"],
                strategy_name=strategy_name,
                min_score=float(thresholds["min_score"]),
                min_probability=float(thresholds["min_probability"]),
                min_edge=float(thresholds["min_edge"]),
            )
            symbol_metrics = _symbol_metrics(candidates)
            symbol_path = report_dir / f"{strategy_name.lower()}_symbol_metrics.csv"
            candidate_path = report_dir / f"{strategy_name.lower()}_candidates.csv"
            candidates.to_csv(candidate_path, index=False)
            symbol_metrics.to_csv(symbol_path, index=False)

            benchmark = _summarize_backtest(
                candidates.to_dict(orient="records"),
                min_score=float(thresholds["min_score"]),
                min_probability=float(thresholds["min_probability"]),
                min_edge=float(thresholds["min_edge"]),
            )
            benchmark.update(
                {
                    "strategy": strategy_name,
                    "tested_symbols": int(candidates["symbol"].nunique()) if not candidates.empty else 0,
                    "profitable_symbols": int((symbol_metrics["total_return_pct"] > 0).sum()) if not symbol_metrics.empty else 0,
                    "profitable_symbol_pct": round(
                        float((symbol_metrics["total_return_pct"] > 0).mean() * 100.0) if not symbol_metrics.empty else 0.0,
                        2,
                    ),
                    "top_symbol": str(symbol_metrics.iloc[0]["symbol"]) if not symbol_metrics.empty else "",
                    "top_symbol_return_pct": round(float(symbol_metrics.iloc[0]["total_return_pct"]), 4) if not symbol_metrics.empty else 0.0,
                    "bottom_symbol": str(symbol_metrics.iloc[-1]["symbol"]) if not symbol_metrics.empty else "",
                    "bottom_symbol_return_pct": round(float(symbol_metrics.iloc[-1]["total_return_pct"]), 4) if not symbol_metrics.empty else 0.0,
                    "meta": meta,
                    "artifacts": {
                        "candidates": str(candidate_path),
                        "symbol_metrics": str(symbol_path),
                    },
                }
            )
            summary_rows.append(benchmark)
            top_tuning[strategy_name] = _grid_tune(payload["report_dir"])[:10]

        summary_df = pd.DataFrame(summary_rows)
        summary_path = report_dir / "swing_strategy_summary.csv"
        tuning_path = report_dir / "top_thresholds.json"
        detail_path = report_dir / "summary.json"

        summary_df.to_csv(summary_path, index=False)
        tuning_path.write_text(json.dumps(top_tuning, indent=2), encoding="utf-8")
        detail_path.write_text(json.dumps(summary_rows, indent=2), encoding="utf-8")
        return {
            "config": asdict(self.config),
            "artifacts": {
                "summary": str(summary_path),
                "top_thresholds": str(tuning_path),
                "detail": str(detail_path),
            },
            "summary": summary_rows,
            "top_thresholds": top_tuning,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark FnO and US swing strategy research thresholds.")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--fno-report-dir", default=str(DEFAULT_FNO_SWING_REPORT_DIR))
    parser.add_argument("--us-report-dir", default=str(DEFAULT_US_SWING_REPORT_DIR))
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    result = SwingStrategyBenchmarkRunner(
        config=SwingBenchmarkConfig(
            report_dir=args.report_dir,
            fno_report_dir=args.fno_report_dir,
            us_report_dir=args.us_report_dir,
        )
    ).run()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
