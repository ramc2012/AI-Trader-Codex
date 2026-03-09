"""Background fractal scan notifier for watchlist symbols."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Optional

from src.agent.events import AgentEvent, AgentEventBus, AgentEventType
from src.analysis.fractal_scan import (
    DEFAULT_WATCHLIST_SYMBOLS,
    build_scan_payload,
    display_symbol,
    load_context_snapshots,
)
from src.config.market_hours import IST
from src.database.connection import get_session_factory
from src.utils.logger import get_logger

logger = get_logger(__name__)


class FractalScanNotifier:
    """Run periodic watchlist scans and emit candidate events."""

    def __init__(
        self,
        event_bus: AgentEventBus,
        symbols: Optional[list[str]] = None,
        interval_minutes: int = 60,
        min_consecutive_hours: int = 2,
        limit: int = 4,
    ) -> None:
        self._event_bus = event_bus
        self._symbols = list(symbols or DEFAULT_WATCHLIST_SYMBOLS)
        self._interval_minutes = max(int(interval_minutes), 5)
        self._min_consecutive_hours = max(int(min_consecutive_hours), 1)
        self._limit = max(int(limit), 1)
        self._task: Optional[asyncio.Task[None]] = None
        self._last_summary_key: Optional[tuple[str, int, str]] = None
        self._sent_candidate_keys: set[tuple[str, str, str, str]] = set()

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.is_running:
            return
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "fractal_scan_notifier_started",
            interval_minutes=self._interval_minutes,
            symbols=self._symbols,
        )

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("fractal_scan_notifier_stopped")

    async def notify_once(self, session_date: Optional[datetime] = None) -> dict[str, Any]:
        if session_date is None:
            effective_date = datetime.now(tz=IST).replace(tzinfo=None)
        elif session_date.tzinfo is None:
            effective_date = session_date
        else:
            effective_date = session_date.astimezone(IST).replace(tzinfo=None)
        snapshots = await load_context_snapshots(
            session_factory=get_session_factory(),
            symbols=self._symbols,
            session_date=effective_date,
            concurrency=min(6, max(len(self._symbols), 1)),
        )
        payload = build_scan_payload(
            symbols=self._symbols,
            snapshots=snapshots,
            session_date=effective_date,
            min_consecutive_hours=self._min_consecutive_hours,
            limit=self._limit,
        )
        await self._emit_events(payload=payload, snapshots=snapshots)
        return payload

    async def _loop(self) -> None:
        try:
            await asyncio.sleep(20)
            await self.notify_once()
            while True:
                await asyncio.sleep(self._seconds_until_next_run())
                await self.notify_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("fractal_scan_notifier_error", error=str(exc))

    def _seconds_until_next_run(self) -> float:
        now = datetime.now(tz=IST)
        next_run = now.replace(second=10, microsecond=0)
        next_minute = ((next_run.minute // self._interval_minutes) + 1) * self._interval_minutes
        if next_minute >= 60:
            next_run = (next_run + timedelta(hours=1)).replace(minute=0)
        else:
            next_run = next_run.replace(minute=next_minute)
        delay = (next_run - now).total_seconds()
        return max(delay, 30.0)

    async def _emit_events(self, payload: dict[str, Any], snapshots: list[Any]) -> None:
        scan_date = str(payload.get("date", ""))
        candidates = list(payload.get("candidates", []))
        top_symbols = ", ".join(str(item.get("symbol", "")) for item in candidates[:3] if item.get("symbol"))
        summary_key = (scan_date, len(candidates), top_symbols)

        if summary_key != self._last_summary_key:
            await self._event_bus.emit(
                AgentEvent(
                    event_type=AgentEventType.FRACTAL_SCAN_SUMMARY,
                    title="Fractal Watchlist Scan",
                    message=f"{len(candidates)} candidate(s) across {len(self._symbols)} watchlist symbol(s).",
                    severity="success" if candidates else "info",
                    metadata={
                        "scan_date": scan_date,
                        "symbols_scanned": len(self._symbols),
                        "candidates_found": len(candidates),
                        "top_symbols": top_symbols,
                    },
                )
            )
            self._last_summary_key = summary_key

        snapshots_by_symbol = {snapshot.symbol: snapshot for snapshot in snapshots}
        current_day = datetime.now(tz=IST).date().isoformat()
        self._sent_candidate_keys = {
            key for key in self._sent_candidate_keys if key[0] == current_day
        }

        for candidate in candidates:
            symbol = str(candidate.get("symbol", ""))
            snapshot = snapshots_by_symbol.get(symbol)
            current_hour = snapshot.context.hourly_profiles[-1] if snapshot and snapshot.context.hourly_profiles else None
            hour_key = current_hour.start.isoformat() if current_hour is not None else scan_date
            dedupe_key = (
                current_day,
                symbol,
                str(candidate.get("direction", "")),
                hour_key,
            )
            if dedupe_key in self._sent_candidate_keys:
                continue

            severity = "success" if int(candidate.get("conviction", 0) or 0) >= 70 else "info"
            await self._event_bus.emit(
                AgentEvent(
                    event_type=AgentEventType.FRACTAL_CANDIDATE,
                    title=f"{display_symbol(symbol)} fractal candidate",
                    message=str(candidate.get("rationale", "")),
                    severity=severity,
                    metadata={
                        "symbol": symbol,
                        "direction": candidate.get("direction"),
                        "conviction": candidate.get("conviction"),
                        "hourly_shape": candidate.get("hourly_shape"),
                        "consecutive_migration_hours": candidate.get("consecutive_migration_hours"),
                        "entry_trigger": candidate.get("entry_trigger"),
                        "stop_reference": candidate.get("stop_reference"),
                        "target_reference": candidate.get("target_reference"),
                        "suggested_contract": candidate.get("suggested_contract"),
                        "rationale": candidate.get("rationale"),
                    },
                )
            )
            self._sent_candidate_keys.add(dedupe_key)
