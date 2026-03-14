"""Runtime manager for automatic collectors and live streams."""

from __future__ import annotations

import asyncio
from datetime import date, datetime

from src.config.constants import INDEX_INSTRUMENTS, INDEX_SYMBOLS
from src.config.market_hours import IST, is_market_day, is_pre_open_window, is_market_open
from src.config.settings import get_settings
from src.data.collectors.order_socket_collector import OrderSocketCollector
from src.data.collectors.tick_collector import TickCollector
from src.data.live.live_ohlc import LiveOHLCCacheBridge
from src.data.live.tick_stream import TickStreamBroker
from src.database.connection import get_session
from src.integrations.fyers_client import FyersClient
from src.utils.logger import get_logger
from src.watchlist.instrument_registry_service import InstrumentRegistryService
from src.watchlist.options_data_service import OptionsDataService

logger = get_logger(__name__)


class RuntimeManager:
    """Manages app-level background services.

    Services started:
    - Tick websocket collector (auto-start after auth)
    - Periodic option-chain snapshots persisted to DB
    - Periodic instrument/expiry refresh
    """

    def __init__(
        self,
        client: FyersClient,
        registry: InstrumentRegistryService,
    ) -> None:
        self._client = client
        self._registry = registry
        self._options_service = OptionsDataService(client)
        self._tick_broker = TickStreamBroker()
        self._candle_broker = TickStreamBroker()
        self._order_broker = TickStreamBroker()
        self._live_ohlc = LiveOHLCCacheBridge()

        self._running = False
        self._tasks: dict[str, asyncio.Task] = {}
        self._tick_collector: TickCollector | None = None
        self._order_collector: OrderSocketCollector | None = None
        self._last_preopen_refresh: date | None = None

    @property
    def broker(self) -> TickStreamBroker:
        return self._tick_broker

    @property
    def candle_broker(self) -> TickStreamBroker:
        return self._candle_broker

    @property
    def order_broker(self) -> TickStreamBroker:
        return self._order_broker

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            return
        if not self._client.is_authenticated:
            refreshed = await asyncio.to_thread(self._client.try_auto_refresh_with_saved_pin, False)
            if refreshed:
                logger.info("runtime_token_auto_refreshed")
            if not self._client.is_authenticated:
                logger.warning("runtime_not_started_not_authenticated")
                return

        loop = asyncio.get_running_loop()
        self._tick_broker.bind_loop(loop)
        self._candle_broker.bind_loop(loop)
        self._order_broker.bind_loop(loop)
        self._live_ohlc.bind_loop(loop)
        self._running = True

        await asyncio.to_thread(self._registry.refresh, self._client)
        await self._start_tick_collector()
        await self._start_order_collector()

        self._tasks["option_snapshot_loop"] = asyncio.create_task(self._option_snapshot_loop())
        self._tasks["instrument_refresh_loop"] = asyncio.create_task(self._instrument_refresh_loop())
        self._tasks["preopen_refresh_loop"] = asyncio.create_task(self._preopen_refresh_loop())
        # Watchdog: restarts tick collector if it exits unexpectedly
        # (handles prolonged internet outages where FyersDataSocket gives up)
        self._tasks["tick_watchdog"] = asyncio.create_task(self._tick_watchdog())
        logger.info("runtime_manager_started")

    async def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

        if self._tick_collector:
            await asyncio.to_thread(self._tick_collector.stop)
            self._tick_collector = None
        if self._order_collector:
            await asyncio.to_thread(self._order_collector.stop)
            self._order_collector = None
        logger.info("runtime_manager_stopped")

    async def restart_if_authenticated(self) -> None:
        if self._client.is_authenticated:
            await self.stop()
            await self.start()

    async def _start_tick_collector(self) -> None:
        access_token = self._client.access_token
        if not access_token:
            return

        symbols = []
        settings = get_settings()
        cache = self._registry.get_cache()
        for item in cache.values():
            if item.spot_symbol:
                symbols.append(item.spot_symbol)
            if item.futures_symbol:
                symbols.append(item.futures_symbol)
        symbols.extend(
            symbol.strip()
            for symbol in settings.agent_default_symbols.split(",")
            if symbol.strip()
        )
        if not symbols:
            symbols.extend(INDEX_SYMBOLS)
        symbols = sorted(set(symbols))
        if not symbols:
            logger.warning("tick_collector_not_started_no_symbols")
            return

        self._tick_collector = TickCollector(
            access_token=access_token,
            symbols=symbols,
            on_tick=lambda tick: self._tick_broker.publish(
                {
                    "type": "tick",
                    "symbol": tick.symbol,
                    "timestamp": tick.timestamp.isoformat(),
                    "ltp": tick.ltp,
                    "bid": tick.bid,
                    "ask": tick.ask,
                    "volume": tick.volume,
                    "cumulative_volume": tick.cumulative_volume,
                }
            ),
            on_candle=self._publish_live_candle,
        )
        self._tasks["tick_collector"] = asyncio.create_task(self._tick_collector.start_async())
        logger.info("tick_collector_started", symbols=len(symbols))

    async def _start_order_collector(self) -> None:
        access_token = self._client.access_token
        if not access_token:
            return

        self._order_collector = OrderSocketCollector(
            access_token=access_token,
            on_event=self._publish_order_event,
        )
        self._tasks["order_collector"] = asyncio.create_task(self._order_collector.start_async())
        logger.info("order_collector_started")

    def _publish_live_candle(self, candle: dict[str, object]) -> None:
        self._live_ohlc.ingest_candle(candle)
        self._candle_broker.publish(
            {
                "type": "candle",
                "symbol": candle.get("symbol"),
                "timeframe": candle.get("timeframe", "1"),
                "timestamp": candle.get("timestamp"),
                "open": candle.get("open"),
                "high": candle.get("high"),
                "low": candle.get("low"),
                "close": candle.get("close"),
                "volume": candle.get("volume"),
            }
        )

    def _publish_order_event(self, payload: dict[str, object]) -> None:
        self._order_broker.publish(payload)

    async def _tick_watchdog(self) -> None:
        """Monitor the tick-collector task and restart it if it exits.

        Handles cases where the Fyers WebSocket gives up after a prolonged
        internet outage.  Polls every 30 s; if the task is done (not still
        running), restarts it after a short back-off delay.
        """
        _RESTART_DELAY = 10   # seconds to wait before attempting restart
        _POLL_INTERVAL = 30   # seconds between liveness checks

        while self._running:
            try:
                await asyncio.sleep(_POLL_INTERVAL)

                if not self._running:
                    break

                task = self._tasks.get("tick_collector")
                if task is None or task.done():
                    logger.warning(
                        "tick_watchdog_detected_dead_collector",
                        done=task.done() if task else None,
                    )
                    # Stop the dead collector cleanly
                    if self._tick_collector:
                        try:
                            await asyncio.to_thread(self._tick_collector.stop)
                        except Exception:
                            pass
                        self._tick_collector = None

                    # Wait a bit before reconnecting (avoid hammering on outage)
                    await asyncio.sleep(_RESTART_DELAY)

                    if self._running and self._client.is_authenticated:
                        logger.info("tick_watchdog_restarting_collector")
                        await self._start_tick_collector()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("tick_watchdog_error", error=str(exc))

    async def _option_snapshot_loop(self) -> None:
        while self._running:
            try:
                if not is_market_open(datetime.now(tz=IST)):
                    await asyncio.sleep(15)
                    continue

                cache = self._registry.get_cache()
                symbols = [item.spot_symbol for item in cache.values() if item.spot_symbol]
                if not symbols:
                    symbols = [
                        INDEX_INSTRUMENTS["NIFTY"].spot_symbol,
                        INDEX_INSTRUMENTS["BANKNIFTY"].spot_symbol,
                        INDEX_INSTRUMENTS["FINNIFTY"].spot_symbol,
                        INDEX_INSTRUMENTS["SENSEX"].spot_symbol,
                    ]
                async with get_session() as session:
                    total_rows = 0
                    failures = 0
                    for symbol in symbols:
                        try:
                            chain = await asyncio.to_thread(
                                self._options_service.get_canonical_chain,
                                symbol,
                                12,
                                None,
                                3,
                            )
                            total_rows += await self._options_service.persist_canonical_chain(session, chain)
                        except Exception as exc:
                            failures += 1
                            logger.warning(
                                "option_snapshot_symbol_failed",
                                symbol=symbol,
                                error=str(exc),
                            )
                    await session.commit()
                logger.info("option_snapshot_persisted", rows=total_rows, failures=failures)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("option_snapshot_loop_error", error=str(exc))
            await asyncio.sleep(60)

    async def _instrument_refresh_loop(self) -> None:
        while self._running:
            try:
                await asyncio.to_thread(self._registry.refresh, self._client)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("instrument_refresh_loop_error", error=str(exc))
            await asyncio.sleep(1800)

    async def _preopen_refresh_loop(self) -> None:
        """Run a once-per-day refresh before market open for symbols/expiries."""
        while self._running:
            try:
                now = datetime.now(tz=IST)
                if not is_market_day(now):
                    await asyncio.sleep(300)
                    continue

                if is_pre_open_window(now) and self._last_preopen_refresh != now.date():
                    await asyncio.to_thread(self._registry.refresh, self._client)
                    symbols = [item.spot_symbol for item in self._registry.get_cache().values() if item.spot_symbol]
                    async with get_session() as session:
                        total_rows = 0
                        failures = 0
                        for symbol in symbols:
                            try:
                                chain = await asyncio.to_thread(
                                    self._options_service.get_canonical_chain,
                                    symbol,
                                    10,
                                    None,
                                    3,
                                )
                                total_rows += await self._options_service.persist_canonical_chain(session, chain)
                            except Exception as exc:
                                failures += 1
                                logger.warning(
                                    "preopen_snapshot_symbol_failed",
                                    symbol=symbol,
                                    error=str(exc),
                                )
                        await session.commit()
                    self._last_preopen_refresh = now.date()
                    logger.info(
                        "preopen_refresh_completed",
                        symbols=len(symbols),
                        rows=total_rows,
                        failures=failures,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("preopen_refresh_loop_error", error=str(exc))
            await asyncio.sleep(60)
