"""Database connection manager for async SQLAlchemy + TimescaleDB.

Provides engine/session factories and a health check utility.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.sql import text

from src.config.settings import get_settings
from src.database.models import Base
from src.utils.logger import get_logger

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


_RUNTIME_MIGRATION_SQL: tuple[str, ...] = (
    # Ensure latest option_chain columns exist for legacy DB volumes.
    "ALTER TABLE IF EXISTS option_chain ADD COLUMN IF NOT EXISTS symbol TEXT",
    "ALTER TABLE IF EXISTS option_chain ADD COLUMN IF NOT EXISTS prev_oi BIGINT DEFAULT 0",
    "ALTER TABLE IF EXISTS option_chain ADD COLUMN IF NOT EXISTS oich BIGINT DEFAULT 0",
    "ALTER TABLE IF EXISTS option_chain ADD COLUMN IF NOT EXISTS source_ts TIMESTAMPTZ",
    "ALTER TABLE IF EXISTS option_chain ADD COLUMN IF NOT EXISTS source_latency_ms INT DEFAULT 0",
    "ALTER TABLE IF EXISTS option_chain ADD COLUMN IF NOT EXISTS integrity_score NUMERIC(6,4) DEFAULT 0",
    "ALTER TABLE IF EXISTS option_chain ADD COLUMN IF NOT EXISTS is_stale BOOLEAN DEFAULT FALSE",
    "ALTER TABLE IF EXISTS option_chain ADD COLUMN IF NOT EXISTS is_partial BOOLEAN DEFAULT FALSE",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_option_chain_unique ON option_chain (timestamp, underlying, expiry, strike, option_type)",
    "CREATE INDEX IF NOT EXISTS idx_optchain_underlying_expiry ON option_chain (underlying, expiry, timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_optchain_strike ON option_chain (underlying, strike, option_type, timestamp DESC)",
    # Ensure option_ohlc table exists for options charts and backtests.
    """
    CREATE TABLE IF NOT EXISTS option_ohlc (
        symbol          TEXT            NOT NULL,
        timeframe       TEXT            NOT NULL,
        timestamp       TIMESTAMPTZ     NOT NULL,
        open            NUMERIC(12, 2)  NOT NULL,
        high            NUMERIC(12, 2)  NOT NULL,
        low             NUMERIC(12, 2)  NOT NULL,
        close           NUMERIC(12, 2)  NOT NULL,
        volume          BIGINT          NOT NULL DEFAULT 0,
        underlying      TEXT,
        expiry          DATE,
        strike          NUMERIC(12, 2),
        option_type     TEXT,
        PRIMARY KEY (symbol, timeframe, timestamp)
    )
    """,
    # Convert option_ohlc into hypertable when TimescaleDB is available.
    """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM pg_extension
            WHERE extname = 'timescaledb'
        ) THEN
            PERFORM create_hypertable(
                'option_ohlc',
                'timestamp',
                if_not_exists => TRUE,
                chunk_time_interval => INTERVAL '1 day'
            );
        END IF;
    EXCEPTION
        WHEN OTHERS THEN
            NULL;
    END $$;
    """,
    "CREATE INDEX IF NOT EXISTS idx_option_ohlc_symbol_tf_time ON option_ohlc (symbol, timeframe, timestamp DESC)",
    # Tick retention + aggregate policies for orderflow/history stability.
    """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM pg_extension
            WHERE extname = 'timescaledb'
        ) THEN
            PERFORM remove_retention_policy('tick_data', if_exists => TRUE);
            PERFORM add_retention_policy('tick_data', INTERVAL '10 days', if_not_exists => TRUE);
        END IF;
    EXCEPTION
        WHEN OTHERS THEN
            NULL;
    END $$;
    """,
    """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM pg_extension
            WHERE extname = 'timescaledb'
        ) THEN
            EXECUTE $stmt$
                CREATE MATERIALIZED VIEW IF NOT EXISTS tick_data_1m
                WITH (timescaledb.continuous) AS
                SELECT
                    time_bucket(INTERVAL '1 minute', timestamp) AS bucket,
                    symbol,
                    AVG(ltp) AS avg_ltp,
                    MIN(ltp) AS low_ltp,
                    MAX(ltp) AS high_ltp,
                    SUM(volume) AS volume,
                    COUNT(*) AS ticks
                FROM tick_data
                GROUP BY bucket, symbol
                WITH NO DATA
            $stmt$;
        END IF;
    EXCEPTION
        WHEN OTHERS THEN
            NULL;
    END $$;
    """,
    "CREATE INDEX IF NOT EXISTS idx_tick_data_1m_symbol_time ON tick_data_1m (symbol, bucket DESC)",
    """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM pg_extension
            WHERE extname = 'timescaledb'
        ) THEN
            PERFORM add_continuous_aggregate_policy(
                'tick_data_1m',
                start_offset => INTERVAL '30 days',
                end_offset => INTERVAL '1 minute',
                schedule_interval => INTERVAL '5 minutes',
                if_not_exists => TRUE
            );
            PERFORM remove_retention_policy('tick_data_1m', if_exists => TRUE);
            PERFORM add_retention_policy('tick_data_1m', INTERVAL '180 days', if_not_exists => TRUE);
        END IF;
    EXCEPTION
        WHEN OTHERS THEN
            NULL;
    END $$;
    """,
)


def get_engine() -> AsyncEngine:
    """Return the singleton async engine, creating it on first call."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.app_debug,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            pool_recycle=3600,
        )
        logger.info("db_engine_created", url=settings.database_url.split("@")[-1])
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the singleton session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session with automatic commit/rollback."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def check_db_health() -> bool:
    """Test database connectivity with a simple query.

    Returns:
        True if the database is reachable, False otherwise.
    """
    try:
        async with get_session() as session:
            result = await session.execute(text("SELECT 1"))
            return result.scalar() == 1
    except Exception as exc:
        logger.error("db_health_check_failed", error=str(exc))
        return False


async def apply_runtime_migrations() -> None:
    """Run idempotent schema migrations required by current runtime code.

    These statements are safe to execute on every startup and are intended to
    heal legacy DB volumes that were initialized with older schemas.
    """
    engine = get_engine()
    failures = 0

    # Bootstrap missing tables on fresh DBs before applying fine-grained ALTER/INDEX statements.
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:
        failures += 1
        logger.warning("db_runtime_bootstrap_failed", error=str(exc))

    # Run each statement in an isolated transaction so one failure doesn't
    # abort the rest of the migration batch.
    for sql in _RUNTIME_MIGRATION_SQL:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(sql))
        except Exception as exc:
            failures += 1
            logger.warning(
                "db_runtime_migration_failed",
                sql=sql.strip().splitlines()[0][:120],
                error=str(exc),
            )

    logger.info(
        "db_runtime_migrations_applied",
        statements=len(_RUNTIME_MIGRATION_SQL) + 1,
        failures=failures,
    )


async def dispose_engine() -> None:
    """Dispose of the engine and release all connections."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("db_engine_disposed")
