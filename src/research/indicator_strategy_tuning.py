"""Daily tuning study for indicator-based strategies."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from src.analysis.indicators import ATR, MACD, RSI
from src.config.fno_constants import FNO_SYMBOLS
from src.config.us_swing_universe import US_SWING_TICKERS
from src.research.fno_swing_research import ResearchConfig as FnOResearchConfig
from src.research.fno_swing_research import download_history as download_nse_history
from src.research.paths import resolve_report_dir
from src.research.us_swing_research import ResearchConfig as USResearchConfig
from src.research.us_swing_research import download_history as download_us_history
from src.strategies.backtester import Backtester
from src.strategies.directional.macd_strategy import MACDStrategy
from src.strategies.directional.rsi_reversal import RSIReversalStrategy
from src.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_REPORT_DIR = resolve_report_dir(
    None,
    folder_name="indicator_tuning",
    legacy_fallback="tmp/indicator_tuning",
)


@dataclass(frozen=True)
class IndicatorTuningConfig:
    start_date: str = "2016-01-01"
    end_date: str | None = None
    min_history_days: int = 252
    trade_notional: float = 10_000.0
    initial_capital: float = 100_000.0
    slippage_pct: float = 0.05
    report_dir: str = str(DEFAULT_REPORT_DIR)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    return value


def _market_history(
    *,
    market: str,
    config: IndicatorTuningConfig,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    market_key = str(market or "").strip().upper()
    if market_key == "NSE":
        history, meta = download_nse_history(
            FNO_SYMBOLS,
            FnOResearchConfig(
                start_date=config.start_date,
                end_date=config.end_date,
                min_history_days=config.min_history_days,
            ),
        )
    elif market_key == "US":
        history, meta = download_us_history(
            US_SWING_TICKERS,
            USResearchConfig(
                start_date=config.start_date,
                end_date=config.end_date,
                min_history_days=config.min_history_days,
            ),
        )
    else:
        raise ValueError(f"Unsupported market: {market}")

    frame = history.reset_index().rename(columns={"date": "timestamp"})
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    frame = frame.dropna(subset=["timestamp"]).sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    return frame, meta


def _iter_symbol_frames(history: pd.DataFrame, min_history_days: int) -> list[tuple[str, pd.DataFrame]]:
    frames: list[tuple[str, pd.DataFrame]] = []
    for symbol, group in history.groupby("symbol", sort=True):
        ordered = group.sort_values("timestamp").reset_index(drop=True)
        if len(ordered) >= min_history_days:
            frames.append((str(symbol), ordered))
    return frames


def _summarize_strategy_runs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return {
            "tested_symbols": 0,
            "profitable_symbols": 0,
            "profitable_symbol_pct": 0.0,
            "trade_count": 0,
            "win_rate_pct": 0.0,
            "avg_trade_return_pct": 0.0,
            "mean_symbol_return_pct": 0.0,
            "median_symbol_return_pct": 0.0,
            "total_pnl": 0.0,
        }

    trade_count = int(frame["trade_count"].sum())
    weighted_trade_return = 0.0
    if trade_count > 0:
        weighted_trade_return = float((frame["avg_trade_return_pct"] * frame["trade_count"]).sum() / trade_count)
    return {
        "tested_symbols": int(len(frame)),
        "profitable_symbols": int((frame["total_return_pct"] > 0).sum()),
        "profitable_symbol_pct": round(float((frame["total_return_pct"] > 0).mean() * 100.0), 2),
        "trade_count": trade_count,
        "win_rate_pct": round(
            float((frame["win_rate_pct"] * frame["trade_count"]).sum() / trade_count) if trade_count else 0.0,
            2,
        ),
        "avg_trade_return_pct": round(weighted_trade_return, 4),
        "mean_symbol_return_pct": round(float(frame["total_return_pct"].mean()), 4),
        "median_symbol_return_pct": round(float(frame["total_return_pct"].median()), 4),
        "total_pnl": round(float(frame["total_pnl"].sum()), 4),
    }


def _evaluate_variant(
    *,
    market: str,
    variant_name: str,
    strategy_factory: Callable[[], Any],
    symbol_frames: list[tuple[str, pd.DataFrame]],
    config: IndicatorTuningConfig,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    symbol_rows: list[dict[str, Any]] = []
    for symbol, frame in symbol_frames:
        first_close = float(pd.to_numeric(frame["close"], errors="coerce").dropna().iloc[0])
        quantity = max(1, int(config.trade_notional / max(first_close, 1e-6)))
        result = Backtester(
            strategy=strategy_factory(),
            initial_capital=config.initial_capital,
            quantity=quantity,
            commission=0.0,
            slippage_pct=config.slippage_pct,
            exit_on_eod=False,
        ).run(frame, symbol=symbol)
        trade_count = int(result.total_trades)
        avg_trade_return = float(result.total_pnl / trade_count / max(quantity * first_close, 1e-6) * 100.0) if trade_count else 0.0
        symbol_rows.append(
            {
                "market": market,
                "variant": variant_name,
                "symbol": symbol,
                "trade_count": trade_count,
                "win_rate_pct": round(float(result.win_rate), 4),
                "avg_trade_return_pct": round(avg_trade_return, 4),
                "total_pnl": round(float(result.total_pnl), 4),
                "total_return_pct": round(float(result.total_return_pct), 4),
                "max_drawdown_pct": round(float(result.max_drawdown), 4),
                "profit_factor": round(float(result.profit_factor), 4),
            }
        )

    summary = _summarize_strategy_runs(symbol_rows)
    summary.update(
        {
            "market": market,
            "variant": variant_name,
        }
    )
    return summary, symbol_rows


def _macd_variants() -> list[tuple[str, Callable[[], MACDStrategy]]]:
    return [
        (
            "macd_base_current",
            lambda: MACDStrategy(
                rsi_filter=50.0,
                atr_sl_multiplier=2.0,
                risk_reward_ratio=2.0,
            ),
        ),
        (
            "macd_base_tighter",
            lambda: MACDStrategy(
                rsi_filter=52.0,
                atr_sl_multiplier=1.5,
                risk_reward_ratio=2.2,
            ),
        ),
        (
            "macd_zero_align_current",
            lambda: MACDStrategy(
                rsi_filter=50.0,
                atr_sl_multiplier=2.0,
                risk_reward_ratio=2.0,
                zero_line_mode="aligned",
            ),
        ),
        (
            "macd_zero_near_current",
            lambda: MACDStrategy(
                rsi_filter=50.0,
                atr_sl_multiplier=2.0,
                risk_reward_ratio=2.0,
                zero_line_mode="near_or_aligned",
                max_zero_line_distance_atr=0.25,
            ),
        ),
        (
            "macd_zero_align_tighter",
            lambda: MACDStrategy(
                rsi_filter=52.0,
                atr_sl_multiplier=1.5,
                risk_reward_ratio=2.2,
                zero_line_mode="aligned",
            ),
        ),
        (
            "macd_zero_near_tighter",
            lambda: MACDStrategy(
                rsi_filter=52.0,
                atr_sl_multiplier=1.5,
                risk_reward_ratio=2.2,
                zero_line_mode="near_or_aligned",
                max_zero_line_distance_atr=0.25,
            ),
        ),
    ]


def _rsi_variants() -> list[tuple[str, Callable[[], RSIReversalStrategy]]]:
    return [
        (
            "rsi_base_current",
            lambda: RSIReversalStrategy(
                oversold=30.0,
                overbought=70.0,
                atr_sl_multiplier=1.5,
                risk_reward_ratio=2.0,
                require_volume_surge=True,
                volume_surge_multiplier=1.5,
            ),
        ),
        (
            "rsi_no_volume_current",
            lambda: RSIReversalStrategy(
                oversold=30.0,
                overbought=70.0,
                atr_sl_multiplier=1.5,
                risk_reward_ratio=2.0,
                require_volume_surge=False,
            ),
        ),
        (
            "rsi_no_volume_32_68",
            lambda: RSIReversalStrategy(
                oversold=32.0,
                overbought=68.0,
                atr_sl_multiplier=1.25,
                risk_reward_ratio=1.5,
                require_volume_surge=False,
            ),
        ),
        (
            "rsi_no_volume_35_65",
            lambda: RSIReversalStrategy(
                oversold=35.0,
                overbought=65.0,
                atr_sl_multiplier=1.25,
                risk_reward_ratio=1.5,
                require_volume_surge=False,
            ),
        ),
        (
            "rsi_volume_32_68",
            lambda: RSIReversalStrategy(
                oversold=32.0,
                overbought=68.0,
                atr_sl_multiplier=1.25,
                risk_reward_ratio=1.5,
                require_volume_surge=True,
                volume_surge_multiplier=1.2,
            ),
        ),
    ]


def _macd_zero_line_study(symbol_frames: list[tuple[str, pd.DataFrame]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    macd_indicator = MACD(fast_period=12, slow_period=26, signal_period=9)
    rsi_indicator = RSI(period=14)
    atr_indicator = ATR(period=14)
    near_threshold = 0.25

    for symbol, frame in symbol_frames:
        close = frame["close"].astype(float)
        high = frame["high"].astype(float)
        low = frame["low"].astype(float)
        macd_df = macd_indicator.calculate(close)
        rsi = rsi_indicator.calculate(close)
        atr = atr_indicator.calculate(close, high=high, low=low)
        macd_line = macd_df["macd"]
        signal_line = macd_df["signal"]

        for index in range(1, len(frame) - 1):
            if any(
                pd.isna(series.iloc[index])
                for series in (macd_line, signal_line, rsi, atr)
            ) or any(pd.isna(series.iloc[index - 1]) for series in (macd_line, signal_line)):
                continue
            prev_diff = float(macd_line.iloc[index - 1] - signal_line.iloc[index - 1])
            curr_diff = float(macd_line.iloc[index] - signal_line.iloc[index])
            curr_macd = float(macd_line.iloc[index])
            curr_rsi = float(rsi.iloc[index])
            curr_atr = float(atr.iloc[index])
            if curr_atr <= 0:
                continue

            category = None
            direction = None
            if prev_diff <= 0 and curr_diff > 0 and curr_rsi > 50.0:
                direction = "BUY"
                if curr_macd >= 0:
                    category = "buy_above_zero"
                elif abs(curr_macd) / curr_atr <= near_threshold:
                    category = "buy_near_zero_below"
                else:
                    category = "buy_far_below_zero"
            elif prev_diff >= 0 and curr_diff < 0 and curr_rsi < 50.0:
                direction = "SELL"
                if curr_macd <= 0:
                    category = "sell_below_zero"
                elif abs(curr_macd) / curr_atr <= near_threshold:
                    category = "sell_near_zero_above"
                else:
                    category = "sell_far_above_zero"

            if category is None or direction is None:
                continue

            price = float(close.iloc[index])
            next_close = float(close.iloc[index + 1])
            forward_5 = frame.iloc[index + 1 : index + 6]["close"].astype(float)
            if forward_5.empty:
                continue
            terminal_close = float(forward_5.iloc[-1])
            if direction == "BUY":
                one_bar_return = ((next_close / price) - 1.0) * 100.0
                five_bar_return = ((terminal_close / price) - 1.0) * 100.0
            else:
                one_bar_return = ((price / next_close) - 1.0) * 100.0
                five_bar_return = ((price / terminal_close) - 1.0) * 100.0

            rows.append(
                {
                    "symbol": symbol,
                    "category": category,
                    "direction": direction,
                    "macd_value": curr_macd,
                    "macd_atr_ratio": curr_macd / curr_atr,
                    "rsi": curr_rsi,
                    "one_bar_return_pct": one_bar_return,
                    "five_bar_return_pct": five_bar_return,
                }
            )

    study = pd.DataFrame(rows)
    if study.empty:
        return study
    grouped = []
    for category, group in study.groupby("category", sort=True):
        grouped.append(
            {
                "category": category,
                "signals": int(len(group)),
                "avg_one_bar_return_pct": round(float(group["one_bar_return_pct"].mean()), 4),
                "median_one_bar_return_pct": round(float(group["one_bar_return_pct"].median()), 4),
                "avg_five_bar_return_pct": round(float(group["five_bar_return_pct"].mean()), 4),
                "median_five_bar_return_pct": round(float(group["five_bar_return_pct"].median()), 4),
                "positive_five_bar_pct": round(float((group["five_bar_return_pct"] > 0).mean() * 100.0), 2),
            }
        )
    return pd.DataFrame(grouped).sort_values("avg_five_bar_return_pct", ascending=False).reset_index(drop=True)


class IndicatorStrategyTuningRunner:
    def __init__(self, config: IndicatorTuningConfig) -> None:
        self.config = config

    def run(self, markets: list[str]) -> dict[str, Any]:
        report_dir = Path(self.config.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)

        summary_rows: list[dict[str, Any]] = []
        symbol_rows: list[dict[str, Any]] = []
        zero_line_rows: list[pd.DataFrame] = []
        coverage: dict[str, Any] = {}

        for market in [str(item).strip().upper() for item in markets]:
            history, meta = _market_history(market=market, config=self.config)
            coverage[market] = meta
            symbol_frames = _iter_symbol_frames(history, self.config.min_history_days)

            for variant_name, strategy_factory in _macd_variants():
                summary, rows = _evaluate_variant(
                    market=market,
                    variant_name=variant_name,
                    strategy_factory=strategy_factory,
                    symbol_frames=symbol_frames,
                    config=self.config,
                )
                summary_rows.append(summary)
                symbol_rows.extend(rows)

            for variant_name, strategy_factory in _rsi_variants():
                summary, rows = _evaluate_variant(
                    market=market,
                    variant_name=variant_name,
                    strategy_factory=strategy_factory,
                    symbol_frames=symbol_frames,
                    config=self.config,
                )
                summary_rows.append(summary)
                symbol_rows.extend(rows)

            zero_line_study = _macd_zero_line_study(symbol_frames)
            if not zero_line_study.empty:
                zero_line_study.insert(0, "market", market)
                zero_line_rows.append(zero_line_study)

        summary_df = pd.DataFrame(summary_rows).sort_values(
            ["market", "mean_symbol_return_pct", "avg_trade_return_pct"],
            ascending=[True, False, False],
        ).reset_index(drop=True)
        symbol_df = pd.DataFrame(symbol_rows).sort_values(
            ["market", "variant", "total_return_pct"],
            ascending=[True, True, False],
        ).reset_index(drop=True)
        zero_line_df = pd.concat(zero_line_rows, ignore_index=True) if zero_line_rows else pd.DataFrame()

        summary_path = report_dir / "variant_summary.csv"
        symbol_path = report_dir / "variant_symbol_metrics.csv"
        zero_line_path = report_dir / "macd_zero_line_study.csv"
        coverage_path = report_dir / "download_coverage.json"
        top_path = report_dir / "top_variants.json"

        summary_df.to_csv(summary_path, index=False)
        symbol_df.to_csv(symbol_path, index=False)
        zero_line_df.to_csv(zero_line_path, index=False)
        coverage_path.write_text(json.dumps(coverage, indent=2), encoding="utf-8")

        top_variants: dict[str, Any] = {}
        for market, group in summary_df.groupby("market", sort=True):
            top_variants[market] = {
                "macd": group[group["variant"].str.startswith("macd_")].head(5).to_dict(orient="records"),
                "rsi": group[group["variant"].str.startswith("rsi_")].head(5).to_dict(orient="records"),
            }
        top_path.write_text(json.dumps(top_variants, indent=2), encoding="utf-8")

        result = {
            "config": asdict(self.config),
            "markets": markets,
            "artifacts": {
                "summary": str(summary_path),
                "symbol_metrics": str(symbol_path),
                "macd_zero_line_study": str(zero_line_path),
                "coverage": str(coverage_path),
                "top_variants": str(top_path),
            },
            "top_variants": top_variants,
        }
        return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tune daily MACD and RSI strategies on long-history NSE/US data.")
    parser.add_argument("--market", choices=["NSE", "US", "ALL"], default="ALL")
    parser.add_argument("--start-date", default="2016-01-01")
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--min-history-days", type=int, default=252)
    parser.add_argument("--trade-notional", type=float, default=10_000.0)
    parser.add_argument("--initial-capital", type=float, default=100_000.0)
    parser.add_argument("--slippage-pct", type=float, default=0.05)
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    markets = ["NSE", "US"] if args.market == "ALL" else [args.market]
    result = IndicatorStrategyTuningRunner(
        config=IndicatorTuningConfig(
            start_date=args.start_date,
            end_date=args.end_date,
            min_history_days=args.min_history_days,
            trade_notional=args.trade_notional,
            initial_capital=args.initial_capital,
            slippage_pct=args.slippage_pct,
            report_dir=args.report_dir,
        )
    ).run(markets)
    print(json.dumps(result, indent=2, default=_json_safe))


if __name__ == "__main__":
    main()
