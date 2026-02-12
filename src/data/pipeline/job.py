"""Data collection job definitions and status tracking.

Represents individual data collection tasks with metadata, status,
and progress tracking capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from src.config.market_hours import IST


class JobStatus(str, Enum):
    """Data job execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobType(str, Enum):
    """Type of data collection job."""

    OHLC_HISTORICAL = "ohlc_historical"
    OHLC_REALTIME = "ohlc_realtime"
    TICK_STREAM = "tick_stream"
    OPTION_CHAIN = "option_chain"
    SYMBOL_INFO = "symbol_info"


@dataclass
class DataJob:
    """Represents a single data collection job.

    Args:
        job_id: Unique identifier for the job
        job_type: Type of data collection task
        symbol: Trading symbol to collect data for
        timeframe: Timeframe for OHLC data (if applicable)
        params: Additional job-specific parameters
        status: Current execution status
        created_at: Timestamp when job was created
        started_at: Timestamp when job started executing
        completed_at: Timestamp when job completed
        progress: Progress percentage (0-100)
        records_collected: Number of records collected
        error_message: Error message if job failed
        retry_count: Number of times job has been retried
        metadata: Additional metadata dictionary
    """

    job_id: str
    job_type: JobType
    symbol: str
    timeframe: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    status: JobStatus = JobStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(IST))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: float = 0.0
    records_collected: int = 0
    error_message: Optional[str] = None
    retry_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def start(self) -> None:
        """Mark job as running."""
        self.status = JobStatus.RUNNING
        self.started_at = datetime.now(IST)

    def complete(self, records_collected: int = 0) -> None:
        """Mark job as completed successfully.

        Args:
            records_collected: Total number of records collected
        """
        self.status = JobStatus.COMPLETED
        self.completed_at = datetime.now(IST)
        self.progress = 100.0
        self.records_collected = records_collected

    def fail(self, error_message: str) -> None:
        """Mark job as failed.

        Args:
            error_message: Description of the failure
        """
        self.status = JobStatus.FAILED
        self.completed_at = datetime.now(IST)
        self.error_message = error_message

    def cancel(self) -> None:
        """Cancel the job."""
        self.status = JobStatus.CANCELLED
        self.completed_at = datetime.now(IST)

    def update_progress(self, progress: float, records: int = 0) -> None:
        """Update job progress.

        Args:
            progress: Progress percentage (0-100)
            records: Current count of records collected
        """
        self.progress = min(100.0, max(0.0, progress))
        self.records_collected = records

    def can_retry(self, max_retries: int = 3) -> bool:
        """Check if job can be retried.

        Args:
            max_retries: Maximum number of retry attempts

        Returns:
            True if job failed and hasn't exceeded retry limit
        """
        return self.status == JobStatus.FAILED and self.retry_count < max_retries

    def increment_retry(self) -> None:
        """Increment retry counter and reset status to pending."""
        self.retry_count += 1
        self.status = JobStatus.PENDING
        self.error_message = None
        self.progress = 0.0

    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate job execution duration in seconds.

        Returns:
            Duration in seconds, or None if job hasn't started
        """
        if not self.started_at:
            return None
        end_time = self.completed_at or datetime.now(IST)
        return (end_time - self.started_at).total_seconds()

    @property
    def is_terminal(self) -> bool:
        """Check if job is in a terminal state.

        Returns:
            True if job is completed, failed, or cancelled
        """
        return self.status in {
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert job to dictionary representation.

        Returns:
            Dictionary with all job fields
        """
        return {
            "job_id": self.job_id,
            "job_type": self.job_type.value,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "params": self.params,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "progress": self.progress,
            "records_collected": self.records_collected,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "duration_seconds": self.duration_seconds,
            "metadata": self.metadata,
        }

    def __repr__(self) -> str:
        return (
            f"<DataJob(id={self.job_id}, type={self.job_type.value}, "
            f"symbol={self.symbol}, status={self.status.value}, "
            f"progress={self.progress:.1f}%)>"
        )
