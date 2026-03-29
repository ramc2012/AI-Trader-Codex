"""FastAPI application entry point for the NiftyTraderGravity trading API."""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from datetime import datetime, timedelta

from src.api.dependencies import (
    get_fractal_scan_notifier,
    get_fyers_client,
    get_runtime_manager,
    get_telegram_notifier,
    get_tick_aggregator,
    get_trading_agent,
)
from src.api.routes.backtest import router as backtest_router
from src.api.routes.market_data import router as market_data_router
from src.api.routes.monitoring import router as monitoring_router
from src.api.routes.options import router as options_router
from src.api.routes.risk import router as risk_router
from src.api.routes.strategies import router as strategies_router
from src.api.routes.trading import router as trading_router
from src.api.routes.auth import router as auth_router
from src.api.routes.websocket import router as websocket_router
from src.api.routes.watchlist import router as watchlist_router, warm_global_watchlist_cache
from src.api.routes.rrg import router as rrg_router
from src.api.routes.tpo import router as tpo_router
from src.api.routes.atr import router as atr_router
from src.api.routes.analytics import router as analytics_router
from src.api.routes.orderflow import router as orderflow_router
from src.api.routes.oi_analysis import router as oi_router
from src.api.routes.money_flow import router as money_flow_router
from src.api.routes.crypto_flow import router as crypto_flow_router
from src.api.routes.history import router as history_router
from src.api.routes.agent import router as agent_router
from src.api.routes.fractal_profile import router as fractal_profile_router
from src.api.routes.scanner import router as scanner_router
from src.api.routes.fno_radar import router as fno_radar_router
from src.api.routes.options_watchlist import router as options_watchlist_router
from src.config.constants import (
    API_V1_PREFIX,
    ALL_TIMEFRAMES,
    ALL_WATCHLIST_SYMBOLS,
    FYERS_RESOLUTION_MAP,
)
from src.config.settings import get_settings
from src.database.connection import apply_runtime_migrations, dispose_engine, get_engine
from src.data.auto_collector import start_auto_collection
from src.data.ohlc_cache import get_ohlc_cache
from src.utils.logger import get_logger, setup_logging

logger = get_logger(__name__)


# ── Prioritised timeframes for cache warmup (most-used first) ─────────────────
_WARM_TIMEFRAMES = ["5", "15", "D", "60", "30", "1", "3", "W", "M"]
# Only go back this many days per timeframe during startup warmup
_WARMUP_DAYS: dict[str, int] = {
    "1": 5, "3": 10, "5": 30, "15": 45, "30": 60,
    "60": 90, "D": 365, "W": 730, "M": 1825,
}


