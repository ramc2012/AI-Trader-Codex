"""Offline US swing research pipeline for a broad sector-balanced universe."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
import yfinance as yf

from src.analysis.indicators.momentum import RSI
from src.analysis.indicators.volatility import ATR
from src.config.us_swing_universe import (
    US_SWING_BENCHMARK_TICKER,
    US_SWING_SECTOR_BY_TICKER,
    US_SWING_TICKERS,
)
from src.research.fno_swing_live import load_model_bundle
from src.research.fno_swing_research import (
    ResearchConfig,
    _batched,
    _normalize_price_frame,
    add_swing_targets,
    build_feature_frame,
    choose_target_columns,
    evaluate_conditions,
    select_model_feature_columns,
    train_direction_model,
)
from src.research.paths import resolve_report_dir
from src.utils.logger import get_logger

logger = get_logger(__name__)


def yahoo_us_ticker(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _download_batch(
    symbols: Sequence[str],
    start_date: str,
    end_date: str | None,
) -> tuple[list[pd.DataFrame], list[str]]:
    tickers = [yahoo_us_ticker(symbol) for symbol in symbols]
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
    for symbol, ticker in zip(symbols, tickers, strict=False):
        try:
            symbol_frame = raw[ticker].copy() if isinstance(raw.columns, pd.MultiIndex) else raw.copy()
        except KeyError:
            failures.append(symbol)
            continue

        normalized = _normalize_price_frame(
            symbol_frame,
            symbol,
            ticker=ticker,
            sector=US_SWING_SECTOR_BY_TICKER.get(symbol, "UNKNOWN"),
        )
        if normalized.empty:
            failures.append(symbol)
            continue
        frames.append(normalized)

    return frames, failures


def download_history(
    symbols: Sequence[str],
    config: ResearchConfig,
) -> tuple[pd.DataFrame, dict[str, Any]]:
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
        raise RuntimeError("No historical data downloaded for the US swing universe.")

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


def download_spy_regime(config: ResearchConfig) -> pd.DataFrame:
    raw = yf.download(
        tickers=US_SWING_BENCHMARK_TICKER,
        start=config.start_date,
        end=config.end_date,
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    normalized = _normalize_price_frame(
        raw,
        "SPY_BENCH",
        ticker=US_SWING_BENCHMARK_TICKER,
        sector="INDEX",
    )
    if normalized.empty:
        raise RuntimeError("Failed to download SPY benchmark history.")

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
    # Kept on the same column names as the NSE pipeline so the
    # shared feature engineering and live scorers can be reused.
    regime["nifty_return_5"] = close.pct_change(5)
    regime["nifty_return_20"] = close.pct_change(20)
    regime["nifty_rsi_14"] = rsi_14
    regime["nifty_atr_pct"] = atr_14 / close.replace(0, np.nan)
    regime["nifty_trend_bias"] = (ema_20 / ema_50) - 1.0
    regime["nifty_above_ema50"] = (close > ema_50).astype(float)
    regime["nifty_bull_regime"] = ((close > ema_50) & (rsi_14 >= 55)).astype(float)
    regime["nifty_bear_regime"] = ((close < ema_50) & (rsi_14 <= 45)).astype(float)
    return regime


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if not np.isfinite(numeric):
        return default
    return numeric


def _batch_probabilities(
    *,
    report_dir: Path,
    target_name: str,
    dataset: pd.DataFrame,
) -> dict[str, np.ndarray]:
    bundle = load_model_bundle(str(report_dir), target_name)
    model = bundle.get("model")
    feature_columns = list(bundle.get("feature_columns", []) or [])
    if model is None or not feature_columns:
        length = len(dataset)
        return {
            "up": np.zeros(length, dtype=float),
            "down": np.zeros(length, dtype=float),
            "neutral": np.zeros(length, dtype=float),
        }

    medians = pd.Series(bundle.get("feature_medians", {}), dtype=float)
    frame = dataset.reindex(columns=feature_columns).replace([np.inf, -np.inf], np.nan)
    frame = frame.fillna(medians).fillna(0.0)
    probabilities = model.predict_proba(frame)
    classes = [str(value) for value in getattr(model, "classes_", [])]
    result = {
        "up": np.zeros(len(frame), dtype=float),
        "down": np.zeros(len(frame), dtype=float),
        "neutral": np.zeros(len(frame), dtype=float),
    }
    for index, label in enumerate(classes):
        if label in result:
            result[label] = probabilities[:, index]
    return result


def _summarize_backtest(
    trades: list[dict[str, Any]],
    *,
    min_score: float,
    min_probability: float,
    min_edge: float,
) -> dict[str, Any]:
    if not trades:
        return {
            "min_score": min_score,
            "min_probability": min_probability,
            "min_edge": min_edge,
            "trades": 0,
            "win_rate_pct": 0.0,
            "avg_return_pct": 0.0,
            "median_return_pct": 0.0,
            "total_return_pct": 0.0,
            "sharpe": 0.0,
            "max_drawdown_pct": 0.0,
            "objective": -1_000_000.0,
        }

    returns = np.asarray([float(trade["return_pct"]) / 100.0 for trade in trades], dtype=float)
    trades_count = int(len(returns))
    wins = int(np.sum(returns > 0))
    mean_return = float(np.mean(returns))
    median_return = float(np.median(returns))
    total_return = float(np.sum(returns))
    std_return = float(np.std(returns, ddof=1)) if trades_count > 1 else 0.0
    sharpe = (mean_return / std_return * np.sqrt(252.0)) if std_return > 0 else 0.0

    equity = np.cumsum(returns)
    peaks = np.maximum.accumulate(equity) if len(equity) else np.array([], dtype=float)
    drawdowns = (peaks - equity) if len(equity) else np.array([], dtype=float)
    max_drawdown_pct = float(drawdowns.max() * 100.0) if len(drawdowns) else 0.0
    win_rate_pct = (wins / trades_count) * 100.0

    objective = (
        (mean_return * 100.0) * (1.0 + np.log1p(trades_count) / 6.0)
        + max(sharpe, 0.0) * 0.75
        + win_rate_pct * 0.03
        - max_drawdown_pct * 0.05
    )
    if trades_count < 40:
        objective -= 25.0

    return {
        "min_score": round(float(min_score), 2),
        "min_probability": round(float(min_probability), 4),
        "min_edge": round(float(min_edge), 4),
        "trades": trades_count,
        "win_rate_pct": round(win_rate_pct, 2),
        "avg_return_pct": round(mean_return * 100.0, 3),
        "median_return_pct": round(median_return * 100.0, 3),
        "total_return_pct": round(total_return * 100.0, 2),
        "sharpe": round(float(sharpe), 3),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "objective": round(float(objective), 3),
    }


def tune_live_filters(
    *,
    report_dir: Path,
    dataset: pd.DataFrame,
    config: ResearchConfig,
    selected_targets: dict[str, Any],
) -> dict[str, Any]:
    dated = dataset.copy()
    dated["date"] = pd.to_datetime(dated["date"], errors="coerce")
    dated = dated.dropna(subset=["date"]).sort_values(["date", "symbol"]).reset_index(drop=True)
    if dated.empty:
        return {}

    cutoff = dated["date"].quantile(config.model_train_fraction)
    test_rows = dated.loc[dated["date"] > cutoff].copy()
    if test_rows.empty:
        return {}

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

    if candidate_rows.empty:
        return {}

    score_grid = (60.0, 65.0, 70.0, 75.0, 80.0)
    probability_grid = (0.42, 0.45, 0.48, 0.52)
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

    ranked = sorted(
        results,
        key=lambda row: (float(row["objective"]), int(row["trades"]), float(row["avg_return_pct"])),
        reverse=True,
    )
    best = ranked[0] if ranked else {}
    return {
        "candidate_rows": int(len(candidate_rows)),
        "test_rows": int(len(test_rows)),
        "test_start": str(test_rows["date"].min().date()),
        "best_filters": best,
        "top_filters": ranked[:10],
    }


def render_report(summary: dict[str, Any]) -> str:
    short_selection = summary["selected_targets"]["selected_short"]
    long_selection = summary["selected_targets"]["selected_long"]
    short_conditions = summary["top_conditions"]["short"][:8]
    long_conditions = summary["top_conditions"]["long"][:8]
    short_model = summary["models"]["short_direction"]
    long_model = summary["models"]["long_direction"]
    tuning = summary.get("tuning", {})
    best_filters = tuning.get("best_filters", {})

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

    tuning_lines = "- tuning unavailable"
    if best_filters:
        tuning_lines = (
            f"- Best live filters: score >= `{best_filters['min_score']}`, "
            f"direction probability >= `{best_filters['min_probability']}`, "
            f"direction edge >= `{best_filters['min_edge']}`\n"
            f"- Test trades: `{best_filters['trades']}`, "
            f"win rate `{best_filters['win_rate_pct']:.2f}%`, "
            f"avg return `{best_filters['avg_return_pct']:.3f}%`, "
            f"total return `{best_filters['total_return_pct']:.2f}%`, "
            f"Sharpe `{best_filters['sharpe']:.3f}`"
        )

    return (
        "# US Swing Research\n\n"
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
        "## Tuned Live Filters\n\n"
        f"{tuning_lines}\n\n"
        "### Top Short-Horizon Features\n\n"
        f"{format_features(short_model['top_features'])}\n\n"
        "### Top Long-Horizon Features\n\n"
        f"{format_features(long_model['top_features'])}\n"
    )


@dataclass
class USSwingResearchRunner:
    """Coordinator for the full US swing research workflow."""

    config: ResearchConfig = field(default_factory=ResearchConfig)

    def run(self, symbols: Sequence[str] | None = None) -> dict[str, Any]:
        selected_symbols = list(symbols or US_SWING_TICKERS)
        logger.info("us_swing_research_start", symbols=len(selected_symbols))

        history, download_meta = download_history(selected_symbols, self.config)
        regime = download_spy_regime(self.config)

        enriched_frames: list[pd.DataFrame] = []
        for symbol, group in history.groupby("symbol"):
            if len(group) < self.config.min_history_days:
                continue
            features = build_feature_frame(group.copy(), regime, self.config)
            labeled = add_swing_targets(features, self.config)
            labeled["date"] = labeled.index
            enriched_frames.append(labeled)

        if not enriched_frames:
            raise RuntimeError("No US symbol had enough history after feature engineering.")

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

        explicit_report_dir = self.config.report_dir
        if explicit_report_dir == "tmp/fno_swing_research":
            explicit_report_dir = None
        report_dir = resolve_report_dir(
            explicit_report_dir,
            folder_name="us_swing",
            legacy_fallback="tmp/us_swing_research_full",
        )
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
            "config": {
                **asdict(self.config),
                "report_dir": str(report_dir),
                "benchmark_ticker": US_SWING_BENCHMARK_TICKER,
                "universe_size": len(selected_symbols),
            },
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
        summary["tuning"] = tune_live_filters(
            report_dir=report_dir,
            dataset=model_dataset,
            config=self.config,
            selected_targets=selected_targets,
        )
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        report_path.write_text(render_report(summary), encoding="utf-8")
        logger.info("us_swing_research_complete", rows=len(dataset), report=str(report_path))
        return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run US swing research over long-history daily data.")
    parser.add_argument("--start-date", default="2016-01-01")
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--limit", type=int, default=None, help="Limit symbol count for quicker runs.")
    parser.add_argument(
        "--report-dir",
        default="data/research/us_swing",
        help="Directory to write dataset, conditions, models, and report.",
    )
    parser.add_argument(
        "--min-history-days",
        type=int,
        default=750,
        help="Minimum daily bars required per symbol after download.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    config = ResearchConfig(
        start_date=args.start_date,
        end_date=args.end_date,
        report_dir=args.report_dir,
        min_history_days=args.min_history_days,
    )
    runner = USSwingResearchRunner(config=config)
    symbols = None
    if args.limit is not None:
        symbols = US_SWING_TICKERS[: max(args.limit, 1)]
    summary = runner.run(symbols=symbols)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
