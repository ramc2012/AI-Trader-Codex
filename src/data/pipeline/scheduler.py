"""Data collection scheduler.

Provides cron-like scheduling for recurring data collection tasks,
market hours awareness, and automatic job submission.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta
from typing import Callable, Dict, List, Optional

from src.config.constants import INDEX_SYMBOLS, INTRADAY_TIMEFRAMES
from src.config.market_hours import IST, is_market_open
from src.data.pipeline.job import DataJob
from src.data.pipeline.orchestrator import DataOrchestrator
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ScheduledTask:
    """Represents a scheduled data collection task.

    Args:
        name: Human-readable task name
        schedule: Cron-like schedule string or interval in seconds
        job_factory: Callable that creates DataJob instances
        enabled: Whether task is active
        run_only_during_market_hours: Execute only when market is open
    """

    def __init__(
        self,
        name: str,
        schedule: str | int,
        job_factory: Callable[[], List[DataJob] | DataJob],
        enabled: bool = True,
        run_only_during_market_hours: bool = False,
    ) -> None:
        self.name = name
        self.schedule = schedule
        self.job_factory = job_factory
        self.enabled = enabled
        self.run_only_during_market_hours = run_only_during_market_hours
        self.last_run: Optional[datetime] = None
        self.next_run: Optional[datetime] = None
        self.run_count: int = 0
        self.error_count: int = 0

    def should_run(self, now: datetime) -> bool:
        """Check if task should run at the given time.

        Args:
            now: Current timestamp

        Returns:
            True if task should execute now
        """
        if not self.enabled:
            return False

        if self.run_only_during_market_hours and not is_market_open(now):
            return False

        if self.next_run is None:
            return True  # First run

        return now >= self.next_run

    def calculate_next_run(self, now: datetime) -> datetime:
        """Calculate next scheduled run time.

        Args:
            now: Current timestamp

        Returns:
            Next scheduled execution time
        """
        if isinstance(self.schedule, int):
            # Interval in seconds
            return now + timedelta(seconds=self.schedule)
        else:
            # For more complex cron-like schedules, implement parser
            # For now, default to 1 hour interval
            return now + timedelta(hours=1)

    def mark_run(self, now: datetime) -> None:
        """Mark task as executed.

        Args:
            now: Execution timestamp
        """
        self.last_run = now
        self.next_run = self.calculate_next_run(now)
        self.run_count += 1

    def mark_error(self) -> None:
        """Increment error counter."""
        self.error_count += 1


class DataScheduler:
    """Schedule and manage recurring data collection tasks.

    Provides automatic job submission based on schedules, market hours
    awareness, and task lifecycle management.

    Args:
        orchestrator: DataOrchestrator instance for job submission
        check_interval: Seconds between schedule checks
    """

    def __init__(
        self,
        orchestrator: DataOrchestrator,
        check_interval: float = 60.0,
    ) -> None:
        self.orchestrator = orchestrator
        self.check_interval = check_interval
        self._tasks: Dict[str, ScheduledTask] = {}
        self._running: bool = False

    # ========================================================================
    # Task Registration
    # ========================================================================

    def register_task(self, task: ScheduledTask) -> None:
        """Register a scheduled task.

        Args:
            task: ScheduledTask to register
        """
        self._tasks[task.name] = task
        logger.info(
            "task_registered",
            name=task.name,
            schedule=task.schedule,
            market_hours_only=task.run_only_during_market_hours,
        )

    def unregister_task(self, name: str) -> bool:
        """Unregister a scheduled task.

        Args:
            name: Task name

        Returns:
            True if task was removed, False if not found
        """
        if name in self._tasks:
            del self._tasks[name]
            logger.info("task_unregistered", name=name)
            return True
        return False

    def enable_task(self, name: str) -> bool:
        """Enable a scheduled task.

        Args:
            name: Task name

        Returns:
            True if task was enabled, False if not found
        """
        task = self._tasks.get(name)
        if task:
            task.enabled = True
            logger.info("task_enabled", name=name)
            return True
        return False

    def disable_task(self, name: str) -> bool:
        """Disable a scheduled task.

        Args:
            name: Task name

        Returns:
            True if task was disabled, False if not found
        """
        task = self._tasks.get(name)
        if task:
            task.enabled = False
            logger.info("task_disabled", name=name)
            return True
        return False

    # ========================================================================
    # Scheduler Control
    # ========================================================================

    async def start(self) -> None:
        """Start the scheduler loop."""
        if self._running:
            logger.warning("scheduler_already_running")
            return

        self._running = True
        logger.info("scheduler_started", check_interval=self.check_interval)

        try:
            while self._running:
                await self._check_and_run_tasks()
                await asyncio.sleep(self.check_interval)
        except asyncio.CancelledError:
            logger.info("scheduler_cancelled")
        finally:
            self._running = False

    async def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        logger.info("scheduler_stopped")

    async def _check_and_run_tasks(self) -> None:
        """Check all tasks and execute those that should run."""
        now = datetime.now(IST)

        for task in self._tasks.values():
            if task.should_run(now):
                try:
                    await self._execute_task(task, now)
                except Exception as exc:
                    task.mark_error()
                    logger.error(
                        "task_execution_failed",
                        task_name=task.name,
                        error=str(exc),
                    )

    async def _execute_task(self, task: ScheduledTask, now: datetime) -> None:
        """Execute a scheduled task.

        Args:
            task: ScheduledTask to execute
            now: Current timestamp
        """
        logger.info("task_executing", name=task.name)

        try:
            # Create jobs from factory
            jobs = task.job_factory()
            if isinstance(jobs, DataJob):
                jobs = [jobs]

            # Submit jobs to orchestrator
            await self.orchestrator.submit_jobs(jobs)

            task.mark_run(now)
            logger.info(
                "task_executed",
                name=task.name,
                jobs_submitted=len(jobs),
                next_run=task.next_run.isoformat() if task.next_run else None,
            )

        except Exception as exc:
            task.mark_error()
            logger.error("task_failed", name=task.name, error=str(exc))
            raise

    # ========================================================================
    # Pre-configured Schedules
    # ========================================================================

    def register_default_tasks(self) -> None:
        """Register default data collection tasks.

        Sets up common schedules for:
        - Daily OHLC collection (end of day)
        - Intraday OHLC collection (during market hours)
        - Option chain snapshots
        """
        # End-of-day daily candle collection (3:45 PM IST)
        def daily_ohlc_jobs() -> List[DataJob]:
            return [
                self.orchestrator.create_ohlc_job(
                    symbol=symbol,
                    timeframe="D",
                    days_back=7,  # Backfill last week
                )
                for symbol in INDEX_SYMBOLS
            ]

        eod_task = ScheduledTask(
            name="daily_ohlc_eod",
            schedule=3600 * 24,  # Once per day
            job_factory=daily_ohlc_jobs,
            run_only_during_market_hours=False,
        )
        self.register_task(eod_task)

        # Intraday data collection (every 5 minutes during market hours)
        def intraday_ohlc_jobs() -> List[DataJob]:
            jobs = []
            for symbol in INDEX_SYMBOLS:
                for tf in ["5", "15"]:  # 5-min and 15-min
                    jobs.append(
                        self.orchestrator.create_ohlc_job(
                            symbol=symbol,
                            timeframe=tf,
                            days_back=1,  # Just today's data
                        )
                    )
            return jobs

        intraday_task = ScheduledTask(
            name="intraday_ohlc",
            schedule=300,  # Every 5 minutes
            job_factory=intraday_ohlc_jobs,
            run_only_during_market_hours=True,
        )
        self.register_task(intraday_task)

        # Option chain snapshots (every 15 minutes during market hours)
        def option_chain_jobs() -> List[DataJob]:
            return [
                self.orchestrator.create_option_chain_job(symbol=symbol)
                for symbol in INDEX_SYMBOLS[:2]  # Nifty and Bank Nifty only
            ]

        option_task = ScheduledTask(
            name="option_chain_snapshots",
            schedule=900,  # Every 15 minutes
            job_factory=option_chain_jobs,
            run_only_during_market_hours=True,
        )
        self.register_task(option_task)

        logger.info("default_tasks_registered", count=len(self._tasks))

    # ========================================================================
    # Status and Introspection
    # ========================================================================

    def get_task_status(self, name: str) -> Optional[Dict[str, any]]:
        """Get status of a specific task.

        Args:
            name: Task name

        Returns:
            Dictionary with task status, or None if not found
        """
        task = self._tasks.get(name)
        if not task:
            return None

        return {
            "name": task.name,
            "enabled": task.enabled,
            "schedule": task.schedule,
            "market_hours_only": task.run_only_during_market_hours,
            "last_run": task.last_run.isoformat() if task.last_run else None,
            "next_run": task.next_run.isoformat() if task.next_run else None,
            "run_count": task.run_count,
            "error_count": task.error_count,
        }

    def get_all_tasks_status(self) -> List[Dict[str, any]]:
        """Get status of all registered tasks.

        Returns:
            List of task status dictionaries
        """
        return [
            self.get_task_status(name) for name in self._tasks.keys()
        ]

    @property
    def is_running(self) -> bool:
        """Check if scheduler is currently running."""
        return self._running

    @property
    def task_count(self) -> int:
        """Get number of registered tasks."""
        return len(self._tasks)
