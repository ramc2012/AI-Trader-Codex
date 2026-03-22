"""Hourly large-move pattern research for NSE and US stocks and indices."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd
import yfinance as yf

from src.analysis.indicators.momentum import MACD, ROC, RSI
from src.analysis.indicators.trend import ADX
from src.analysis.indicators.volatility import ATR, BollingerBands, DonchianChannels
from src.analysis.indicators.volume import ChaikinMoneyFlow, MFI, OBV
from src.config.fno_constants import FNO_SYMBOLS
from src.config.us_swing_universe import US_SWING_TICKERS
from src.research.fno_swing_research import yahoo_equity_ticker
from src.research.paths import resolve_report_dir
from src.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_REPORT_DIR = resolve_report_dir(
    None,
    folder_name="hourly_large_move",
    legacy_fallback="tmp/hourly_large_move",
)

NSE_INDEX_TICKERS: dict[str, str] = {
    "NSE:NIFTY50-INDEX": "^NSEI",
    "NSE:NIFTYBANK-INDEX": "^NSEBANK",
    "BSE:SENSEX-INDEX": "^BSESN",
}

US_INDEX_TICKERS: dict[str, str] = {
    "US:SPY": "SPY",
    "US:QQQ": "QQQ",
    "US:IWM": "IWM",
    "US:DIA": "DIA",
}


@dataclass(frozen=True)
class HourlyLargeMoveConfig:
    start_date: str = ""
    end_date: str | None = None
    interval: str = "60m"
    chunk_days: int = 120
    horizon_bars: int = 14
    stock_move_pct: float = 0.05
    index_move_pct: float = 0.01
    min_history_bars: int = 600
    min_condition_support: int = 120
    top_condition_count: int = 12
    max_stock_symbols_per_market: int = 0
    report_dir: str = str(DEFAULT_REPORT_DIR)


def _default_start_date() -> str:
    return (datetime.now(UTC) - timedelta(days=365 * 3)).strftime("%Y-%m-%d")


def _iter_chunks(start: datetime, end: datetime, chunk_days: int) -> Iterable[tuple[datetime, datetime]]:
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + timedelta(days=chunk_days), end)
        yield cursor, chunk_end
        cursor = chunk_end


def _normalize_hourly_frame(
    frame: pd.DataFrame,
    *,
    symbol: str,
    market: str,
    asset_type: str,
    ticker: str,
) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()

    if isinstance(frame.columns, pd.MultiIndex):
        level_zero = {str(item).lower() for item in frame.columns.get_level_values(0)}
        level_last = {str(item).lower() for item in frame.columns.get_level_values(-1)}
        expected = {"open", "high", "low", "close", "adj close", "volume"}
        if expected.intersection(level_zero):
            frame = frame.copy()
            frame.columns = frame.columns.get_level_values(0)
        elif expected.intersection(level_last):
            frame = frame.copy()
            frame.columns = frame.columns.get_level_values(-1)

    normalized = frame.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "adj_close",
            "Volume": "volume",
            "Datetime": "timestamp",
            "Date": "timestamp",
        }
    ).copy()
    if "timestamp" not in normalized.columns:
        normalized = normalized.reset_index()
        normalized = normalized.rename(columns={"Datetime": "timestamp", "Date": "timestamp"})
    if "timestamp" not in normalized.columns:
        return pd.DataFrame()

    normalized["timestamp"] = pd.to_datetime(normalized["timestamp"], errors="coerce", utc=True)
    for column in ("open", "high", "low", "close", "volume"):
        normalized[column] = pd.to_numeric(normalized.get(column), errors="coerce")
    normalized = (
        normalized.dropna(subset=["timestamp", "open", "high", "low", "close"])
        .sort_values("timestamp")
        .drop_duplicates(subset=["timestamp"], keep="last")
    )
    if normalized.empty:
        return pd.DataFrame()

    normalized["volume"] = normalized["volume"].fillna(0.0)
    normalized["symbol"] = symbol
    normalized["market"] = market
    normalized["asset_type"] = asset_type
    normalized["ticker"] = ticker
    return normalized[["timestamp", "symbol", "market", "asset_type", "ticker", "open", "high", "low", "close", "volume"]]


def _download_symbol_hourly(
    *,
    symbol: str,
    ticker: str,
    market: str,
    asset_type: str,
    config: HourlyLargeMoveConfig,
) -> pd.DataFrame:
    start = datetime.strptime(config.start_date, "%Y-%m-%d").replace(tzinfo=UTC)
    end = datetime.strptime(config.end_date, "%Y-%m-%d").replace(tzinfo=UTC) if config.end_date else datetime.now(UTC)
    span_days = max((end - start).days, 0)
    use_max_hourly_period = config.interval == "60m" and config.end_date is None and span_days >= 730
    frames: list[pd.DataFrame] = []

    if use_max_hourly_period:
        raw = yf.download(
            tickers=ticker,
            period="730d",
            interval=config.interval,
            auto_adjust=False,
            progress=False,
            threads=False,
        )
        normalized = _normalize_hourly_frame(
            raw,
            symbol=symbol,
            market=market,
            asset_type=asset_type,
            ticker=ticker,
        )
        if not normalized.empty:
            frames.append(normalized)
    else:
        for chunk_start, chunk_end in _iter_chunks(start, end, max(int(config.chunk_days), 1)):
            raw = yf.download(
                tickers=ticker,
                start=chunk_start.strftime("%Y-%m-%d"),
                end=chunk_end.strftime("%Y-%m-%d"),
                interval=config.interval,
                auto_adjust=False,
                progress=False,
                threads=False,
            )
            normalized = _normalize_hourly_frame(
                raw,
                symbol=symbol,
                market=market,
                asset_type=asset_type,
                ticker=ticker,
            )
            if not normalized.empty:
                frames.append(normalized)

    if not frames:
        return pd.DataFrame()
    result = (
        pd.concat(frames, ignore_index=True)
        .sort_values("timestamp")
        .drop_duplicates(subset=["timestamp"], keep="last")
        .reset_index(drop=True)
    )
    return result


def _market_universe(market: str, config: HourlyLargeMoveConfig) -> list[dict[str, str]]:
    market_key = str(market).strip().upper()
    if market_key == "NSE":
        stock_symbols = list(FNO_SYMBOLS)
        if config.max_stock_symbols_per_market > 0:
            stock_symbols = stock_symbols[: int(config.max_stock_symbols_per_market)]
        rows = [
            {
                "symbol": f"NSE:{root}-EQ",
                "ticker": yahoo_equity_ticker(root),
                "asset_type": "stock",
            }
            for root in stock_symbols
        ]
        rows.extend(
            {
                "symbol": symbol,
                "ticker": ticker,
                "asset_type": "index",
            }
            for symbol, ticker in NSE_INDEX_TICKERS.items()
        )
        return rows
    if market_key == "US":
        stock_tickers = list(US_SWING_TICKERS)
        if config.max_stock_symbols_per_market > 0:
            stock_tickers = stock_tickers[: int(config.max_stock_symbols_per_market)]
        rows = [
            {
                "symbol": f"US:{ticker}",
                "ticker": ticker,
                "asset_type": "stock",
            }
            for ticker in stock_tickers
        ]
        rows.extend(
            {
                "symbol": symbol,
                "ticker": ticker,
                "asset_type": "index",
            }
            for symbol, ticker in US_INDEX_TICKERS.items()
        )
        return rows
    raise ValueError(f"Unsupported market: {market}")


def _build_feature_frame(frame: pd.DataFrame) -> pd.DataFrame:
    ohlcv = frame[["open", "high", "low", "close", "volume"]].copy()
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    volume = frame["volume"].astype(float)
    returns = close.pct_change()
    atr = ATR(period=14).calculate(close, high=high, low=low)
    atr_pct = atr / close.replace(0, np.nan)
    atr_pct_median = atr_pct.rolling(120, min_periods=120).median()
    ema_8 = close.ewm(span=8, adjust=False).mean()
    ema_21 = close.ewm(span=21, adjust=False).mean()
    ema_55 = close.ewm(span=55, adjust=False).mean()
    rsi = RSI(period=14).calculate(close)
    adx = ADX(period=14).calculate(ohlcv)
    macd = MACD(fast_period=12, slow_period=26, signal_period=9).calculate(close)
    bb = BollingerBands(period=20, std_dev=2.0).calculate(close)
    donchian = DonchianChannels(period=20).calculate(ohlcv)
    roc_6 = ROC(period=6).calculate(close) / 100.0
    roc_12 = ROC(period=12).calculate(close) / 100.0
    cmf = ChaikinMoneyFlow(period=20).calculate(ohlcv)
    mfi = MFI(period=14).calculate(ohlcv)
    obv = OBV().calculate(ohlcv)
    volume_mean_20 = volume.rolling(20, min_periods=20).mean()
    volume_std_20 = volume.rolling(20, min_periods=20).std()
    realized_vol_12 = returns.rolling(12, min_periods=12).std() * np.sqrt(252 * 7)
    realized_vol_24 = returns.rolling(24, min_periods=24).std() * np.sqrt(252 * 7)
    bb_width = (bb["upper"] - bb["lower"]) / bb["middle"].replace(0, np.nan)
    bb_width_median = bb_width.rolling(120, min_periods=120).median()
    range_pct = (high - low) / close.shift(1).replace(0, np.nan)

    features = frame.copy()
    features["return_1"] = returns
    features["return_3"] = close.pct_change(3)
    features["return_6"] = close.pct_change(6)
    features["return_12"] = close.pct_change(12)
    features["return_24"] = close.pct_change(24)
    features["return_48"] = close.pct_change(48)
    features["gap_pct"] = (frame["open"] - close.shift(1)) / close.shift(1).replace(0, np.nan)
    features["range_pct"] = range_pct
    features["close_position"] = (close - low) / (high - low).replace(0, np.nan)
    features["atr_pct"] = atr_pct
    features["atr_ratio_120"] = atr_pct / atr_pct_median.replace(0, np.nan)
    features["realized_vol_12"] = realized_vol_12
    features["realized_vol_24"] = realized_vol_24
    features["realized_vol_ratio"] = realized_vol_12 / realized_vol_24.replace(0, np.nan)
    features["ema_gap_8"] = (close / ema_8) - 1.0
    features["ema_gap_21"] = (close / ema_21) - 1.0
    features["ema_gap_55"] = (close / ema_55) - 1.0
    features["ema_trend_8_21"] = (ema_8 / ema_21) - 1.0
    features["ema_trend_21_55"] = (ema_21 / ema_55) - 1.0
    features["rsi_14"] = rsi
    features["adx_14"] = adx["adx"]
    features["plus_di_14"] = adx["plus_di"]
    features["minus_di_14"] = adx["minus_di"]
    features["macd_hist"] = macd["histogram"]
    features["bb_width"] = bb_width
    features["bb_width_ratio_120"] = bb_width / bb_width_median.replace(0, np.nan)
    features["bb_position"] = (close - bb["lower"]) / (bb["upper"] - bb["lower"]).replace(0, np.nan)
    features["volume_ratio_20"] = volume / volume_mean_20.replace(0, np.nan)
    features["volume_zscore_20"] = (volume - volume_mean_20) / volume_std_20.replace(0, np.nan)
    features["cmf_20"] = cmf
    features["mfi_14"] = mfi
    features["obv_slope_20"] = obv.diff(20) / 20.0
    features["roc_6"] = roc_6
    features["roc_12"] = roc_12
    features["prior_high_breakout_24"] = close / high.shift(1).rolling(24, min_periods=24).max() - 1.0
    features["prior_low_breakdown_24"] = close / low.shift(1).rolling(24, min_periods=24).min() - 1.0
    features["prior_high_breakout_48"] = close / high.shift(1).rolling(48, min_periods=48).max() - 1.0
    features["prior_low_breakdown_48"] = close / low.shift(1).rolling(48, min_periods=48).min() - 1.0
    features["donchian_width"] = donchian["width"]
    features["nr7"] = (range_pct <= range_pct.rolling(7, min_periods=7).min()).astype(float)
    features["inside_bar"] = ((high <= high.shift(1)) & (low >= low.shift(1))).astype(float)
    ts_utc = features["timestamp"].dt.tz_convert(UTC)
    features["hour_utc"] = ts_utc.dt.hour.astype(float)
    features["weekday"] = ts_utc.dt.weekday.astype(float)
    return features


def _build_condition_table(dataset: pd.DataFrame) -> dict[str, pd.Series]:
    conditions = {
        "bullish_ema_stack": (
            (dataset["ema_gap_21"] > 0)
            & (dataset["ema_gap_55"] > 0)
            & (dataset["ema_trend_8_21"] > 0)
            & (dataset["ema_trend_21_55"] > 0)
        ),
        "bearish_ema_stack": (
            (dataset["ema_gap_21"] < 0)
            & (dataset["ema_gap_55"] < 0)
            & (dataset["ema_trend_8_21"] < 0)
            & (dataset["ema_trend_21_55"] < 0)
        ),
        "rsi_breakout": dataset["rsi_14"] >= 62,
        "rsi_breakdown": dataset["rsi_14"] <= 38,
        "adx_trending": dataset["adx_14"] >= 25,
        "volume_expansion": dataset["volume_ratio_20"] >= 1.4,
        "volume_surge": dataset["volume_zscore_20"] >= 2.0,
        "atr_compression": dataset["atr_ratio_120"] <= 0.85,
        "bb_squeeze": dataset["bb_width_ratio_120"] <= 0.85,
        "nr7_setup": dataset["nr7"] >= 1.0,
        "inside_bar": dataset["inside_bar"] >= 1.0,
        "breakout_24": dataset["prior_high_breakout_24"] >= 0.0,
        "breakdown_24": dataset["prior_low_breakdown_24"] <= 0.0,
        "breakout_48": dataset["prior_high_breakout_48"] >= 0.0,
        "breakdown_48": dataset["prior_low_breakdown_48"] <= 0.0,
        "cmf_positive": dataset["cmf_20"] >= 0.10,
        "cmf_negative": dataset["cmf_20"] <= -0.10,
        "hour_open_drive": dataset["hour_utc"].isin({3.0, 4.0, 14.0, 15.0}),
        "hour_late_session": dataset["hour_utc"].isin({8.0, 9.0, 18.0, 19.0}),
    }
    return {name: series.fillna(False) for name, series in conditions.items()}


def _evaluate_conditions(
    dataset: pd.DataFrame,
    *,
    target_column: str,
    label_column: str,
    config: HourlyLargeMoveConfig,
) -> pd.DataFrame:
    from itertools import combinations

    conditions = _build_condition_table(dataset)
    target = dataset[target_column].astype(float)
    labels = dataset[label_column].astype(str)
    baseline = float(target.mean()) if len(target) else 0.0
    rows: list[dict[str, Any]] = []

    def add_row(name: str, mask: pd.Series, condition_type: str) -> None:
        support = int(mask.sum())
        if support < int(config.min_condition_support):
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
                "avg_abs_move_2d": float(dataset.loc[mask, "future_abs_move_2d"].mean()),
            }
        )

    for name, mask in conditions.items():
        add_row(name, mask, "single")
    single_rank = sorted(rows, key=lambda row: (row["lift"], row["support"]), reverse=True)
    shortlisted = [row["condition"] for row in single_rank[: int(config.top_condition_count)]]
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


def _label_large_move_targets(frame: pd.DataFrame, config: HourlyLargeMoveConfig) -> pd.DataFrame:
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    close = frame["close"].astype(float)
    horizon = max(int(config.horizon_bars), 1)
    future_high = pd.concat(
        {offset: high.shift(-offset) / close - 1.0 for offset in range(1, horizon + 1)},
        axis=1,
    )
    future_low = pd.concat(
        {offset: 1.0 - (low.shift(-offset) / close) for offset in range(1, horizon + 1)},
        axis=1,
    )
    up_move = future_high.max(axis=1)
    down_move = future_low.max(axis=1)
    abs_move = pd.concat([up_move, down_move], axis=1).max(axis=1)
    threshold = np.where(
        frame["asset_type"].astype(str) == "index",
        float(config.index_move_pct),
        float(config.stock_move_pct),
    )

    labeled = frame.copy()
    labeled["future_up_move_2d"] = up_move
    labeled["future_down_move_2d"] = down_move
    labeled["future_abs_move_2d"] = abs_move
    labeled["move_threshold_2d"] = threshold
    labeled["target_large_move_hit"] = (abs_move >= threshold).astype(float)
    labeled["target_large_move_direction"] = np.where(
        (up_move >= threshold) & (up_move >= down_move),
        "up",
        np.where((down_move >= threshold) & (down_move > up_move), "down", "neutral"),
    )
    return labeled


class HourlyLargeMoveResearchRunner:
    def __init__(self, config: HourlyLargeMoveConfig) -> None:
        self.config = config

    def run(self, markets: Sequence[str]) -> dict[str, Any]:
        report_dir = Path(self.config.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)

        all_frames: list[pd.DataFrame] = []
        download_rows: list[dict[str, Any]] = []
        for market in [str(item).strip().upper() for item in markets]:
            for item in _market_universe(market, self.config):
                frame = _download_symbol_hourly(
                    symbol=str(item["symbol"]),
                    ticker=str(item["ticker"]),
                    market=market,
                    asset_type=str(item["asset_type"]),
                    config=self.config,
                )
                download_rows.append(
                    {
                        "market": market,
                        "symbol": str(item["symbol"]),
                        "ticker": str(item["ticker"]),
                        "asset_type": str(item["asset_type"]),
                        "rows": int(len(frame)),
                        "start": str(frame["timestamp"].min()) if not frame.empty else None,
                        "end": str(frame["timestamp"].max()) if not frame.empty else None,
                    }
                )
                if len(frame) >= int(self.config.min_history_bars):
                    all_frames.append(_build_feature_frame(frame))

        if not all_frames:
            raise RuntimeError("No hourly history met the minimum-bar requirement.")

        dataset = pd.concat(all_frames, ignore_index=True).sort_values(["market", "symbol", "timestamp"]).reset_index(drop=True)
        dataset = _label_large_move_targets(dataset, self.config)
        dataset["date"] = dataset["timestamp"].dt.date.astype(str)
        dataset = dataset.replace([np.inf, -np.inf], np.nan)

        dataset_path = report_dir / "labeled_dataset.csv.gz"
        download_path = report_dir / "download_coverage.json"
        dataset.to_csv(dataset_path, index=False, compression="gzip")
        download_path.write_text(json.dumps(download_rows, indent=2), encoding="utf-8")

        summary_rows: list[dict[str, Any]] = []
        artifact_rows: dict[str, Any] = {}
        for market in sorted(dataset["market"].astype(str).unique()):
            market_frame = dataset.loc[dataset["market"].astype(str) == market].copy()
            for asset_type in ("stock", "index"):
                subset = market_frame.loc[market_frame["asset_type"].astype(str) == asset_type].copy()
                if subset.empty:
                    continue
                conditions = _evaluate_conditions(
                    subset,
                    target_column="target_large_move_hit",
                    label_column="target_large_move_direction",
                    config=self.config,
                )
                artifact_key = f"{market.lower()}_{asset_type}_conditions"
                artifact_path = report_dir / f"{artifact_key}.csv"
                conditions.to_csv(artifact_path, index=False)
                artifact_rows[artifact_key] = str(artifact_path)
                summary_rows.append(
                    {
                        "market": market,
                        "asset_type": asset_type,
                        "rows": int(len(subset)),
                        "symbols": int(subset["symbol"].nunique()),
                        "hit_rate": round(float(subset["target_large_move_hit"].mean()), 4),
                        "up_share": round(float((subset["target_large_move_direction"] == "up").mean()), 4),
                        "down_share": round(float((subset["target_large_move_direction"] == "down").mean()), 4),
                        "avg_abs_move_2d": round(float(subset["future_abs_move_2d"].mean()), 4),
                        "top_condition": (
                            str(conditions.iloc[0]["condition"]) if not conditions.empty else None
                        ),
                        "top_condition_hit_rate": (
                            round(float(conditions.iloc[0]["hit_rate"]), 4) if not conditions.empty else None
                        ),
                        "top_condition_lift": (
                            round(float(conditions.iloc[0]["lift"]), 4) if not conditions.empty else None
                        ),
                    }
                )

        summary = {
            "config": asdict(self.config),
            "markets": list(markets),
            "summary": summary_rows,
            "artifacts": {
                "dataset": str(dataset_path),
                "download_coverage": str(download_path),
                **artifact_rows,
            },
        }
        summary_path = report_dir / "summary.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Research 2-day large-move patterns from 3-year hourly data.")
    parser.add_argument("--market", choices=["NSE", "US", "ALL"], default="ALL")
    parser.add_argument("--start-date", default=_default_start_date())
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--chunk-days", type=int, default=120)
    parser.add_argument("--horizon-bars", type=int, default=14)
    parser.add_argument("--stock-move-pct", type=float, default=0.05)
    parser.add_argument("--index-move-pct", type=float, default=0.01)
    parser.add_argument("--min-history-bars", type=int, default=600)
    parser.add_argument("--min-condition-support", type=int, default=120)
    parser.add_argument("--top-condition-count", type=int, default=12)
    parser.add_argument("--max-stock-symbols-per-market", type=int, default=0)
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    markets = ["NSE", "US"] if args.market == "ALL" else [args.market]
    runner = HourlyLargeMoveResearchRunner(
        HourlyLargeMoveConfig(
            start_date=args.start_date,
            end_date=args.end_date,
            chunk_days=args.chunk_days,
            horizon_bars=args.horizon_bars,
            stock_move_pct=args.stock_move_pct,
            index_move_pct=args.index_move_pct,
            min_history_bars=args.min_history_bars,
            min_condition_support=args.min_condition_support,
            top_condition_count=args.top_condition_count,
            max_stock_symbols_per_market=args.max_stock_symbols_per_market,
            report_dir=args.report_dir,
        )
    )
    result = runner.run(markets)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
