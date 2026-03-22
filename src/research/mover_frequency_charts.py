"""Generate mover-frequency charts from the stored 10-year research datasets."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any
import pandas as pd
from xml.sax.saxutils import escape

from src.research.paths import resolve_report_dir

DEFAULT_REPORT_DIR = resolve_report_dir(
    None,
    folder_name="mover_frequency",
    legacy_fallback="tmp/mover_frequency",
)


@dataclass(frozen=True)
class MoverFrequencyConfig:
    report_dir: str = str(DEFAULT_REPORT_DIR)
    nse_dataset: str = "tmp/fno_swing_research_full/labeled_dataset.csv.gz"
    us_dataset: str = "tmp/us_swing_research_full/labeled_dataset.csv.gz"
    daily_threshold_pct: float = 5.0
    monthly_thresholds_pct: tuple[float, float] = (10.0, 20.0)


def _load_price_history(dataset_path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(
        dataset_path,
        compression="gzip",
        usecols=["date", "symbol", "close"],
        low_memory=False,
    )
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["date", "symbol", "close"]).sort_values(["symbol", "date"]).reset_index(drop=True)
    frame["daily_return_pct"] = (
        frame.groupby("symbol", sort=True)["close"].pct_change() * 100.0
    )
    return frame.dropna(subset=["daily_return_pct"]).reset_index(drop=True)


def _daily_mover_counts(frame: pd.DataFrame, threshold_pct: float) -> pd.DataFrame:
    movers = frame.loc[frame["daily_return_pct"].abs() >= float(threshold_pct)].copy()
    counts = (
        movers.groupby("date", sort=True)["symbol"]
        .nunique()
        .rename("mover_count")
        .reset_index()
        .sort_values("date")
    )
    return counts


def _monthly_mover_counts(frame: pd.DataFrame, thresholds_pct: tuple[float, float]) -> pd.DataFrame:
    working = frame.copy()
    working["month"] = working["date"].dt.to_period("M").dt.to_timestamp()
    rows: list[dict[str, Any]] = []
    for threshold in thresholds_pct:
        movers = working.loc[working["daily_return_pct"].abs() >= float(threshold)].copy()
        monthly = (
            movers.groupby("month", sort=True)["symbol"]
            .count()
            .rename("mover_events")
            .reset_index()
        )
        monthly["threshold_pct"] = float(threshold)
        rows.append(monthly)
    if not rows:
        return pd.DataFrame(columns=["month", "mover_events", "threshold_pct"])
    return pd.concat(rows, ignore_index=True).sort_values(["threshold_pct", "month"]).reset_index(drop=True)


def _scale_points(
    dates: pd.Series,
    values: pd.Series,
    *,
    x0: float,
    y0: float,
    width: float,
    height: float,
) -> list[tuple[float, float]]:
    if dates.empty:
        return []
    x_values = dates.map(pd.Timestamp.toordinal).astype(float)
    y_values = pd.to_numeric(values, errors="coerce").fillna(0.0).astype(float)
    x_min = float(x_values.min())
    x_max = float(x_values.max())
    y_max = float(max(y_values.max(), 1.0))
    x_span = max(x_max - x_min, 1.0)
    points: list[tuple[float, float]] = []
    for raw_x, raw_y in zip(x_values, y_values, strict=False):
        px = x0 + ((float(raw_x) - x_min) / x_span) * width
        py = y0 + height - (float(raw_y) / y_max) * height
        points.append((round(px, 2), round(py, 2)))
    return points


def _polyline(points: list[tuple[float, float]], color: str, stroke_width: float = 2.0) -> str:
    if not points:
        return ""
    coords = " ".join(f"{x},{y}" for x, y in points)
    return (
        f'<polyline fill="none" stroke="{color}" stroke-width="{stroke_width}" '
        f'stroke-linejoin="round" stroke-linecap="round" points="{coords}" />'
    )


def _year_ticks(dates: pd.Series) -> list[pd.Timestamp]:
    if dates.empty:
        return []
    start = pd.Timestamp(dates.min()).normalize()
    end = pd.Timestamp(dates.max()).normalize()
    years = list(range(start.year, end.year + 1))
    return [pd.Timestamp(year=year, month=1, day=1) for year in years]


def _axis_group(
    *,
    dates: pd.Series,
    x0: float,
    y0: float,
    width: float,
    height: float,
    y_max: float,
    y_label: str,
) -> str:
    x_axis = f'<line x1="{x0}" y1="{y0 + height}" x2="{x0 + width}" y2="{y0 + height}" stroke="#334155" stroke-width="1.2" />'
    y_axis = f'<line x1="{x0}" y1="{y0}" x2="{x0}" y2="{y0 + height}" stroke="#334155" stroke-width="1.2" />'

    grid_lines: list[str] = [x_axis, y_axis]
    for idx in range(5):
        frac = idx / 4
        y = round(y0 + height - frac * height, 2)
        value = round(frac * y_max, 1)
        grid_lines.append(
            f'<line x1="{x0}" y1="{y}" x2="{x0 + width}" y2="{y}" stroke="#cbd5e1" stroke-width="0.8" />'
        )
        grid_lines.append(
            f'<text x="{x0 - 10}" y="{y + 4}" text-anchor="end" font-size="12" fill="#334155">{value:g}</text>'
        )

    tick_dates = _year_ticks(dates)
    if tick_dates:
        ord_min = float(pd.Timestamp(dates.min()).toordinal())
        ord_max = float(pd.Timestamp(dates.max()).toordinal())
        span = max(ord_max - ord_min, 1.0)
        for tick in tick_dates:
            x = round(x0 + ((float(tick.toordinal()) - ord_min) / span) * width, 2)
            if x < x0 or x > x0 + width:
                continue
            grid_lines.append(
                f'<line x1="{x}" y1="{y0}" x2="{x}" y2="{y0 + height}" stroke="#e2e8f0" stroke-width="0.8" />'
            )
            grid_lines.append(
                f'<text x="{x}" y="{y0 + height + 18}" text-anchor="middle" font-size="12" fill="#334155">{tick.year}</text>'
            )

    grid_lines.append(
        f'<text x="{x0 - 62}" y="{y0 + (height / 2)}" transform="rotate(-90 {x0 - 62},{y0 + (height / 2)})" '
        f'text-anchor="middle" font-size="13" fill="#0f172a">{escape(y_label)}</text>'
    )
    return "".join(grid_lines)


def _legend(items: list[tuple[str, str]], *, x: float, y: float) -> str:
    parts: list[str] = []
    for index, (label, color) in enumerate(items):
        row_y = y + index * 22
        parts.append(f'<line x1="{x}" y1="{row_y}" x2="{x + 18}" y2="{row_y}" stroke="{color}" stroke-width="3" />')
        parts.append(
            f'<text x="{x + 26}" y="{row_y + 4}" font-size="12" fill="#0f172a">{escape(label)}</text>'
        )
    return "".join(parts)


def _plot_market(
    *,
    market: str,
    daily_counts: pd.DataFrame,
    monthly_counts: pd.DataFrame,
    config: MoverFrequencyConfig,
    output_path: Path,
) -> None:
    width = 1500
    height = 980
    panel_width = 1300
    panel_height = 320
    x0 = 120
    top_y = 120
    bottom_y = 560

    daily_points = _scale_points(
        daily_counts["date"],
        daily_counts["mover_count"],
        x0=x0,
        y0=top_y,
        width=panel_width,
        height=panel_height,
    )
    monthly_series: list[tuple[str, str, list[tuple[float, float]], pd.DataFrame]] = []
    monthly_colors = {
        float(config.monthly_thresholds_pct[0]): "#b45309",
        float(config.monthly_thresholds_pct[1]): "#991b1b",
    }
    for threshold in config.monthly_thresholds_pct:
        subset = monthly_counts.loc[monthly_counts["threshold_pct"] == float(threshold)].copy()
        points = _scale_points(
            subset["month"],
            subset["mover_events"],
            x0=x0,
            y0=bottom_y,
            width=panel_width,
            height=panel_height,
        )
        monthly_series.append((f"Monthly |return| >= {threshold:.0f}%", monthly_colors[float(threshold)], points, subset))

    daily_y_max = float(max(daily_counts["mover_count"].max(), 1.0)) if not daily_counts.empty else 1.0
    monthly_y_max = (
        float(max(monthly_counts["mover_events"].max(), 1.0))
        if not monthly_counts.empty
        else 1.0
    )

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#f8fafc" />',
        f'<text x="{x0}" y="54" font-size="28" font-weight="700" fill="#0f172a">{escape(market)} 10-Year Mover Frequency</text>',
        f'<text x="{x0}" y="84" font-size="15" fill="#475569">Daily distinct 5% movers and monthly 10% / 20% move events from the stored research universe.</text>',
        f'<text x="{x0}" y="{top_y - 26}" font-size="20" font-weight="600" fill="#0f172a">{escape(f"Daily {config.daily_threshold_pct:.0f}%+ Movers")}</text>',
        _axis_group(
            dates=daily_counts["date"],
            x0=x0,
            y0=top_y,
            width=panel_width,
            height=panel_height,
            y_max=daily_y_max,
            y_label="Distinct symbols",
        ),
        _polyline(daily_points, "#0f766e", 2.0),
        _legend(
            [(f"Daily |return| >= {config.daily_threshold_pct:.0f}%", "#0f766e")],
            x=x0 + panel_width - 220,
            y=top_y + 20,
        ),
        f'<text x="{x0}" y="{bottom_y - 26}" font-size="20" font-weight="600" fill="#0f172a">Monthly 10%+ and 20%+ Move Events</text>',
        _axis_group(
            dates=monthly_counts["month"] if not monthly_counts.empty else pd.Series(dtype="datetime64[ns]"),
            x0=x0,
            y0=bottom_y,
            width=panel_width,
            height=panel_height,
            y_max=monthly_y_max,
            y_label="Symbol-day events",
        ),
    ]

    legend_items: list[tuple[str, str]] = []
    for label, color, points, _subset in monthly_series:
        svg_parts.append(_polyline(points, color, 2.0))
        legend_items.append((label, color))
    svg_parts.append(_legend(legend_items, x=x0 + panel_width - 240, y=bottom_y + 20))
    svg_parts.append("</svg>")

    output_path.write_text("".join(svg_parts), encoding="utf-8")


class MoverFrequencyChartRunner:
    def __init__(self, config: MoverFrequencyConfig) -> None:
        self.config = config

    def run(self) -> dict[str, Any]:
        report_dir = Path(self.config.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)

        dataset_map = {
            "NSE": Path(self.config.nse_dataset),
            "US": Path(self.config.us_dataset),
        }
        summary: dict[str, Any] = {"config": asdict(self.config), "markets": {}}

        for market, dataset_path in dataset_map.items():
            history = _load_price_history(dataset_path)
            daily_counts = _daily_mover_counts(history, self.config.daily_threshold_pct)
            monthly_counts = _monthly_mover_counts(history, self.config.monthly_thresholds_pct)

            daily_csv = report_dir / f"{market.lower()}_daily_mover_counts.csv"
            monthly_csv = report_dir / f"{market.lower()}_monthly_mover_counts.csv"
            chart_path = report_dir / f"{market.lower()}_mover_frequency.svg"
            daily_counts.to_csv(daily_csv, index=False)
            monthly_counts.to_csv(monthly_csv, index=False)
            _plot_market(
                market=market,
                daily_counts=daily_counts,
                monthly_counts=monthly_counts,
                config=self.config,
                output_path=chart_path,
            )

            market_summary = {
                "dataset": str(dataset_path),
                "rows": int(len(history)),
                "symbols": int(history["symbol"].nunique()),
                "start_date": str(history["date"].min().date()) if not history.empty else None,
                "end_date": str(history["date"].max().date()) if not history.empty else None,
                "peak_daily_count": int(daily_counts["mover_count"].max()) if not daily_counts.empty else 0,
                "peak_daily_date": (
                    str(daily_counts.loc[daily_counts["mover_count"].idxmax(), "date"].date())
                    if not daily_counts.empty
                    else None
                ),
                "artifacts": {
                    "daily_counts": str(daily_csv),
                    "monthly_counts": str(monthly_csv),
                    "chart": str(chart_path),
                },
            }
            summary["markets"][market] = market_summary

        summary_path = report_dir / "summary.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        summary["summary_path"] = str(summary_path)
        return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate 10-year mover-frequency charts from stored research datasets.")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--nse-dataset", default="tmp/fno_swing_research_full/labeled_dataset.csv.gz")
    parser.add_argument("--us-dataset", default="tmp/us_swing_research_full/labeled_dataset.csv.gz")
    parser.add_argument("--daily-threshold-pct", type=float, default=5.0)
    parser.add_argument("--monthly-thresholds-pct", nargs=2, type=float, default=(10.0, 20.0))
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    result = MoverFrequencyChartRunner(
        MoverFrequencyConfig(
            report_dir=args.report_dir,
            nse_dataset=args.nse_dataset,
            us_dataset=args.us_dataset,
            daily_threshold_pct=args.daily_threshold_pct,
            monthly_thresholds_pct=tuple(float(value) for value in args.monthly_thresholds_pct),
        )
    ).run()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
