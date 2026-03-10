"""Canonical options data service for Fyers option-chain payloads."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.config.market_hours import IST
from src.database.operations import (
    get_option_chain_oi_history,
    get_option_chain_rows_for_expiry,
    upsert_option_chain_rows,
)
from src.integrations.fyers_client import FyersClient
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _normalize_option_type(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if raw in {"CE", "CALL", "C"}:
        return "CE"
    if raw in {"PE", "PUT", "P"}:
        return "PE"
    return ""


def _parse_source_ts(value: Any, fallback: datetime) -> datetime:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=IST)
        except (TypeError, ValueError, OSError):
            return fallback
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=IST)
            return parsed.astimezone(IST)
        except ValueError:
            return fallback
    return fallback


def _to_naive_datetime(value: datetime) -> datetime:
    """Convert timezone-aware datetime to naive timestamp for current ORM types."""
    if value.tzinfo is None:
        return value
    return value.astimezone(IST).replace(tzinfo=None)


def _empty_side() -> dict[str, Any]:
    return {
        "symbol": "",
        "ltp": 0.0,
        "oi": 0,
        "oich": 0,
        "prev_oi": 0,
        "iv": 0.0,
        "volume": 0,
        "bid": 0.0,
        "ask": 0.0,
        "delta": None,
        "gamma": None,
        "theta": None,
        "vega": None,
    }


class OptionsDataService:
    """Fetches, normalizes, and persists options chain snapshots."""

    def __init__(self, client: FyersClient):
        self._client = client

    def get_expiries(self, underlying: str) -> list[dict[str, Any]]:
        response = self._client.get_option_chain(symbol=underlying, strike_count=1)
        expiry_rows = response.get("data", {}).get("expiryData", [])
        expiries: list[dict[str, Any]] = []
        for row in expiry_rows:
            expiry_ts = _safe_int(row.get("expiry"))
            if not expiry_ts:
                continue
            expiries.append(
                {
                    "date": str(row.get("date", "")),
                    "expiry_ts": expiry_ts,
                    "expiry_iso": datetime.fromtimestamp(expiry_ts, tz=IST).date().isoformat(),
                }
            )
        return expiries

    def get_canonical_chain(
        self,
        underlying: str,
        strike_count: int = 10,
        expiry_ts: int | None = None,
        include_expiries: int = 3,
    ) -> dict[str, Any]:
        """Return a canonical CE/PE matrix for near/next/far expiries."""
        fetched_at = datetime.now(tz=IST)
        base_response = self._client.get_option_chain(
            symbol=underlying,
            strike_count=strike_count,
            timestamp=expiry_ts,
        )
        base_data = base_response.get("data", {})
        expiry_rows = base_data.get("expiryData", [])
        expiry_map: dict[int, str] = {}
        for row in expiry_rows:
            ts = _safe_int(row.get("expiry"))
            if ts:
                expiry_map[ts] = str(row.get("date", ""))

        now_ts = int(fetched_at.timestamp())
        target_expiries: list[int] = []
        if expiry_ts:
            target_expiries = [expiry_ts]
        else:
            valid_count = 0
            for row in expiry_rows:
                ts = _safe_int(row.get("expiry"))
                if ts and ts > now_ts:  # Only include future (non-expired) expirations
                    target_expiries.append(ts)
                    valid_count += 1
                    if valid_count >= include_expiries:
                        break

        if not target_expiries:
            logger.warning("option_chain_no_expiries", underlying=underlying)
            return {
                "underlying": underlying,
                "fetched_at": fetched_at.isoformat(),
                "data": {"expiryData": []},
                "quality": {
                    "is_stale": True,
                    "integrity_score": 0.0,
                    "notes": ["No expiries available from broker payload"],
                },
            }

        expiry_payloads: list[dict[str, Any]] = []
        for idx, ts in enumerate(target_expiries):
            if idx == 0:
                raw_data = base_data
            else:
                resp = self._client.get_option_chain(
                    symbol=underlying,
                    strike_count=strike_count,
                    timestamp=ts,
                )
                raw_data = resp.get("data", {})
            expiry_payloads.append(
                self._parse_flat_chain_payload(
                    underlying=underlying,
                    fetched_at=fetched_at,
                    raw_data=raw_data,
                    expiry_ts=ts,
                    expiry_label=expiry_map.get(ts, ""),
                )
            )

        integrity_scores = [p["quality"]["integrity_score"] for p in expiry_payloads]
        avg_integrity = sum(integrity_scores) / len(integrity_scores) if integrity_scores else 0.0
        return {
            "underlying": underlying,
            "fetched_at": fetched_at.isoformat(),
            "data": {"expiryData": expiry_payloads},
            "quality": {
                "is_stale": False,
                "integrity_score": round(avg_integrity, 4),
                "expiries_loaded": len(expiry_payloads),
            },
        }

    def _parse_flat_chain_payload(
        self,
        underlying: str,
        fetched_at: datetime,
        raw_data: dict[str, Any],
        expiry_ts: int,
        expiry_label: str,
    ) -> dict[str, Any]:
        options_chain = raw_data.get("optionsChain", [])
        spot = 0.0
        by_strike: dict[float, dict[str, Any]] = {}
        source_ts = _parse_source_ts(raw_data.get("source_ts", raw_data.get("timestamp")), fetched_at)
        source_latency_ms = max(int((fetched_at - source_ts).total_seconds() * 1000), 0)

        for row in options_chain:
            opt_type = _normalize_option_type(
                row.get("option_type", row.get("type", row.get("optionType")))
            )
            strike = _safe_float(
                row.get("strike_price", row.get("strikePrice", row.get("strike"))),
                default=-1.0,
            )

            if not opt_type or strike < 0:
                # underlying row
                if strike < 0 and _safe_float(row.get("ltp")) > 0:
                    spot = _safe_float(row.get("ltp"))
                continue

            if opt_type not in {"CE", "PE"}:
                continue

            if strike not in by_strike:
                by_strike[strike] = {
                    "strike": strike,
                    "ce": _empty_side(),
                    "pe": _empty_side(),
                    "quality": {"is_partial": False},
                }

            side = "ce" if opt_type == "CE" else "pe"
            oi = _safe_int(row.get("oi", row.get("open_interest")))
            oich = _safe_int(row.get("oich", row.get("oi_change", row.get("oichg", 0))))
            prev_oi = _safe_int(row.get("prev_oi", row.get("prevOi")))
            if prev_oi <= 0 and oi > 0 and oich:
                prev_oi = max(oi - oich, 0)
            by_strike[strike][side] = {
                "symbol": str(row.get("symbol", "")),
                "ltp": _safe_float(row.get("ltp")),
                "oi": oi,
                "oich": oich,
                "prev_oi": prev_oi,
                "iv": _safe_float(row.get("iv")),
                "volume": _safe_int(row.get("volume", row.get("vol"))),
                "bid": _safe_float(row.get("bid", row.get("bid_price"))),
                "ask": _safe_float(row.get("ask", row.get("ask_price"))),
                "delta": row.get("delta"),
                "gamma": row.get("gamma"),
                "theta": row.get("theta"),
                "vega": row.get("vega"),
            }

        strikes = sorted(by_strike.values(), key=lambda x: x["strike"])
        total_call_oi = sum(int(s["ce"]["oi"]) for s in strikes)
        total_put_oi = sum(int(s["pe"]["oi"]) for s in strikes)
        max_call_oi = max([int(s["ce"]["oi"]) for s in strikes], default=0)
        max_put_oi = max([int(s["pe"]["oi"]) for s in strikes], default=0)

        pair_count = 0
        nonzero_oi_count = 0
        partial_count = 0
        for row in strikes:
            ce = row["ce"]
            pe = row["pe"]
            is_partial = not bool(ce["symbol"] and pe["symbol"])
            row["quality"] = {"is_partial": is_partial}
            if not is_partial:
                pair_count += 1
            else:
                partial_count += 1
            if ce["oi"] > 0 or pe["oi"] > 0:
                nonzero_oi_count += 1
            row["oi_bar"] = {
                "ce_ratio": (ce["oi"] / max_call_oi) if max_call_oi > 0 else 0.0,
                "pe_ratio": (pe["oi"] / max_put_oi) if max_put_oi > 0 else 0.0,
            }

        total_rows = len(strikes)
        pair_ratio = (pair_count / total_rows) if total_rows else 0.0
        oi_ratio = (nonzero_oi_count / total_rows) if total_rows else 0.0
        integrity_score = (0.6 * pair_ratio) + (0.4 * oi_ratio)
        pcr = (total_put_oi / total_call_oi) if total_call_oi > 0 else 0.0

        expiry_iso = datetime.fromtimestamp(expiry_ts, tz=IST).date().isoformat()
        is_stale = source_latency_ms > 180_000
        return {
            "expiry": expiry_iso,
            "expiry_ts": expiry_ts,
            "expiry_label": expiry_label,
            "spot": spot,
            "total_call_oi": total_call_oi,
            "total_put_oi": total_put_oi,
            "pcr": pcr,
            "strikes": strikes,
            "quality": {
                "is_stale": is_stale,
                "integrity_score": round(integrity_score, 4),
                "rows": total_rows,
                "partial_rows": partial_count,
                "nonzero_oi_rows": nonzero_oi_count,
                "source_latency_ms": source_latency_ms,
            },
            "source_ts": source_ts.isoformat(),
        }

    async def persist_canonical_chain(
        self,
        session: AsyncSession,
        chain_payload: dict[str, Any],
    ) -> int:
        rows = self._to_option_chain_rows(chain_payload)
        if not rows:
            return 0
        return await upsert_option_chain_rows(session, rows)

    def _to_option_chain_rows(self, chain_payload: dict[str, Any]) -> list[dict[str, Any]]:
        fetched_at_raw = chain_payload.get("fetched_at")
        if fetched_at_raw:
            fetched_at = _parse_source_ts(fetched_at_raw, datetime.now(tz=IST))
        else:
            fetched_at = datetime.now(tz=IST)
        fetched_at_db = _to_naive_datetime(fetched_at)

        output: list[dict[str, Any]] = []
        underlying = chain_payload.get("underlying")
        expiry_data = chain_payload.get("data", {}).get("expiryData", [])
        for expiry_block in expiry_data:
            expiry_iso = expiry_block.get("expiry")
            if not expiry_iso:
                continue
            expiry_dt = date.fromisoformat(expiry_iso)
            chain_quality = expiry_block.get("quality", {})
            block_source_ts = _parse_source_ts(expiry_block.get("source_ts"), fetched_at)
            block_source_ts_db = _to_naive_datetime(block_source_ts)
            source_latency_ms = _safe_int(chain_quality.get("source_latency_ms"), default=0)
            for strike_row in expiry_block.get("strikes", []):
                strike = _safe_float(strike_row.get("strike"))
                row_quality = strike_row.get("quality", {})
                for option_type, side in (("CE", strike_row.get("ce", {})), ("PE", strike_row.get("pe", {}))):
                    if not side.get("symbol"):
                        continue
                    output.append(
                        {
                            "timestamp": fetched_at_db,
                            "source_ts": block_source_ts_db,
                            "underlying": underlying,
                            "expiry": expiry_dt,
                            "strike": strike,
                            "option_type": option_type,
                            "symbol": side.get("symbol"),
                            "ltp": _safe_float(side.get("ltp")),
                            "oi": _safe_int(side.get("oi")),
                            "prev_oi": _safe_int(side.get("prev_oi")),
                            "oich": _safe_int(side.get("oich")),
                            "volume": _safe_int(side.get("volume")),
                            "iv": _safe_float(side.get("iv")),
                            "delta": side.get("delta"),
                            "gamma": side.get("gamma"),
                            "theta": side.get("theta"),
                            "vega": side.get("vega"),
                            "integrity_score": float(chain_quality.get("integrity_score", 0.0)),
                            "is_stale": bool(chain_quality.get("is_stale", False)),
                            "is_partial": bool(row_quality.get("is_partial", False)),
                            "source_latency_ms": source_latency_ms,
                        }
                    )
        return output

    async def get_persisted_expiry_chain(
        self,
        session: AsyncSession,
        underlying: str,
        expiry_iso: str,
    ) -> list[dict[str, Any]]:
        expiry = date.fromisoformat(expiry_iso)
        rows = await get_option_chain_rows_for_expiry(session, underlying, expiry)
        return [r.to_dict() for r in rows]

    async def get_oi_history(
        self,
        session: AsyncSession,
        underlying: str,
        expiry_iso: str,
        strike: float,
        side: str,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        expiry = date.fromisoformat(expiry_iso)
        option_type = side.upper()
        rows = await get_option_chain_oi_history(
            session=session,
            underlying=underlying,
            expiry=expiry,
            strike=strike,
            option_type=option_type,
            limit=limit,
        )
        history: list[dict[str, Any]] = []
        prev_oi: int | None = None
        for row in rows:
            oi = int(row.oi or 0)
            oich = int(row.oich or 0)
            if oich == 0 and prev_oi is not None:
                oich = oi - prev_oi
            history.append(
                {
                    "timestamp": row.timestamp.isoformat(),
                    "oi": oi,
                    "change_in_oi": oich,
                    "ltp": float(row.ltp or 0),
                    "volume": int(row.volume or 0),
                    "integrity_score": float(row.integrity_score or 0),
                    "is_stale": bool(row.is_stale),
                }
            )
            prev_oi = oi
        return history
