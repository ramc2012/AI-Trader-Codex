"""Helpers for locating persisted research artifacts."""

from __future__ import annotations

from pathlib import Path


def research_root_dir() -> Path:
    try:
        from src.config.settings import get_settings

        return get_settings().data_path / "research"
    except Exception:
        return Path("data") / "research"


def resolve_report_dir(
    explicit: str | Path | None,
    *,
    folder_name: str,
    legacy_fallback: str | Path | None = None,
) -> Path:
    if explicit:
        return Path(explicit)

    primary = research_root_dir() / folder_name
    if primary.exists():
        return primary

    if legacy_fallback:
        legacy = Path(legacy_fallback)
        if legacy.exists():
            return legacy

    return primary

