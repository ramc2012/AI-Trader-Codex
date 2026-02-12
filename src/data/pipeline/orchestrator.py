"""Data pipeline orchestrator.

Coordinates data collection jobs, manages execution queues, handles
failures and retries, and provides centralized job management.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.config.market_hours import IST
from src.data.collectors.ohlc_collector import Candle, OHLCCollector
from src.data.pipeline.job import DataJob, JobStatus, JobType
from src.database.operations import upsert_ohlc_candles
from src.integrations.fyers_client import FyersClient
from src.utils.exceptions import DataFetchError
from src.utils.logger import get_logger

logger = get_logger(__name__)


class DataOrchestrator:
    """Orchestrate and manage data collection jobs.

    Provides centralized job queue management, parallel execution,
    retry logic, and progress tracking for data collection tasks.

    Args:
        fyers_client: Fyers API client for data collection
        db_session: Database session for storing collected data
        max_concurrent_jobs: Maximum number of jobs to run in parallel
        max_retries: Maximum retry attempts for failed jobs
    """

    def __init__(
        self,
        fyers_client: FyersClient,
        db_session: AsyncSession,
        max_concurrent_jobs: int = 3,
        max_retries: int = 3,
    ) -> None:
        self.fyers_client = fyers_client
        self.db_session = db_session
        self.max_concurrent_jobs = max_concurrent_jobs
        self.max_retries = max_retries

        # Job tracking
        self._jobs: Dict[str, DataJob] = {}
        self._job_queue: asyncio.Queue[DataJob] = asyncio.Queue()
        self._running_jobs: Dict[str, asyncio.Task] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent_jobs)

        # Statistics
        self._stats: Dict[str, int] = defaultdict(int)

    # ========================================================================
    # Job Creation
    # ========================================================================

    def create_ohlc_job(
        self,
        symbol: str,
        timeframe: str,
        days_back: int = 90,
    ) -> DataJob:
        """Create a historical OHLC data collection job.

        Args:
            symbol: Trading symbol (e.g., "NSE:NIFTY50-INDEX")
            timeframe: Timeframe (e.g., "D", "60", "5")
            days_back: Number of days of historical data to collect

        Returns:
            Created DataJob instance
        """
        job_id = f"ohlc_{symbol}_{timeframe}_{uuid.uuid4().hex[:8]}"
        job = DataJob(
            job_id=job_id,
            job_type=JobType.OHLC_HISTORICAL,
            symbol=symbol,
            timeframe=timeframe,
            params={"days_back": days_back},
        )
        self._jobs[job_id] = job
        logger.info(
            "ohlc_job_created",
            job_id=job_id,
            symbol=symbol,
            timeframe=timeframe,
            days_back=days_back,
        )
        return job

    def create_option_chain_job(
        self,
        symbol: str,
        expiry_date: Optional[str] = None,
    ) -> DataJob:
        """Create an option chain data collection job.

        Args:
            symbol: Underlying symbol (e.g., "NSE:NIFTY50-INDEX")
            expiry_date: Specific expiry date (optional)

        Returns:
            Created DataJob instance
        """
        job_id = f"option_{symbol}_{uuid.uuid4().hex[:8]}"
        job = DataJob(
            job_id=job_id,
            job_type=JobType.OPTION_CHAIN,
            symbol=symbol,
            params={"expiry_date": expiry_date} if expiry_date else {},
        )
        self._jobs[job_id] = job
        logger.info("option_chain_job_created", job_id=job_id, symbol=symbol)
        return job

    # ========================================================================
    # Job Submission and Execution
    # ========================================================================

    async def submit_job(self, job: DataJob) -> None:
        """Submit a job to the execution queue.

        Args:
            job: DataJob to submit
        """
        await self._job_queue.put(job)
        logger.info("job_submitted", job_id=job.job_id, queue_size=self._job_queue.qsize())

    async def submit_jobs(self, jobs: List[DataJob]) -> None:
        """Submit multiple jobs to the execution queue.

        Args:
            jobs: List of DataJob instances
        """
        for job in jobs:
            await self.submit_job(job)

    async def execute_job(self, job: DataJob) -> None:
        """Execute a single job.

        Args:
            job: DataJob to execute
        """
        async with self._semaphore:
            job.start()
            self._stats["started"] += 1
            logger.info(
                "job_started",
                job_id=job.job_id,
                job_type=job.job_type.value,
                symbol=job.symbol,
            )

            try:
                if job.job_type == JobType.OHLC_HISTORICAL:
                    await self._execute_ohlc_job(job)
                elif job.job_type == JobType.OPTION_CHAIN:
                    await self._execute_option_chain_job(job)
                else:
                    raise NotImplementedError(
                        f"Job type {job.job_type} not implemented"
                    )

                job.complete(job.records_collected)
                self._stats["completed"] += 1
                logger.info(
                    "job_completed",
                    job_id=job.job_id,
                    records=job.records_collected,
                    duration=job.duration_seconds,
                )

            except Exception as exc:
                error_msg = str(exc)
                job.fail(error_msg)
                self._stats["failed"] += 1
                logger.error(
                    "job_failed",
                    job_id=job.job_id,
                    error=error_msg,
                    retry_count=job.retry_count,
                )

                # Retry if eligible
                if job.can_retry(self.max_retries):
                    job.increment_retry()
                    await self.submit_job(job)
                    self._stats["retried"] += 1
                    logger.info("job_retried", job_id=job.job_id, retry=job.retry_count)

    async def _execute_ohlc_job(self, job: DataJob) -> None:
        """Execute OHLC data collection job.

        Args:
            job: OHLC DataJob instance
        """
        days_back = job.params.get("days_back", 90)
        end_date = datetime.now(IST).date()
        start_date = end_date - __import__("datetime").timedelta(days=days_back)

        collector = OHLCCollector(self.fyers_client)

        # Progress callback
        def on_progress(symbol: str, tf: str, collected: int, total: int) -> None:
            progress = (collected / total * 100) if total > 0 else 0
            job.update_progress(progress, collected)

        # Collect data
        candles: List[Candle] = await asyncio.to_thread(
            collector.collect_range,
            symbol=job.symbol,
            timeframe=job.timeframe,
            start_date=start_date,
            end_date=end_date,
            on_progress=on_progress,
        )

        # Store to database
        if candles:
            candle_dicts = [c.to_dict() for c in candles]
            await upsert_ohlc_candles(self.db_session, candle_dicts)
            job.records_collected = len(candles)

    async def _execute_option_chain_job(self, job: DataJob) -> None:
        """Execute option chain collection job.

        Args:
            job: Option chain DataJob instance
        """
        # Placeholder for option chain collection
        # Implementation will depend on OptionChainCollector API
        logger.warning(
            "option_chain_collection_not_implemented",
            job_id=job.job_id,
        )
        await asyncio.sleep(1)  # Simulate work
        job.records_collected = 0

    # ========================================================================
    # Queue Processing
    # ========================================================================

    async def process_queue(self) -> None:
        """Process jobs from the queue until empty."""
        while not self._job_queue.empty():
            job = await self._job_queue.get()
            task = asyncio.create_task(self.execute_job(job))
            self._running_jobs[job.job_id] = task

        # Wait for all running jobs to complete
        if self._running_jobs:
            await asyncio.gather(*self._running_jobs.values(), return_exceptions=True)
            self._running_jobs.clear()

        logger.info("queue_processing_complete", stats=dict(self._stats))

    async def process_queue_continuous(self, check_interval: float = 1.0) -> None:
        """Continuously process jobs from the queue.

        Runs indefinitely, checking for new jobs at regular intervals.

        Args:
            check_interval: Seconds to wait between queue checks
        """
        logger.info("continuous_queue_processing_started")
        while True:
            try:
                job = await asyncio.wait_for(
                    self._job_queue.get(), timeout=check_interval
                )
                task = asyncio.create_task(self.execute_job(job))
                self._running_jobs[job.job_id] = task

                # Clean up completed tasks
                completed_ids = [
                    jid for jid, task in self._running_jobs.items() if task.done()
                ]
                for jid in completed_ids:
                    del self._running_jobs[jid]

            except asyncio.TimeoutError:
                continue  # No jobs in queue, keep waiting
            except Exception as exc:
                logger.error("queue_processing_error", error=str(exc))
                await asyncio.sleep(check_interval)

    # ========================================================================
    # Job Query and Status
    # ========================================================================

    def get_job(self, job_id: str) -> Optional[DataJob]:
        """Retrieve job by ID.

        Args:
            job_id: Job identifier

        Returns:
            DataJob instance or None if not found
        """
        return self._jobs.get(job_id)

    def get_jobs_by_status(self, status: JobStatus) -> List[DataJob]:
        """Get all jobs with a specific status.

        Args:
            status: JobStatus to filter by

        Returns:
            List of matching DataJob instances
        """
        return [job for job in self._jobs.values() if job.status == status]

    def get_all_jobs(self) -> List[DataJob]:
        """Get all jobs.

        Returns:
            List of all DataJob instances
        """
        return list(self._jobs.values())

    def get_stats(self) -> Dict[str, Any]:
        """Get orchestrator statistics.

        Returns:
            Dictionary with job counts and statistics
        """
        return {
            "total_jobs": len(self._jobs),
            "queue_size": self._job_queue.qsize(),
            "running_jobs": len(self._running_jobs),
            "pending": len(self.get_jobs_by_status(JobStatus.PENDING)),
            "running": len(self.get_jobs_by_status(JobStatus.RUNNING)),
            "completed": len(self.get_jobs_by_status(JobStatus.COMPLETED)),
            "failed": len(self.get_jobs_by_status(JobStatus.FAILED)),
            "execution_stats": dict(self._stats),
        }

    # ========================================================================
    # Cleanup
    # ========================================================================

    async def cancel_all_jobs(self) -> None:
        """Cancel all pending and running jobs."""
        # Cancel pending jobs
        while not self._job_queue.empty():
            try:
                job = self._job_queue.get_nowait()
                job.cancel()
            except asyncio.QueueEmpty:
                break

        # Cancel running tasks
        for task in self._running_jobs.values():
            task.cancel()

        if self._running_jobs:
            await asyncio.gather(*self._running_jobs.values(), return_exceptions=True)
            self._running_jobs.clear()

        logger.info("all_jobs_cancelled")

    def clear_completed_jobs(self) -> int:
        """Remove completed jobs from memory.

        Returns:
            Number of jobs cleared
        """
        completed_ids = [
            jid for jid, job in self._jobs.items() if job.is_terminal
        ]
        for jid in completed_ids:
            del self._jobs[jid]
        logger.info("completed_jobs_cleared", count=len(completed_ids))
        return len(completed_ids)
