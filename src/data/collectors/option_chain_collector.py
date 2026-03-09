"""Option chain data collector for Nifty, Bank Nifty, and Sensex.

Periodically snapshots the full option chain (CE + PE) for index
symbols and stores strike-level data including LTP, OI, volume,
and Greeks (IV, delta, gamma, theta, vega).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable

from src.config.constants import INDEX_SYMBOLS
from src.config.market_hours import IST
from src.integrations.fyers_client import FyersClient
from src.utils.exceptions import DataFetchError
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class OptionStrike:
    """A single option strike from the chain."""

    timestamp: datetime
    underlying: str
    expiry: date
    strike: float
    option_type: str  # "CE" or "PE"
    symbol: str | None = None
    ltp: float | None = None
    oi: int = 0
    prev_oi: int = 0
    oich: int = 0
    volume: int = 0
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "underlying": self.underlying,
            "expiry": self.expiry,
            "strike": self.strike,
            "option_type": self.option_type,
            "symbol": self.symbol,
            "ltp": self.ltp,
            "oi": self.oi,
            "prev_oi": self.prev_oi,
            "oich": self.oich,
            "volume": self.volume,
            "iv": self.iv,
            "delta": self.delta,
            "gamma": self.gamma,
            "theta": self.theta,
            "vega": self.vega,
        }


@dataclass
class ChainSnapshot:
    """A complete option chain snapshot for one underlying at one point in time."""

    underlying: str
    timestamp: datetime
    expiry: date
    strikes: list[OptionStrike] = field(default_factory=list)
    spot_price: float | None = None

    @property
    def call_strikes(self) -> list[OptionStrike]:
        return [s for s in self.strikes if s.option_type == "CE"]

    @property
    def put_strikes(self) -> list[OptionStrike]:
        return [s for s in self.strikes if s.option_type == "PE"]

    @property
    def total_call_oi(self) -> int:
        return sum(s.oi for s in self.call_strikes)

    @property
    def total_put_oi(self) -> int:
        return sum(s.oi for s in self.put_strikes)

    @property
    def pcr(self) -> float | None:
        """Put-Call Ratio based on OI."""
        total_call = self.total_call_oi
        if total_call == 0:
            return None
        return self.total_put_oi / total_call

    @property
    def max_pain(self) -> float | None:
        """Estimate max pain strike (strike with least total OI payout)."""
        if not self.strikes:
            return None
        unique_strikes = sorted(set(s.strike for s in self.strikes))
        if not unique_strikes:
            return None

        call_oi = {s.strike: s.oi for s in self.call_strikes}
        put_oi = {s.strike: s.oi for s in self.put_strikes}

        min_pain = float("inf")
        max_pain_strike = unique_strikes[0]

        for expiry_price in unique_strikes:
            pain = 0.0
            for strike in unique_strikes:
                # Call writers pay when expiry > strike
                if expiry_price > strike:
                    pain += call_oi.get(strike, 0) * (expiry_price - strike)
                # Put writers pay when expiry < strike
                if expiry_price < strike:
                    pain += put_oi.get(strike, 0) * (strike - expiry_price)
            if pain < min_pain:
                min_pain = pain
                max_pain_strike = expiry_price

        return max_pain_strike


class OptionChainCollector:
    """Collects option chain snapshots from Fyers API.

    Args:
        client: An authenticated FyersClient.
        symbols: Underlying symbols. Defaults to INDEX_SYMBOLS.
        strike_count: Number of strikes above/below ATM to fetch.
    """

    def __init__(
        self,
        client: FyersClient,
        symbols: list[str] | None = None,
        strike_count: int = 10,
    ) -> None:
        self._client = client
        self._symbols = symbols or list(INDEX_SYMBOLS)
        self._strike_count = strike_count

    def collect_snapshot(
        self,
        symbol: str,
        expiry_timestamp: int | None = None,
    ) -> ChainSnapshot:
        """Fetch a single option chain snapshot for an underlying.

        Args:
            symbol: Underlying symbol (e.g., 'NSE:NIFTY50-INDEX').
            expiry_timestamp: Expiry epoch timestamp. None for nearest expiry.

        Returns:
            ChainSnapshot with all strikes.

        Raises:
            DataFetchError: If the API fails.
        """
        try:
            response = self._client.get_option_chain(
                symbol=symbol,
                strike_count=self._strike_count,
                timestamp=expiry_timestamp,
            )
        except Exception as exc:
            raise DataFetchError(f"Option chain fetch failed for {symbol}: {exc}") from exc

        now = datetime.now(tz=IST)
        strikes = self._parse_response(symbol, now, response)

        snapshot = ChainSnapshot(
            underlying=symbol,
            timestamp=now,
            expiry=strikes[0].expiry if strikes else date.today(),
            strikes=strikes,
        )

        logger.info(
            "option_chain_collected",
            symbol=symbol,
            strikes=len(strikes),
            pcr=snapshot.pcr,
        )
        return snapshot

    def collect_all(
        self, expiry_timestamp: int | None = None
    ) -> list[ChainSnapshot]:
        """Collect option chain snapshots for all configured symbols.

        Args:
            expiry_timestamp: Expiry epoch. None for nearest.

        Returns:
            List of ChainSnapshot objects.
        """
        snapshots: list[ChainSnapshot] = []
        for symbol in self._symbols:
            try:
                snapshot = self.collect_snapshot(symbol, expiry_timestamp)
                snapshots.append(snapshot)
            except DataFetchError as exc:
                logger.warning("chain_collect_failed", symbol=symbol, error=str(exc))
        return snapshots

    def _parse_response(
        self, symbol: str, timestamp: datetime, response: dict[str, Any]
    ) -> list[OptionStrike]:
        """Parse Fyers option chain response into OptionStrike objects.

        Fyers returns a flat `optionsChain` array with one row per CE/PE
        contract plus one underlying row (`strike_price=-1`).
        """
        strikes: list[OptionStrike] = []
        data = response.get("data", response)
        options_chain = data.get("optionsChain", [])

        for item in options_chain:
            option_type = str(item.get("option_type", "")).upper().strip()

            expiry_raw = item.get("expiry")
            if isinstance(expiry_raw, (int, float)):
                expiry_date = datetime.fromtimestamp(expiry_raw, tz=IST).date()
            elif isinstance(expiry_raw, str):
                # Accept both YYYY-MM-DD and DD-MM-YYYY payload variants.
                parsed = None
                for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
                    try:
                        parsed = datetime.strptime(expiry_raw, fmt).date()
                        break
                    except ValueError:
                        continue
                expiry_date = parsed or date.today()
            else:
                expiry_date = date.today()

            strike_price = float(item.get("strike_price", item.get("strikePrice", item.get("strike", 0))))
            if strike_price < 0:
                continue

            if option_type in {"CE", "PE"}:
                strikes.append(self._parse_strike(
                    timestamp, symbol, expiry_date, strike_price, option_type, item
                ))
                continue

            # Backward compatibility: nested CE/PE payloads.
            ce = item.get("ce", item.get("CE"))
            pe = item.get("pe", item.get("PE"))
            if isinstance(ce, dict):
                strikes.append(self._parse_strike(
                    timestamp, symbol, expiry_date, strike_price, "CE", ce
                ))
            if isinstance(pe, dict):
                strikes.append(self._parse_strike(
                    timestamp, symbol, expiry_date, strike_price, "PE", pe
                ))

        return strikes

    @staticmethod
    def _parse_strike(
        timestamp: datetime,
        underlying: str,
        expiry: date,
        strike: float,
        option_type: str,
        data: dict[str, Any],
    ) -> OptionStrike:
        """Parse a single CE or PE side from the chain response."""
        oi = int(data.get("oi", data.get("open_interest", 0)) or 0)
        oich = int(data.get("oich", data.get("oi_change", data.get("oichg", 0))) or 0)
        prev_oi = int(data.get("prev_oi", data.get("prevOi", 0)) or 0)
        if prev_oi <= 0 and oi > 0 and oich:
            prev_oi = max(oi - oich, 0)
        return OptionStrike(
            timestamp=timestamp,
            underlying=underlying,
            expiry=expiry,
            strike=strike,
            option_type=option_type,
            symbol=data.get("symbol"),
            ltp=data.get("ltp"),
            oi=oi,
            prev_oi=prev_oi,
            oich=oich,
            volume=int(data.get("volume", data.get("vol_traded_today", 0)) or 0),
            iv=data.get("iv", data.get("implied_vol")),
            delta=data.get("delta"),
            gamma=data.get("gamma"),
            theta=data.get("theta"),
            vega=data.get("vega"),
        )
