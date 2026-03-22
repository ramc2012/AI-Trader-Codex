#!/usr/bin/env python3
"""CLI entry point for daily indicator tuning."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.research.indicator_strategy_tuning import main


if __name__ == "__main__":
    main()