async def _warm_ohlc_cache() -> None:
    """Load recent OHLC from DB into the in-memory cache at startup.

    Strategy:
    1. Small delay so the DB engine / pool is ready.
    2. Query DB for all symbols × timeframes.
    3. For any (symbol, timeframe) pair with no DB data, try Fyers REST API.
    4. Call cache.warm_up() with the consolidated dict.
    """
    await asyncio.sleep(5)          # let DB pool warm up first
    from src.database.connection import get_session_factory
    from src.database.operations import get_ohlc_candles

    cache = get_ohlc_cache()
    factory = get_session_factory()
    now = datetime.utcnow()

    data: dict = {}
    session = factory()
    try:
        for symbol in ALL_WATCHLIST_SYMBOLS:
            data[symbol] = {}
            for tf in _WARM_TIMEFRAMES:
                days = _WARMUP_DAYS.get(tf, 60)
                start = now - timedelta(days=days)
                try:
                    rows = await get_ohlc_candles(
                        session, symbol, tf, start, now, limit=2000
                    )
                    if rows:
                        data[symbol][tf] = [
                            {
                                "timestamp": r.timestamp.isoformat(),
                                "open": float(r.open),
                                "high": float(r.high),
                                "low": float(r.low),
                                "close": float(r.close),
                                "volume": r.volume,
                            }
                            for r in rows
                        ]
                except Exception as exc:
                    logger.warning(
                        "cache_warm_db_error",
                        symbol=symbol,
                        tf=tf,
                        error=str(exc),
                    )
    finally:
        await session.close()

    # Fill gaps from Fyers API where DB returned nothing
    try:
        fyers = get_fyers_client()
        if fyers.is_authenticated:
            for symbol in ALL_WATCHLIST_SYMBOLS:
                for tf in _WARM_TIMEFRAMES:
                    if data.get(symbol, {}).get(tf):
                        continue          # already have data from DB
                    days = _WARMUP_DAYS.get(tf, 30)
                    start = now - timedelta(days=days)
                    try:
                        raw = await asyncio.to_thread(
                            lambda s=symbol, t=tf, sd=start: fyers.get_history(
                                symbol=s,
                                resolution=t,
                                range_from=sd.strftime("%Y-%m-%d"),
                                range_to=now.strftime("%Y-%m-%d"),
                            )
                        )
                        if raw and raw.get("candles"):
                            data.setdefault(symbol, {})[tf] = [
                                {
                                    "timestamp": datetime.utcfromtimestamp(row[0]).isoformat(),
                                    "open": float(row[1]),
                                    "high": float(row[2]),
                                    "low": float(row[3]),
                                    "close": float(row[4]),
                                    "volume": int(row[5]),
                                }
                                for row in raw["candles"]
                            ]
                    except Exception as exc:
                        logger.debug(
                            "cache_warm_fyers_skip",
                            symbol=symbol,
                            tf=tf,
                            error=str(exc),
                        )
    except Exception as exc:
        logger.warning("cache_warm_fyers_client_error", error=str(exc))

    await cache.warm_up(data)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup/shutdown lifecycle."""
    setup_logging()
    logger.info("app_starting")
    # Eagerly create the DB engine so connection issues surface early
    get_engine()
    await apply_runtime_migrations()

    # Warm in-memory OHLC cache (DB → Fyers fallback)
    asyncio.create_task(_warm_ohlc_cache())
    # Start background data collectors and runtime services
    asyncio.create_task(start_auto_collection())
    runtime_manager = get_runtime_manager()
    asyncio.create_task(runtime_manager.start())
    asyncio.create_task(warm_global_watchlist_cache())
    # Start real-time tick aggregator (footprint/orderflow)
    aggregator = get_tick_aggregator()
    asyncio.create_task(aggregator.start())
    notifier = get_telegram_notifier()
    if notifier.is_configured:
        asyncio.create_task(notifier.start())
    fractal_scan_notifier = get_fractal_scan_notifier()
    asyncio.create_task(fractal_scan_notifier.start())

    settings = get_settings()
    if settings.agent_auto_start:
        async def _auto_start_agent() -> None:
            # Small delay so runtime/cache tasks begin first.
            await asyncio.sleep(2)
            try:
                agent = get_trading_agent()
                await agent.start()
                logger.info(
                    "agent_auto_start_enabled",
                    symbols=agent.config.symbols,
                    timeframe=agent.config.timeframe,
                    execution_timeframes=agent.config.execution_timeframes,
                    reference_timeframes=agent.config.reference_timeframes,
                    interval_seconds=agent.config.scan_interval_seconds,
                )
            except Exception as exc:
                logger.error("agent_auto_start_failed", error=str(exc))

        asyncio.create_task(_auto_start_agent())

    yield

    try:
        agent = get_trading_agent()
        await agent.stop()
    except Exception:
        pass

    try:
        notifier = get_telegram_notifier()
        await notifier.stop()
    except Exception:
        pass

    try:
        await fractal_scan_notifier.stop()
    except Exception:
        pass

    await runtime_manager.stop()
    await dispose_engine()
    logger.info("app_stopped")


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="NiftyTraderGravity API",
        description="NiftyTraderGravity — AI trading agent & market data API",
        version="0.1.0",
        lifespan=lifespan,
        debug=settings.app_debug,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if not settings.is_production else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routes
    app.include_router(market_data_router, prefix=API_V1_PREFIX)
    app.include_router(trading_router, prefix=API_V1_PREFIX)
    app.include_router(strategies_router, prefix=API_V1_PREFIX)
    app.include_router(risk_router, prefix=API_V1_PREFIX)
    app.include_router(monitoring_router, prefix=API_V1_PREFIX)
    app.include_router(backtest_router, prefix=API_V1_PREFIX)
    app.include_router(websocket_router, prefix=API_V1_PREFIX)
    app.include_router(auth_router, prefix=API_V1_PREFIX)
    app.include_router(watchlist_router, prefix=API_V1_PREFIX)
    app.include_router(options_router, prefix=API_V1_PREFIX)
    app.include_router(rrg_router, prefix=API_V1_PREFIX)
    app.include_router(tpo_router, prefix=API_V1_PREFIX)
    app.include_router(atr_router, prefix=API_V1_PREFIX)
    app.include_router(analytics_router, prefix=API_V1_PREFIX)
    app.include_router(orderflow_router, prefix=API_V1_PREFIX)
    app.include_router(oi_router, prefix=API_V1_PREFIX)
    app.include_router(money_flow_router, prefix=API_V1_PREFIX)
    app.include_router(crypto_flow_router, prefix=API_V1_PREFIX)
    app.include_router(history_router, prefix=API_V1_PREFIX)
    app.include_router(scanner_router, prefix=API_V1_PREFIX)
    app.include_router(fractal_profile_router, prefix=API_V1_PREFIX)
    app.include_router(fno_radar_router, prefix=API_V1_PREFIX)
    app.include_router(options_watchlist_router, prefix=API_V1_PREFIX)
    app.include_router(agent_router, prefix=API_V1_PREFIX)

    # Prometheus Metrics
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)

    return app


app = create_app()
