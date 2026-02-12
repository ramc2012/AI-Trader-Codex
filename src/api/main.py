"""FastAPI application entry point for the Nifty AI Trader data API."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes.backtest import router as backtest_router
from src.api.routes.market_data import router as market_data_router
from src.api.routes.monitoring import router as monitoring_router
from src.api.routes.risk import router as risk_router
from src.api.routes.strategies import router as strategies_router
from src.api.routes.trading import router as trading_router
from src.api.routes.auth import router as auth_router
from src.api.routes.websocket import router as websocket_router
from src.config.constants import API_V1_PREFIX
from src.config.settings import get_settings
from src.database.connection import dispose_engine, get_engine
from src.utils.logger import get_logger, setup_logging

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup/shutdown lifecycle."""
    setup_logging()
    logger.info("app_starting")
    # Eagerly create the DB engine so connection issues surface early
    get_engine()
    yield
    await dispose_engine()
    logger.info("app_stopped")


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Nifty AI Trader API",
        description="Market data access and trading system API",
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

    return app


app = create_app()
