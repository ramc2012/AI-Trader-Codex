"""Build runtime swing-research artifacts inside the backend environment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.fno_swing_research import FnOSwingResearchRunner, ResearchConfig
from src.research.paths import resolve_report_dir
from src.research.us_swing_research import USSwingResearchRunner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ensure runtime swing-research artifacts are available.")
    parser.add_argument("--skip-existing", action="store_true", help="Skip a run when summary.json already exists.")
    parser.add_argument("--fno-report-dir", default=None)
    parser.add_argument("--us-report-dir", default=None)
    parser.add_argument("--start-date", default="2016-01-01")
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--min-history-days", type=int, default=750)
    parser.add_argument("--skip-fno", action="store_true")
    parser.add_argument("--skip-us", action="store_true")
    return parser


def _ensure_report(
    *,
    report_dir: Path,
    skip_existing: bool,
    runner_factory,
) -> dict[str, object]:
    summary_path = report_dir / "summary.json"
    if skip_existing and summary_path.exists():
        return {
            "report_dir": str(report_dir),
            "summary_path": str(summary_path),
            "skipped": True,
        }

    report_dir.mkdir(parents=True, exist_ok=True)
    summary = runner_factory().run()
    return {
        "report_dir": str(report_dir),
        "summary_path": str(summary_path),
        "skipped": False,
        "dataset_rows": int(summary.get("dataset", {}).get("rows", 0) or 0),
        "downloaded_symbols": int(summary.get("download", {}).get("symbols_downloaded", 0) or 0),
    }


def main() -> None:
    args = build_parser().parse_args()

    fno_report_dir = resolve_report_dir(
        args.fno_report_dir,
        folder_name="fno_swing",
        legacy_fallback="tmp/fno_swing_research_full",
    )
    us_report_dir = resolve_report_dir(
        args.us_report_dir,
        folder_name="us_swing",
        legacy_fallback="tmp/us_swing_research_full",
    )

    results: dict[str, object] = {}
    base_config = dict(
        start_date=args.start_date,
        end_date=args.end_date,
        min_history_days=args.min_history_days,
    )

    if not args.skip_fno:
        results["fno"] = _ensure_report(
            report_dir=fno_report_dir,
            skip_existing=bool(args.skip_existing),
            runner_factory=lambda: FnOSwingResearchRunner(
                config=ResearchConfig(report_dir=str(fno_report_dir), **base_config)
            ),
        )
    if not args.skip_us:
        results["us"] = _ensure_report(
            report_dir=us_report_dir,
            skip_existing=bool(args.skip_existing),
            runner_factory=lambda: USSwingResearchRunner(
                config=ResearchConfig(report_dir=str(us_report_dir), **base_config)
            ),
        )

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
