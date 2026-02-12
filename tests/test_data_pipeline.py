"""Tests for data pipeline orchestration.

Tests job creation, execution, queue management, and scheduler functionality.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.market_hours import IST
from src.data.pipeline.job import DataJob, JobStatus, JobType
from src.data.pipeline.orchestrator import DataOrchestrator
from src.data.pipeline.scheduler import DataScheduler, ScheduledTask


# ==============================================================================
# DataJob Tests
# ==============================================================================


def test_data_job_creation():
    """Test DataJob creation with default values."""
    job = DataJob(
        job_id="test_job_1",
        job_type=JobType.OHLC_HISTORICAL,
        symbol="NSE:NIFTY50-INDEX",
        timeframe="D",
    )

    assert job.job_id == "test_job_1"
    assert job.job_type == JobType.OHLC_HISTORICAL
    assert job.symbol == "NSE:NIFTY50-INDEX"
    assert job.timeframe == "D"
    assert job.status == JobStatus.PENDING
    assert job.progress == 0.0
    assert job.records_collected == 0
    assert job.retry_count == 0


def test_data_job_lifecycle():
    """Test DataJob state transitions."""
    job = DataJob(
        job_id="test_job_2",
        job_type=JobType.OHLC_HISTORICAL,
        symbol="NSE:NIFTY50-INDEX",
    )

    # Start job
    job.start()
    assert job.status == JobStatus.RUNNING
    assert job.started_at is not None

    # Update progress
    job.update_progress(50.0, 100)
    assert job.progress == 50.0
    assert job.records_collected == 100

    # Complete job
    job.complete(records_collected=200)
    assert job.status == JobStatus.COMPLETED
    assert job.progress == 100.0
    assert job.records_collected == 200
    assert job.completed_at is not None
    assert job.is_terminal is True


def test_data_job_failure_and_retry():
    """Test job failure and retry logic."""
    job = DataJob(
        job_id="test_job_3",
        job_type=JobType.OHLC_HISTORICAL,
        symbol="NSE:NIFTY50-INDEX",
    )

    # Fail job
    job.fail("API error: timeout")
    assert job.status == JobStatus.FAILED
    assert job.error_message == "API error: timeout"
    assert job.is_terminal is True

    # Can retry
    assert job.can_retry(max_retries=3) is True

    # Retry job
    job.increment_retry()
    assert job.retry_count == 1
    assert job.status == JobStatus.PENDING
    assert job.error_message is None


def test_data_job_to_dict():
    """Test DataJob serialization."""
    job = DataJob(
        job_id="test_job_4",
        job_type=JobType.OHLC_HISTORICAL,
        symbol="NSE:NIFTY50-INDEX",
        timeframe="D",
    )

    job_dict = job.to_dict()

    assert job_dict["job_id"] == "test_job_4"
    assert job_dict["job_type"] == "ohlc_historical"
    assert job_dict["symbol"] == "NSE:NIFTY50-INDEX"
    assert job_dict["timeframe"] == "D"
    assert job_dict["status"] == "pending"


# ==============================================================================
# DataOrchestrator Tests
# ==============================================================================


@pytest.fixture
def mock_fyers_client():
    """Mock FyersClient for testing."""
    return MagicMock()


@pytest.fixture
def mock_db_session():
    """Mock database session for testing."""
    return AsyncMock()


@pytest.fixture
def orchestrator(mock_fyers_client, mock_db_session):
    """Create DataOrchestrator instance for testing."""
    return DataOrchestrator(
        fyers_client=mock_fyers_client,
        db_session=mock_db_session,
        max_concurrent_jobs=2,
        max_retries=2,
    )


def test_orchestrator_create_ohlc_job(orchestrator):
    """Test OHLC job creation."""
    job = orchestrator.create_ohlc_job(
        symbol="NSE:NIFTY50-INDEX",
        timeframe="D",
        days_back=90,
    )

    assert job.job_type == JobType.OHLC_HISTORICAL
    assert job.symbol == "NSE:NIFTY50-INDEX"
    assert job.timeframe == "D"
    assert job.params["days_back"] == 90
    assert job.job_id in orchestrator._jobs


def test_orchestrator_create_option_chain_job(orchestrator):
    """Test option chain job creation."""
    job = orchestrator.create_option_chain_job(
        symbol="NSE:NIFTY50-INDEX",
        expiry_date="2024-12-26",
    )

    assert job.job_type == JobType.OPTION_CHAIN
    assert job.symbol == "NSE:NIFTY50-INDEX"
    assert job.params["expiry_date"] == "2024-12-26"


@pytest.mark.asyncio
async def test_orchestrator_submit_job(orchestrator):
    """Test job submission to queue."""
    job = orchestrator.create_ohlc_job(
        symbol="NSE:NIFTY50-INDEX",
        timeframe="D",
    )

    await orchestrator.submit_job(job)
    assert orchestrator._job_queue.qsize() == 1


def test_orchestrator_get_jobs_by_status(orchestrator):
    """Test filtering jobs by status."""
    job1 = orchestrator.create_ohlc_job(symbol="NSE:NIFTY50-INDEX", timeframe="D")
    job2 = orchestrator.create_ohlc_job(symbol="NSE:NIFTYBANK-INDEX", timeframe="D")

    job1.start()
    job2.complete()

    pending_jobs = orchestrator.get_jobs_by_status(JobStatus.PENDING)
    running_jobs = orchestrator.get_jobs_by_status(JobStatus.RUNNING)
    completed_jobs = orchestrator.get_jobs_by_status(JobStatus.COMPLETED)

    assert len(pending_jobs) == 0
    assert len(running_jobs) == 1
    assert len(completed_jobs) == 1


def test_orchestrator_get_stats(orchestrator):
    """Test orchestrator statistics."""
    orchestrator.create_ohlc_job(symbol="NSE:NIFTY50-INDEX", timeframe="D")
    orchestrator.create_ohlc_job(symbol="NSE:NIFTYBANK-INDEX", timeframe="D")

    stats = orchestrator.get_stats()

    assert stats["total_jobs"] == 2
    assert stats["pending"] == 2
    assert "execution_stats" in stats


# ==============================================================================
# DataScheduler Tests
# ==============================================================================


@pytest.fixture
def scheduler(orchestrator):
    """Create DataScheduler instance for testing."""
    return DataScheduler(
        orchestrator=orchestrator,
        check_interval=1.0,
    )


def test_scheduled_task_creation():
    """Test ScheduledTask creation."""
    def job_factory():
        return DataJob(
            job_id="scheduled_job",
            job_type=JobType.OHLC_HISTORICAL,
            symbol="NSE:NIFTY50-INDEX",
        )

    task = ScheduledTask(
        name="daily_collection",
        schedule=3600,  # 1 hour
        job_factory=job_factory,
        enabled=True,
    )

    assert task.name == "daily_collection"
    assert task.schedule == 3600
    assert task.enabled is True
    assert task.run_count == 0


def test_scheduled_task_should_run():
    """Test task execution timing."""
    def job_factory():
        return DataJob(
            job_id="test",
            job_type=JobType.OHLC_HISTORICAL,
            symbol="NSE:NIFTY50-INDEX",
        )

    task = ScheduledTask(
        name="test_task",
        schedule=60,  # 1 minute
        job_factory=job_factory,
    )

    now = datetime.now(IST)

    # First run should execute
    assert task.should_run(now) is True

    # Set next run to future
    task.next_run = now + timedelta(minutes=5)
    assert task.should_run(now) is False

    # Should run when time passed
    future = now + timedelta(minutes=10)
    assert task.should_run(future) is True


def test_scheduler_register_task(scheduler):
    """Test task registration."""
    def job_factory():
        return DataJob(
            job_id="test",
            job_type=JobType.OHLC_HISTORICAL,
            symbol="NSE:NIFTY50-INDEX",
        )

    task = ScheduledTask(
        name="test_task",
        schedule=60,
        job_factory=job_factory,
    )

    scheduler.register_task(task)
    assert "test_task" in scheduler._tasks
    assert scheduler.task_count == 1


def test_scheduler_enable_disable_task(scheduler):
    """Test task enable/disable."""
    def job_factory():
        return DataJob(
            job_id="test",
            job_type=JobType.OHLC_HISTORICAL,
            symbol="NSE:NIFTY50-INDEX",
        )

    task = ScheduledTask(
        name="test_task",
        schedule=60,
        job_factory=job_factory,
    )

    scheduler.register_task(task)

    # Disable task
    result = scheduler.disable_task("test_task")
    assert result is True
    assert scheduler._tasks["test_task"].enabled is False

    # Enable task
    result = scheduler.enable_task("test_task")
    assert result is True
    assert scheduler._tasks["test_task"].enabled is True


def test_scheduler_get_task_status(scheduler):
    """Test task status retrieval."""
    def job_factory():
        return DataJob(
            job_id="test",
            job_type=JobType.OHLC_HISTORICAL,
            symbol="NSE:NIFTY50-INDEX",
        )

    task = ScheduledTask(
        name="test_task",
        schedule=60,
        job_factory=job_factory,
    )

    scheduler.register_task(task)
    status = scheduler.get_task_status("test_task")

    assert status is not None
    assert status["name"] == "test_task"
    assert status["enabled"] is True
    assert status["schedule"] == 60


def test_scheduler_register_default_tasks(scheduler):
    """Test default task registration."""
    scheduler.register_default_tasks()

    assert scheduler.task_count >= 3  # At least 3 default tasks
    assert "daily_ohlc_eod" in scheduler._tasks
    assert "intraday_ohlc" in scheduler._tasks
    assert "option_chain_snapshots" in scheduler._tasks
