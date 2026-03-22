#!/usr/bin/env python3
"""CLI entry point for hourly large-move research."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.research.hourly_large_move_research import main


if __name__ == "__main__":
    main()
