"""Historical OHLC data collector for Nifty, Bank Nifty, and Sensex.

Fetches candle data across all timeframes from Fyers API with:
- Date range chunking to respect API limits
- Rate-limiting queue (1 req/sec)
- Data validation (OHLC logic, no gaps)
- Progress tracking for large backfills
- Resume capability (skip existing data via callback)
- Comprehensive logging
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable

from src.config.constants import (
    ALL_TIMEFRAMES,
    FYERS_RESOLUTION_MAP,
    INDEX_SYMBOLS,
    INTRADAY_TIMEFRAMES,
)
from src.config.market_hours import IST
from src.integrations.fyers_client import FyersClient
from src.utils.exceptions import DataFetchError, DataValidationError
from src.utils.logger import get_logger
from src.utils.validators import validate_ohlc, validate_volume

logger = get_logger(__name__)

# Fyers returns at most ~5000 candles per request.
# Chunk sizes (in days) per timeframe to stay well within limits.
_CHUNK_DAYS: dict[str, int] = {
    "1": 15,     # 1-min  → ~375 candles/day × 15 ≈ 5625
    "3": 30,     # 3-min  → ~125/day × 30
    "5": 60,     # 5-min  → ~75/day  × 60
    "15": 90,    # 15-min → ~25/day  × 90
    "30": 180,   # 30-min → ~13/day  × 180
    "60": 365,   # 60-min → ~6/day   × 365
    "D": 730,    # daily  → 1/day    × 730
    "W": 1825,   # weekly → ~0.2/day × 1825
    "M": 3650,   # monthly
}

# Maximum lookback per timeframe type
MAX_LOOKBACK_INTRADAY_DAYS = 90
MAX_LOOKBACK_DAILY_DAYS = 730


@dataclass
class Candle:
    """A single OHLCV candle."""

    symbol: str
    timeframe: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int

    def to_dict(self) -> dict[str, Any]:
        """Convert to a flat dictionary."""
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "timestamp": self.timestamp,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


@dataclass
class CollectionProgress:
    """Tracks progress of a data collection run."""

    symbol: str
    timeframe: str
    total_chunks: int = 0
    completed_chunks: int = 0
    total_candles: int = 0
    skipped_candles: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def progress_pct(self) -> float:
        if self.total_chunks == 0:
            return 0.0
        return (self.completed_chunks / self.total_chunks) * 100


@dataclass
class CollectionResult:
    """Result of a full collection run."""

    candles: list[Candle]
    progress: CollectionProgress
    duration_seconds: float = 0.0

    @property
    def success(self) -> bool:
        return len(self.progress.errors) == 0


# Type for the "already exists?" callback
ExistsCallback = Callable[[str, str, datetime], bool]


class OHLCCollector:
    """Collects historical OHLC data from Fyers for index symbols.

    Args:
        client: An authenticated FyersClient instance.
        symbols: List of symbols to collect. Defaults to INDEX_SYMBOLS.
        on_progress: Optional callback called after each chunk with CollectionProgress.
    """

    def __init__(
        self,
        client: FyersClient,
        symbols: list[str] | None = None,
        on_progress: Callable[[CollectionProgress], None] | None = None,
    ) -> None:
        self._client = client
        self._symbols = symbols or list(INDEX_SYMBOLS)
        self._on_progress = on_progress

    # =========================================================================
    # Public API
    # =========================================================================

    def collect(
        self,
        timeframes: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        exists_fn: ExistsCallback | None = None,
    ) -> list[CollectionResult]:
        """Collect historical data for all symbols and timeframes.

        Args:
            timeframes: Timeframes to collect. Defaults to ALL_TIMEFRAMES.
            start_date: Start date. Defaults to max lookback for each timeframe.
            end_date: End date. Defaults to today.
            exists_fn: Optional callback(symbol, timeframe, timestamp) -> bool.
                       Return True to skip that candle (resume support).

        Returns:
            List of CollectionResult, one per (symbol, timeframe) pair.
        """
        timeframes = timeframes or list(ALL_TIMEFRAMES)
        end_date = end_date or date.today()
        results: list[CollectionResult] = []

        for symbol in self._symbols:
            for tf in timeframes:
                tf_start = start_date or self._default_start(tf, end_date)
                logger.info(
                    "collection_start",
                    symbol=symbol,
                    timeframe=tf,
                    start=str(tf_start),
                    end=str(end_date),
                )
                result = self._collect_symbol_timeframe(
                    symbol=symbol,
                    timeframe=tf,
                    start_date=tf_start,
                    end_date=end_date,
                    exists_fn=exists_fn,
                )
                results.append(result)
                logger.info(
                    "collection_complete",
                    symbol=symbol,
                    timeframe=tf,
                    candles=len(result.candles),
                    errors=len(result.progress.errors),
                    duration=f"{result.duration_seconds:.1f}s",
                )

        return results

    def collect_symbol(
        self,
        symbol: str,
        timeframe: str,
        start_date: date,
        end_date: date | None = None,
        exists_fn: ExistsCallback | None = None,
    ) -> CollectionResult:
        """Collect data for a single symbol and timeframe.

        Args:
            symbol: Symbol string (e.g., 'NSE:NIFTY50-INDEX').
            timeframe: Timeframe string (e.g., '5', 'D').
            start_date: Start date.
            end_date: End date. Defaults to today.
            exists_fn: Optional resume callback.

        Returns:
            CollectionResult with candles and progress info.
        """
        end_date = end_date or date.today()
        return self._collect_symbol_timeframe(
            symbol=symbol,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            exists_fn=exists_fn,
        )

    # =========================================================================
    # Internal Collection Logic
    # =========================================================================

    def _collect_symbol_timeframe(
        self,
        symbol: str,
        timeframe: str,
        start_date: date,
        end_date: date,
        exists_fn: ExistsCallback | None = None,
    ) -> CollectionResult:
        """Fetch all chunks for one symbol+timeframe pair."""
        start_time = time.monotonic()
        chunks = self._build_date_chunks(timeframe, start_date, end_date)

        progress = CollectionProgress(
            symbol=symbol,
            timeframe=timeframe,
            total_chunks=len(chunks),
        )
        all_candles: list[Candle] = []

        for chunk_start, chunk_end in chunks:
            try:
                candles = self._fetch_chunk(symbol, timeframe, chunk_start, chunk_end)
                for candle in candles:
                    if exists_fn and exists_fn(symbol, timeframe, candle.timestamp):
                        progress.skipped_candles += 1
                        continue
                    all_candles.append(candle)
                progress.total_candles += len(candles)

            except (DataFetchError, DataValidationError) as exc:
                error_msg = (
                    f"Chunk {chunk_start}->{chunk_end}: {exc}"
                )
                progress.errors.append(error_msg)
                logger.warning(
                    "chunk_error",
                    symbol=symbol,
                    timeframe=timeframe,
                    chunk_start=str(chunk_start),
                    chunk_end=str(chunk_end),
                    error=str(exc),
                )

            progress.completed_chunks += 1
            if self._on_progress:
                self._on_progress(progress)

        duration = time.monotonic() - start_time
        return CollectionResult(
            candles=all_candles,
            progress=progress,
            duration_seconds=duration,
        )

    def _fetch_chunk(
        self, symbol: str, timeframe: str, start_date: date, end_date: date
    ) -> list[Candle]:
        """Fetch a single date-range chunk from Fyers and validate."""
        resolution = FYERS_RESOLUTION_MAP.get(timeframe, timeframe)

        response = self._client.get_history(
            symbol=symbol,
            resolution=resolution,
            range_from=start_date.strftime("%Y-%m-%d"),
            range_to=end_date.strftime("%Y-%m-%d"),
        )

        raw_candles: list[list] = response.get("candles", [])
        candles: list[Candle] = []

        for raw in raw_candles:
            candle = self._parse_candle(symbol, timeframe, raw)
            candles.append(candle)

        logger.debug(
            "chunk_fetched",
            symbol=symbol,
            timeframe=timeframe,
            start=str(start_date),
            end=str(end_date),
            candles=len(candles),
        )
        return candles

    def _parse_candle(
        self, symbol: str, timeframe: str, raw: list
    ) -> Candle:
        """Parse a raw [timestamp, O, H, L, C, V] list into a validated Candle.

        Args:
            symbol: Symbol string.
            timeframe: Timeframe string.
            raw: List of [timestamp, open, high, low, close, volume].

        Returns:
            Validated Candle dataclass.

        Raises:
            DataValidationError: If OHLC logic or volume is invalid.
        """
        if len(raw) < 6:
            raise DataValidationError(
                f"Expected 6 fields in candle, got {len(raw)}: {raw}"
            )

        ts_raw, open_, high, low, close, volume = raw[0], raw[1], raw[2], raw[3], raw[4], raw[5]

        # Parse timestamp — Fyers returns epoch seconds
        if isinstance(ts_raw, (int, float)):
            timestamp = datetime.fromtimestamp(ts_raw, tz=IST)
        else:
            raise DataValidationError(f"Unexpected timestamp format: {ts_raw}")

        # Validate
        validate_ohlc(open_, high, low, close)
        validate_volume(int(volume))

        return Candle(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=timestamp,
            open=float(open_),
            high=float(high),
            low=float(low),
            close=float(close),
            volume=int(volume),
        )

    # =========================================================================
    # Date Chunking
    # =========================================================================

    def _build_date_chunks(
        self, timeframe: str, start_date: date, end_date: date
    ) -> list[tuple[date, date]]:
        """Split a date range into chunks sized for the timeframe.

        Args:
            timeframe: Timeframe string.
            start_date: Overall start date.
            end_date: Overall end date.

        Returns:
            List of (chunk_start, chunk_end) tuples.
        """
        chunk_days = _CHUNK_DAYS.get(timeframe, 30)
        chunks: list[tuple[date, date]] = []
        current = start_date

        while current < end_date:
            chunk_end = min(current + timedelta(days=chunk_days), end_date)
            chunks.append((current, chunk_end))
            current = chunk_end + timedelta(days=1)

        return chunks

    def _default_start(self, timeframe: str, end_date: date) -> date:
        """Compute the default start date based on timeframe type.

        Intraday timeframes default to 90 days back.
        Daily/weekly/monthly default to 730 days (2 years).
        """
        if timeframe in INTRADAY_TIMEFRAMES:
            return end_date - timedelta(days=MAX_LOOKBACK_INTRADAY_DAYS)
        return end_date - timedelta(days=MAX_LOOKBACK_DAILY_DAYS)

    # =========================================================================
    # Quality Checks
    # =========================================================================

    @staticmethod
    def check_data_gaps(
        candles: list[Candle],
        expected_interval_minutes: int | None = None,
    ) -> list[tuple[datetime, datetime]]:
        """Detect gaps in a sorted list of candles.

        Args:
            candles: Sorted list of Candle objects.
            expected_interval_minutes: Expected minutes between candles.
                If None, inferred from the first two candles.

        Returns:
            List of (gap_start, gap_end) tuples where data is missing.
        """
        if len(candles) < 2:
            return []

        gaps: list[tuple[datetime, datetime]] = []

        if expected_interval_minutes is None:
            delta = candles[1].timestamp - candles[0].timestamp
            expected_interval_minutes = int(delta.total_seconds() / 60)

        max_gap = timedelta(minutes=expected_interval_minutes * 2)

        for i in range(1, len(candles)):
            diff = candles[i].timestamp - candles[i - 1].timestamp
            if diff > max_gap:
                gaps.append((candles[i - 1].timestamp, candles[i].timestamp))

        return gaps
