"""Instrument and expiry registry with dynamic symbol discovery.

Builds a runtime registry of tradable index instruments, active futures symbols,
and near/next/far option expiries using live Fyers responses.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.config.constants import INDEX_INSTRUMENTS, IndexInstrument, build_monthly_futures_symbol
from src.config.market_hours import IST
from src.integrations.fyers_client import FyersClient
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ExpiryInfo:
    date: str
    expiry_ts: int


@dataclass
class InstrumentRegistryItem:
    name: str
    display_name: str
    spot_symbol: str
    futures_symbol: str | None
    exchange: str
    lot_size: int
    expiries: list[ExpiryInfo]
    last_synced_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "spot_symbol": self.spot_symbol,
            "futures_symbol": self.futures_symbol,
            "exchange": self.exchange,
            "lot_size": self.lot_size,
            "expiries": [
                {"date": e.date, "expiry_ts": e.expiry_ts}
                for e in self.expiries
            ],
            "last_synced_at": self.last_synced_at,
        }


class InstrumentRegistryService:
    """In-memory instrument registry refreshed from broker data."""

    def __init__(self) -> None:
        self._cache: dict[str, InstrumentRegistryItem] = {}
        self._last_refresh_at: datetime | None = None

    @property
    def last_refresh_at(self) -> datetime | None:
        return self._last_refresh_at

    def get_cache(self) -> dict[str, InstrumentRegistryItem]:
        return self._cache

    def get_item(self, name: str) -> InstrumentRegistryItem | None:
        return self._cache.get(name.upper())

    def get_spot_symbol(self, name: str) -> str | None:
        item = self.get_item(name)
        return item.spot_symbol if item else None

    def get_futures_symbol(self, name: str) -> str | None:
        item = self.get_item(name)
        return item.futures_symbol if item else None

    def refresh(self, client: FyersClient, include_expiries: int = 6) -> dict[str, InstrumentRegistryItem]:
        """Refresh the full registry from live Fyers data."""
        refreshed_at = datetime.now(tz=IST)
        new_cache: dict[str, InstrumentRegistryItem] = {}

        for name, instrument in INDEX_INSTRUMENTS.items():
            expiries = self._fetch_expiries(client, instrument.spot_symbol, include_expiries)
            futures_symbol = self._resolve_active_futures_symbol(client, instrument)

            new_cache[name] = InstrumentRegistryItem(
                name=name,
                display_name=self._display_name(name),
                spot_symbol=instrument.spot_symbol,
                futures_symbol=futures_symbol,
                exchange=instrument.exchange,
                lot_size=self._lot_size(name),
                expiries=expiries,
                last_synced_at=refreshed_at.isoformat(),
            )

        self._cache = new_cache
        self._last_refresh_at = refreshed_at
        logger.info("instrument_registry_refreshed", instruments=len(new_cache))
        return new_cache

    def _fetch_expiries(
        self,
        client: FyersClient,
        underlying: str,
        include_expiries: int,
    ) -> list[ExpiryInfo]:
        try:
            response = client.get_option_chain(symbol=underlying, strike_count=1)
            expiry_rows = response.get("data", {}).get("expiryData", [])
            expiries: list[ExpiryInfo] = []
            seen: set[int] = set()
            for row in expiry_rows:
                ts_raw = row.get("expiry")
                date = str(row.get("date", ""))
                try:
                    expiry_ts = int(ts_raw)
                except (TypeError, ValueError):
                    continue
                if expiry_ts in seen:
                    continue
                seen.add(expiry_ts)
                expiries.append(ExpiryInfo(date=date, expiry_ts=expiry_ts))
            expiries.sort(key=lambda e: e.expiry_ts)
            return expiries[:include_expiries]
        except Exception as exc:
            logger.warning("expiry_fetch_failed", symbol=underlying, error=str(exc))
            return []

    def _resolve_active_futures_symbol(
        self,
        client: FyersClient,
        instrument: IndexInstrument,
    ) -> str | None:
        """Resolve the first valid front-month futures symbol."""
        candidates = self._futures_candidates(instrument)
        for candidate in candidates:
            try:
                quote = client.get_quotes([candidate])
                rows = quote.get("d", [])
                if not rows:
                    continue
                payload = rows[0].get("v", {})
                if payload.get("s") == "error":
                    continue
                ltp = payload.get("lp")
                if ltp is None:
                    continue
                return candidate
            except Exception:
                continue
        return None

    def _futures_candidates(self, instrument: IndexInstrument) -> list[str]:
        now = datetime.now(tz=IST)
        candidates: list[str] = []
        year = now.year
        month = now.month
        # On the last Thursday of the month (monthly expiry day), skip the current
        # month's futures contract — it expires at end of day and the Fyers WebSocket
        # will reject subscriptions to expiring contracts, causing immediate close.
        start_offset = 1 if self._is_last_thursday_of_month(now) else 0
        for offset in range(start_offset, start_offset + 4):
            y, m = self._add_months(year, month, offset)
            dt = now.replace(year=y, month=m, day=1)
            candidates.append(
                build_monthly_futures_symbol(
                    root=instrument.futures_root,
                    exchange=instrument.exchange,
                    dt=dt,
                )
            )
        return candidates

    @staticmethod
    def _is_last_thursday_of_month(dt: datetime) -> bool:
        """Return True if *dt* falls on the last Thursday of its month.

        NSE and BSE monthly derivatives expire on the last Thursday of the month.
        On expiry day the contract still trades via REST but Fyers WS rejects new
        subscriptions, so we skip the current-month futures on that day.
        """
        if dt.weekday() != 3:  # 3 = Thursday
            return False
        # It is the last Thursday if adding 7 days would leave the month
        return (dt.day + 7) > calendar.monthrange(dt.year, dt.month)[1]

    @staticmethod
    def _add_months(year: int, month: int, offset: int) -> tuple[int, int]:
        total = (year * 12 + (month - 1)) + offset
        next_year = total // 12
        next_month = (total % 12) + 1
        return next_year, next_month

    @staticmethod
    def _display_name(name: str) -> str:
        mapping = {
            "NIFTY": "Nifty 50",
            "BANKNIFTY": "Bank Nifty",
            "FINNIFTY": "Fin Nifty",
            "MIDCPNIFTY": "Midcap Nifty",
            "SENSEX": "BSE Sensex",
        }
        return mapping.get(name, name)

    @staticmethod
    def _lot_size(name: str) -> int:
        lot_sizes = {
            "NIFTY": 25,
            "BANKNIFTY": 15,
            "FINNIFTY": 25,
            "MIDCPNIFTY": 50,
            "SENSEX": 10,
        }
        return lot_sizes.get(name, 1)
