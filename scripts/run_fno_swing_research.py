#!/usr/bin/env python3
"""CLI entry point for the FnO swing research workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.research.fno_swing_research import FnOSwingResearchRunner, ResearchConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run FnO swing research over long-history daily data.")
    parser.add_argument("--start-date", default="2016-01-01")
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--limit", type=int, default=None, help="Limit symbol count for quicker runs.")
    parser.add_argument(
        "--report-dir",
        default="data/research/fno_swing",
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
    runner = FnOSwingResearchRunner(config=config)
    symbols = None
    if args.limit is not None:
        from src.config.fno_constants import FNO_SYMBOLS

        symbols = FNO_SYMBOLS[: max(args.limit, 1)]

    summary = runner.run(symbols=symbols)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
