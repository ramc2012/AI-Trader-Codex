"""Historical OHLC collector for option symbols."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.config.market_hours import IST
from src.database.operations import upsert_option_ohlc_candles
from src.integrations.fyers_client import FyersClient
from src.utils.exceptions import DataFetchError
from src.utils.logger import get_logger

logger = get_logger(__name__)


class OptionOHLCCollector:
    """Collect and persist OHLC candles for individual option contracts."""

    def __init__(self, client: FyersClient):
        self._client = client

    @staticmethod
    def _normalize_expiry(expiry: str | date | None) -> date | None:
        if expiry is None:
            return None
        if isinstance(expiry, date):
            return expiry
        value = str(expiry).strip()
        if not value:
            return None
        for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _normalize_timestamp(timestamp: float | int) -> datetime:
        # Store naive timestamps to align with current ORM DateTime mapping.
        return datetime.fromtimestamp(timestamp, tz=IST).replace(tzinfo=None)

    def fetch_history(
        self,
        symbol: str,
        resolution: str = "15",
        days_back: int = 7,
        underlying: str | None = None,
        expiry: str | None = None,
        strike: float | None = None,
        option_type: str | None = None,
    ) -> list[dict[str, Any]]:
        end_date = datetime.now(tz=IST).date()
        start_date = end_date - timedelta(days=days_back)
        try:
            response = self._client.get_history(
                symbol=symbol,
                resolution=resolution,
                range_from=start_date.strftime("%Y-%m-%d"),
                range_to=end_date.strftime("%Y-%m-%d"),
            )
        except DataFetchError:
            return []
        candles = response.get("candles", [])
        expiry_date = self._normalize_expiry(expiry)
        out: list[dict[str, Any]] = []
        for candle in candles:
            if len(candle) < 6:
                continue
            out.append(
                {
                    "symbol": symbol,
                    "timeframe": resolution,
                    "timestamp": self._normalize_timestamp(candle[0]),
                    "open": float(candle[1]),
                    "high": float(candle[2]),
                    "low": float(candle[3]),
                    "close": float(candle[4]),
                    "volume": int(candle[5]),
                    "underlying": underlying,
                    "expiry": expiry_date,
                    "strike": strike,
                    "option_type": option_type,
                }
            )
        return out

    async def collect_and_store(
        self,
        session: AsyncSession,
        symbol: str,
        resolution: str = "15",
        days_back: int = 7,
        underlying: str | None = None,
        expiry: str | None = None,
        strike: float | None = None,
        option_type: str | None = None,
    ) -> int:
        candles = self.fetch_history(
            symbol=symbol,
            resolution=resolution,
            days_back=days_back,
            underlying=underlying,
            expiry=expiry,
            strike=strike,
            option_type=option_type,
        )
        if not candles:
            return 0
        inserted = await upsert_option_ohlc_candles(session, candles)
        logger.info(
            "option_ohlc_collected",
            symbol=symbol,
            resolution=resolution,
            candles=inserted,
        )
        return inserted
