"""Daily replay research harness for Bootstrap_Explorer."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

import pandas as pd

from src.config.fno_constants import FNO_SYMBOLS
from src.config.us_swing_universe import US_SWING_TICKERS
from src.research.fno_swing_research import ResearchConfig as FnOResearchConfig
from src.research.fno_swing_research import download_history as download_nse_history
from src.research.paths import resolve_report_dir
from src.research.us_swing_research import ResearchConfig as USResearchConfig
from src.research.us_swing_research import download_history as download_us_history
from src.strategies.backtester import Backtester
from src.strategies.base import BacktestTrade
from src.strategies.directional.bootstrap_explorer import BootstrapExplorerStrategy
from src.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_BOOTSTRAP_REPORT_DIR = resolve_report_dir(
    None,
    folder_name="bootstrap_explorer_daily",
    legacy_fallback="tmp/bootstrap_explorer_daily",
)


@dataclass(frozen=True)
class BootstrapExplorerResearchConfig:
    start_date: str = "2016-01-01"
    end_date: str | None = None
    min_history_days: int = 252
    trade_notional: float = 10_000.0
    initial_capital: float = 100_000.0
    commission: float = 0.0
    slippage_pct: float = 0.05
    report_dir: str = str(DEFAULT_BOOTSTRAP_REPORT_DIR)


def _json_safe(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value


def _trade_rows(trades: Sequence[BacktestTrade], *, market: str, symbol: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for trade in trades:
        rows.append(
            {
                "market": market,
                "symbol": symbol,
                "entry_time": trade.entry_time.isoformat(),
                "exit_time": trade.exit_time.isoformat() if trade.exit_time is not None else None,
                "side": trade.side,
                "entry_price": round(float(trade.entry_price), 4),
                "exit_price": round(float(trade.exit_price or 0.0), 4) if trade.exit_price is not None else None,
                "quantity": int(trade.quantity),
                "pnl": round(float(trade.pnl), 4),
                "pnl_pct": round(float(trade.pnl_pct), 4),
                "exit_reason": trade.exit_reason,
                "hold_days": round(
                    (
                        ((trade.exit_time - trade.entry_time).total_seconds() / 86400.0)
                        if trade.exit_time is not None
                        else 0.0
                    ),
                    4,
                ),
            }
        )
    return rows


def _summarize_trades(trades: pd.DataFrame, *, market: str, tested_symbols: int) -> dict[str, Any]:
    if trades.empty:
        return {
            "market": market,
            "tested_symbols": tested_symbols,
            "trade_count": 0,
            "win_rate_pct": 0.0,
            "avg_trade_return_pct": 0.0,
            "median_trade_return_pct": 0.0,
            "avg_hold_days": 0.0,
            "median_hold_days": 0.0,
        }

    pnl_pct = pd.to_numeric(trades["pnl_pct"], errors="coerce").fillna(0.0)
    hold_days = pd.to_numeric(trades["hold_days"], errors="coerce").fillna(0.0)
    winners = int((pnl_pct > 0).sum())
    return {
        "market": market,
        "tested_symbols": tested_symbols,
        "trade_count": int(len(trades)),
        "win_rate_pct": round((winners / max(len(trades), 1)) * 100.0, 2),
        "avg_trade_return_pct": round(float(pnl_pct.mean()), 4),
        "median_trade_return_pct": round(float(pnl_pct.median()), 4),
        "avg_hold_days": round(float(hold_days.mean()), 4),
        "median_hold_days": round(float(hold_days.median()), 4),
    }


def _yearly_metrics(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(
            columns=[
                "market",
                "year",
                "trades",
                "win_rate_pct",
                "avg_trade_return_pct",
                "median_trade_return_pct",
                "total_pnl",
            ]
        )

    frame = trades.copy()
    frame["entry_time"] = pd.to_datetime(frame["entry_time"], errors="coerce")
    frame["year"] = frame["entry_time"].dt.year.astype("Int64")
    frame["pnl_pct"] = pd.to_numeric(frame["pnl_pct"], errors="coerce").fillna(0.0)
    frame["pnl"] = pd.to_numeric(frame["pnl"], errors="coerce").fillna(0.0)

    rows: list[dict[str, Any]] = []
    for (market, year), group in frame.dropna(subset=["year"]).groupby(["market", "year"], sort=True):
        winners = int((group["pnl_pct"] > 0).sum())
        rows.append(
            {
                "market": market,
                "year": int(year),
                "trades": int(len(group)),
                "win_rate_pct": round((winners / max(len(group), 1)) * 100.0, 2),
                "avg_trade_return_pct": round(float(group["pnl_pct"].mean()), 4),
                "median_trade_return_pct": round(float(group["pnl_pct"].median()), 4),
                "total_pnl": round(float(group["pnl"].sum()), 4),
            }
        )
    return pd.DataFrame(rows)


def _render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Bootstrap Explorer Daily Research",
        "",
        f"- Start date: `{summary['config']['start_date']}`",
        f"- End date: `{summary['config']['end_date'] or 'latest available'}`",
        f"- Min history days: `{summary['config']['min_history_days']}`",
        f"- Trade notional: `{summary['config']['trade_notional']}`",
        f"- Slippage pct: `{summary['config']['slippage_pct']}`",
        "",
        "## Market Summary",
        "",
    ]
    for market_summary in summary["markets"]:
        lines.extend(
            [
                f"### {market_summary['market']}",
                "",
                f"- Tested symbols: `{market_summary['tested_symbols']}`",
                f"- Trade count: `{market_summary['trade_count']}`",
                f"- Win rate: `{market_summary['win_rate_pct']}%`",
                f"- Avg trade return: `{market_summary['avg_trade_return_pct']}%`",
                f"- Median trade return: `{market_summary['median_trade_return_pct']}%`",
                f"- Avg hold days: `{market_summary['avg_hold_days']}`",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


class BootstrapExplorerResearchRunner:
    def __init__(self, config: BootstrapExplorerResearchConfig) -> None:
        self.config = config

    def _market_symbols(self, market: str) -> list[str]:
        market_key = str(market or "").strip().upper()
        if market_key == "NSE":
            return list(FNO_SYMBOLS)
        if market_key == "US":
            return list(US_SWING_TICKERS)
        raise ValueError(f"Unsupported market: {market}")

    def _download_market_history(self, market: str, symbols: Sequence[str]) -> tuple[pd.DataFrame, dict[str, Any]]:
        market_key = str(market or "").strip().upper()
        if market_key == "NSE":
            history, download_meta = download_nse_history(
                symbols,
                FnOResearchConfig(
                    start_date=self.config.start_date,
                    end_date=self.config.end_date,
                    min_history_days=self.config.min_history_days,
                ),
            )
        elif market_key == "US":
            history, download_meta = download_us_history(
                symbols,
                USResearchConfig(
                    start_date=self.config.start_date,
                    end_date=self.config.end_date,
                    min_history_days=self.config.min_history_days,
                ),
            )
        else:
            raise ValueError(f"Unsupported market: {market}")

        history = history.copy()
        history = history.reset_index().rename(columns={"date": "timestamp"})
        history["timestamp"] = pd.to_datetime(history["timestamp"], errors="coerce")
        history = history.dropna(subset=["timestamp"]).sort_values(["symbol", "timestamp"]).reset_index(drop=True)
        return history, download_meta

    def _iter_symbol_frames(self, history: pd.DataFrame) -> Iterable[tuple[str, pd.DataFrame]]:
        for symbol, group in history.groupby("symbol", sort=True):
            ordered = group.sort_values("timestamp").reset_index(drop=True)
            if len(ordered) < self.config.min_history_days:
                continue
            yield str(symbol), ordered

    def run(self, markets: Sequence[str], *, limit: int | None = None) -> dict[str, Any]:
        selected_markets = [str(market).strip().upper() for market in markets]
        report_dir = Path(self.config.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)

        per_symbol_rows: list[dict[str, Any]] = []
        per_trade_rows: list[dict[str, Any]] = []
        download: dict[str, Any] = {}
        market_summaries: list[dict[str, Any]] = []

        for market in selected_markets:
            symbols = self._market_symbols(market)
            if limit is not None:
                symbols = symbols[: max(int(limit), 1)]
            history, download_meta = self._download_market_history(market, symbols)
            download[market] = download_meta

            tested_symbols = 0
            for symbol, frame in self._iter_symbol_frames(history):
                tested_symbols += 1
                first_close = float(pd.to_numeric(frame["close"], errors="coerce").dropna().iloc[0])
                quantity = max(1, int(self.config.trade_notional / max(first_close, 1e-6)))
                result = Backtester(
                    strategy=BootstrapExplorerStrategy(),
                    initial_capital=self.config.initial_capital,
                    quantity=quantity,
                    commission=self.config.commission,
                    slippage_pct=self.config.slippage_pct,
                    exit_on_eod=False,
                ).run(frame, symbol=symbol)

                per_trade_rows.extend(_trade_rows(result.trades, market=market, symbol=symbol))
                per_symbol_rows.append(
                    {
                        "market": market,
                        "symbol": symbol,
                        "bars": int(len(frame)),
                        "start": frame["timestamp"].iloc[0].date().isoformat(),
                        "end": frame["timestamp"].iloc[-1].date().isoformat(),
                        "quantity": int(quantity),
                        "total_trades": int(result.total_trades),
                        "win_rate_pct": round(float(result.win_rate), 4),
                        "total_pnl": round(float(result.total_pnl), 4),
                        "total_return_pct": round(float(result.total_return_pct), 4),
                        "max_drawdown_pct": round(float(result.max_drawdown), 4),
                        "profit_factor": round(float(result.profit_factor), 4),
                        "avg_win": round(float(result.avg_win), 4),
                        "avg_loss": round(float(result.avg_loss), 4),
                    }
                )

            market_trade_frame = pd.DataFrame([row for row in per_trade_rows if row["market"] == market])
            market_summaries.append(_summarize_trades(market_trade_frame, market=market, tested_symbols=tested_symbols))

        symbol_metrics = pd.DataFrame(per_symbol_rows)
        if not symbol_metrics.empty:
            symbol_metrics = symbol_metrics.sort_values(["market", "symbol"]).reset_index(drop=True)

        trade_metrics = pd.DataFrame(per_trade_rows)
        if not trade_metrics.empty:
            trade_metrics = trade_metrics.sort_values(["market", "symbol", "entry_time"]).reset_index(drop=True)

        yearly_metrics = _yearly_metrics(trade_metrics)
        if not yearly_metrics.empty:
            yearly_metrics = yearly_metrics.sort_values(["market", "year"]).reset_index(drop=True)

        symbol_metrics_path = report_dir / "symbol_metrics.csv"
        trade_metrics_path = report_dir / "trade_log.csv"
        yearly_metrics_path = report_dir / "yearly_metrics.csv"
        summary_path = report_dir / "summary.json"
        coverage_path = report_dir / "download_coverage.json"
        report_path = report_dir / "report.md"

        symbol_metrics.to_csv(symbol_metrics_path, index=False)
        trade_metrics.to_csv(trade_metrics_path, index=False)
        yearly_metrics.to_csv(yearly_metrics_path, index=False)
        coverage_path.write_text(json.dumps(download, indent=2, default=_json_safe), encoding="utf-8")

        summary = {
            "config": {
                **asdict(self.config),
                "markets": selected_markets,
                "limit": limit,
                "report_dir": str(report_dir),
            },
            "download": download,
            "markets": market_summaries,
            "artifacts": {
                "symbol_metrics": str(symbol_metrics_path),
                "trade_log": str(trade_metrics_path),
                "yearly_metrics": str(yearly_metrics_path),
                "coverage": str(coverage_path),
                "report": str(report_path),
            },
        }
        summary_path.write_text(json.dumps(summary, indent=2, default=_json_safe), encoding="utf-8")
        report_path.write_text(_render_report(summary), encoding="utf-8")
        logger.info("bootstrap_explorer_research_complete", report=str(report_path))
        return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay Bootstrap_Explorer on daily NSE/US history.")
    parser.add_argument("--market", choices=["NSE", "US", "ALL"], default="ALL")
    parser.add_argument("--start-date", default="2016-01-01")
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--limit", type=int, default=None, help="Limit symbols per market for quicker smoke runs.")
    parser.add_argument("--min-history-days", type=int, default=252)
    parser.add_argument("--trade-notional", type=float, default=10_000.0)
    parser.add_argument("--initial-capital", type=float, default=100_000.0)
    parser.add_argument("--slippage-pct", type=float, default=0.05)
    parser.add_argument("--commission", type=float, default=0.0)
    parser.add_argument(
        "--report-dir",
        default=str(DEFAULT_BOOTSTRAP_REPORT_DIR),
        help="Directory to write symbol metrics, yearly metrics, and report.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    markets = ["NSE", "US"] if args.market == "ALL" else [args.market]
    summary = BootstrapExplorerResearchRunner(
        config=BootstrapExplorerResearchConfig(
            start_date=args.start_date,
            end_date=args.end_date,
            min_history_days=args.min_history_days,
            trade_notional=args.trade_notional,
            initial_capital=args.initial_capital,
            slippage_pct=args.slippage_pct,
            commission=args.commission,
            report_dir=args.report_dir,
        )
    ).run(markets=markets, limit=args.limit)
    print(json.dumps(summary, indent=2, default=_json_safe))


if __name__ == "__main__":
    main()
