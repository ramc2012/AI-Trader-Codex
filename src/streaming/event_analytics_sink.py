"""Shared analytics sink for ClickHouse and QuestDB event ingestion."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Dict, Optional

import httpx

from src.config.settings import Settings, get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

try:
    import orjson  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    orjson = None


@dataclass
class EventAnalyticsSinkStats:
    written: int = 0
    errors: int = 0
    started: bool = False


class EventAnalyticsSink:
    """Write normalized event envelopes into analytics backends."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._http_client: httpx.AsyncClient | None = None
        self._questdb_writer: asyncio.StreamWriter | None = None
        self._questdb_lock = asyncio.Lock()
        self._started = False
        self.stats = EventAnalyticsSinkStats()

    async def start(self) -> None:
        if self._started or not self.enabled:
            return
        if self._settings.clickhouse_enabled:
            self._http_client = httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0))
            await self._ensure_clickhouse_tables()
        self._started = True
        self.stats.started = True

    async def stop(self) -> None:
        if self._questdb_writer is not None:
            try:
                self._questdb_writer.close()
                await self._questdb_writer.wait_closed()
            except Exception:
                pass
            self._questdb_writer = None
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
        self._started = False
        self.stats.started = False

    @property
    def enabled(self) -> bool:
        return bool(self._settings.clickhouse_enabled or self._settings.questdb_enabled)

    async def write_envelope(self, envelope: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            if self._settings.clickhouse_enabled:
                await self._write_clickhouse(envelope)
            if self._settings.questdb_enabled:
                await self._write_questdb(envelope)
            self.stats.written += 1
        except Exception:
            self.stats.errors += 1
            raise

    async def _ensure_clickhouse_tables(self) -> None:
        if self._http_client is None:
            return
        execution_ddl = f"""
        CREATE TABLE IF NOT EXISTS {self._settings.clickhouse_database}.execution_events (
            event_time DateTime64(3, 'UTC'),
            event_date Date,
            event_id String,
            source LowCardinality(String),
            event_type LowCardinality(String),
            symbol String,
            order_id String,
            trade_id String,
            strategy String,
            market LowCardinality(String),
            payload String
        ) ENGINE = MergeTree
        ORDER BY (event_date, event_type, symbol, event_time)
        """
        market_ticks_ddl = f"""
        CREATE TABLE IF NOT EXISTS {self._settings.clickhouse_database}.market_ticks (
            event_time DateTime64(3, 'UTC'),
            event_date Date,
            symbol String,
            market LowCardinality(String),
            ltp Float64,
            bid Nullable(Float64),
            ask Nullable(Float64),
            volume Int64,
            cumulative_volume Nullable(Int64),
            payload String
        ) ENGINE = MergeTree
        ORDER BY (event_date, symbol, event_time)
        """
        market_bars_ddl = f"""
        CREATE TABLE IF NOT EXISTS {self._settings.clickhouse_database}.market_bars (
            event_time DateTime64(3, 'UTC'),
            event_date Date,
            symbol String,
            market LowCardinality(String),
            timeframe LowCardinality(String),
            open Float64,
            high Float64,
            low Float64,
            close Float64,
            volume Int64,
            payload String
        ) ENGINE = MergeTree
        ORDER BY (event_date, symbol, timeframe, event_time)
        """
        for ddl in (execution_ddl, market_ticks_ddl, market_bars_ddl):
            response = await self._http_client.post(
                self._settings.clickhouse_http_url,
                params={"query": ddl},
                auth=(self._settings.clickhouse_user, self._settings.clickhouse_password or ""),
            )
            response.raise_for_status()

    async def _write_clickhouse(self, envelope: Dict[str, Any]) -> None:
        if self._http_client is None:
            return
        stream = str(envelope.get("stream") or "execution")
        event_time = self._clickhouse_timestamp(str(envelope["event_time"]))
        event_date = event_time[:10]
        if stream == "market_ticks":
            row = {
                "event_time": event_time,
                "event_date": event_date,
                "symbol": envelope.get("symbol", ""),
                "market": envelope.get("market", ""),
                "ltp": float(envelope.get("ltp") or 0.0),
                "bid": self._clickhouse_float(envelope.get("bid")),
                "ask": self._clickhouse_float(envelope.get("ask")),
                "volume": int(envelope.get("volume") or 0),
                "cumulative_volume": self._clickhouse_int(envelope.get("cumulative_volume")),
                "payload": self._dumps_text(envelope.get("payload", {})),
            }
            table = "market_ticks"
        elif stream == "market_bars":
            row = {
                "event_time": event_time,
                "event_date": event_date,
                "symbol": envelope.get("symbol", ""),
                "market": envelope.get("market", ""),
                "timeframe": envelope.get("timeframe", ""),
                "open": float(envelope.get("open") or 0.0),
                "high": float(envelope.get("high") or 0.0),
                "low": float(envelope.get("low") or 0.0),
                "close": float(envelope.get("close") or 0.0),
                "volume": int(envelope.get("volume") or 0),
                "payload": self._dumps_text(envelope.get("payload", {})),
            }
            table = "market_bars"
        else:
            table = "execution_events"
            row = {
                "event_time": event_time,
                "event_date": event_date,
                "event_id": envelope["event_id"],
                "source": envelope["source"],
                "event_type": envelope["event_type"],
                "symbol": envelope.get("symbol", ""),
                "order_id": envelope.get("order_id", ""),
                "trade_id": envelope.get("trade_id", ""),
                "strategy": envelope.get("strategy", ""),
                "market": envelope.get("market", ""),
                "payload": self._dumps_text(envelope.get("payload", {})),
            }
        response = await self._http_client.post(
            self._settings.clickhouse_http_url,
            params={"query": f"INSERT INTO {self._settings.clickhouse_database}.{table} FORMAT JSONEachRow"},
            content=self._dumps_bytes(row),
            auth=(self._settings.clickhouse_user, self._settings.clickhouse_password or ""),
        )
        response.raise_for_status()

    async def _write_questdb(self, envelope: Dict[str, Any]) -> None:
        stream = str(envelope.get("stream") or "execution")
        payload_json = self._dumps_text(envelope.get("payload", {})).replace('"', '\\"')
        if stream == "market_ticks":
            line = (
                "market_ticks"
                f",symbol={self._escape_tag(envelope.get('symbol') or '_')}"
                f",market={self._escape_tag(envelope.get('market') or '_')}"
                f" ltp={float(envelope.get('ltp') or 0.0)},"
                f"bid={self._questdb_float(envelope.get('bid'))},"
                f"ask={self._questdb_float(envelope.get('ask'))},"
                f"volume={int(envelope.get('volume') or 0)}i,"
                f"cumulative_volume={self._questdb_int(envelope.get('cumulative_volume'))},"
                f'payload="{self._escape_field(payload_json)}" '
                f"{self._to_ns(envelope['event_time'])}\n"
            )
        elif stream == "market_bars":
            line = (
                "market_bars"
                f",symbol={self._escape_tag(envelope.get('symbol') or '_')}"
                f",market={self._escape_tag(envelope.get('market') or '_')}"
                f",timeframe={self._escape_tag(envelope.get('timeframe') or '_')}"
                f" open={float(envelope.get('open') or 0.0)},"
                f"high={float(envelope.get('high') or 0.0)},"
                f"low={float(envelope.get('low') or 0.0)},"
                f"close={float(envelope.get('close') or 0.0)},"
                f"volume={int(envelope.get('volume') or 0)}i,"
                f'payload="{self._escape_field(payload_json)}" '
                f"{self._to_ns(envelope['event_time'])}\n"
            )
        else:
            line = (
                "execution_events"
                f",source={self._escape_tag(envelope['source'])}"
                f",event_type={self._escape_tag(envelope['event_type'])}"
                f",symbol={self._escape_tag(envelope.get('symbol') or '_')}"
                f",strategy={self._escape_tag(envelope.get('strategy') or '_')}"
                f",market={self._escape_tag(envelope.get('market') or '_')}"
                f' event_id="{self._escape_field(envelope["event_id"])}",'
                f'order_id="{self._escape_field(envelope.get("order_id") or "")}",'
                f'trade_id="{self._escape_field(envelope.get("trade_id") or "")}",'
                f'payload="{self._escape_field(payload_json)}" '
                f"{self._to_ns(envelope['event_time'])}\n"
            )
        payload = line.encode("utf-8")
        writer = await self._get_questdb_writer()
        if writer is None:
            return
        try:
            writer.write(payload)
            await writer.drain()
        except (BrokenPipeError, ConnectionResetError, OSError):
            await self._reset_questdb_writer()
            writer = await self._get_questdb_writer()
            if writer is None:
                raise
            writer.write(payload)
            await writer.drain()

    async def _get_questdb_writer(self) -> asyncio.StreamWriter | None:
        async with self._questdb_lock:
            if self._questdb_writer is not None:
                return self._questdb_writer
            try:
                _, writer = await asyncio.open_connection(
                    self._settings.questdb_host,
                    self._settings.questdb_ilp_port,
                )
            except Exception as exc:
                logger.warning("questdb_ilp_connect_failed", error=str(exc))
                return None
            self._questdb_writer = writer
            return self._questdb_writer

    async def _reset_questdb_writer(self) -> None:
        async with self._questdb_lock:
            if self._questdb_writer is None:
                return
            try:
                self._questdb_writer.close()
                await self._questdb_writer.wait_closed()
            except Exception:
                pass
            self._questdb_writer = None

    @staticmethod
    def _escape_tag(value: str) -> str:
        return str(value or "_").replace("\\", "\\\\").replace(" ", "\\ ").replace(",", "\\,").replace("=", "\\=")

    @staticmethod
    def _escape_field(value: str) -> str:
        return str(value or "").replace("\\", "\\\\").replace('"', '\\"')

    @staticmethod
    def _to_ns(timestamp: str) -> int:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1_000_000_000)

    @staticmethod
    def _questdb_float(value: Any) -> str:
        if value in (None, ""):
            return "null"
        return str(float(value))

    @staticmethod
    def _questdb_int(value: Any) -> str:
        if value in (None, ""):
            return "null"
        return f"{int(value)}i"

    @staticmethod
    def _clickhouse_float(value: Any) -> float | None:
        if value in (None, ""):
            return None
        return float(value)

    @staticmethod
    def _clickhouse_int(value: Any) -> int | None:
        if value in (None, ""):
            return None
        return int(value)

    @staticmethod
    def _clickhouse_timestamp(timestamp: str) -> str:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    @staticmethod
    def _dumps_bytes(payload: Dict[str, Any]) -> bytes:
        if orjson is not None:
            return orjson.dumps(payload)
        return json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")

    @staticmethod
    def _dumps_text(payload: Dict[str, Any]) -> str:
        if orjson is not None:
            return orjson.dumps(payload).decode("utf-8")
        return json.dumps(payload, separators=(",", ":"), default=str)
