-- =============================================================================
-- Nifty AI Trader — TimescaleDB Schema
-- =============================================================================
-- Run once against the nifty_trader database after TimescaleDB is installed.
-- This script is also mounted in docker/init-db/ for automatic setup.
-- =============================================================================

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ---------------------------------------------------------------------------
-- 1. Index OHLC data (candle sticks for Nifty, Bank Nifty, Sensex)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS index_ohlc (
    symbol      TEXT            NOT NULL,
    timeframe   TEXT            NOT NULL,
    timestamp   TIMESTAMPTZ     NOT NULL,
    open        NUMERIC(12, 2)  NOT NULL,
    high        NUMERIC(12, 2)  NOT NULL,
    low         NUMERIC(12, 2)  NOT NULL,
    close       NUMERIC(12, 2)  NOT NULL,
    volume      BIGINT          NOT NULL DEFAULT 0
);

-- Convert to hypertable (partitioned by timestamp)
SELECT create_hypertable(
    'index_ohlc',
    'timestamp',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '7 days'
);

-- Unique constraint to prevent duplicates
CREATE UNIQUE INDEX IF NOT EXISTS idx_ohlc_unique
    ON index_ohlc (symbol, timeframe, timestamp);

-- Query index: fetch candles by symbol + timeframe in time order
CREATE INDEX IF NOT EXISTS idx_ohlc_symbol_tf_time
    ON index_ohlc (symbol, timeframe, timestamp DESC);

-- ---------------------------------------------------------------------------
-- 2. Tick data (real-time LTP stream)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tick_data (
    symbol      TEXT            NOT NULL,
    timestamp   TIMESTAMPTZ     NOT NULL,
    ltp         NUMERIC(12, 2)  NOT NULL,
    bid         NUMERIC(12, 2),
    ask         NUMERIC(12, 2),
    volume      BIGINT          NOT NULL DEFAULT 0,
    open        NUMERIC(12, 2),
    high        NUMERIC(12, 2),
    low         NUMERIC(12, 2),
    close       NUMERIC(12, 2)
);

SELECT create_hypertable(
    'tick_data',
    'timestamp',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '1 day'
);

CREATE INDEX IF NOT EXISTS idx_tick_symbol_time
    ON tick_data (symbol, timestamp DESC);

-- ---------------------------------------------------------------------------
-- 3. Option chain snapshots
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS option_chain (
    timestamp       TIMESTAMPTZ     NOT NULL,
    underlying      TEXT            NOT NULL,
    expiry          DATE            NOT NULL,
    strike          NUMERIC(12, 2)  NOT NULL,
    option_type     TEXT            NOT NULL,  -- 'CE' or 'PE'
    ltp             NUMERIC(12, 2),
    oi              BIGINT          DEFAULT 0,
    volume          BIGINT          DEFAULT 0,
    iv              NUMERIC(8, 4),
    delta           NUMERIC(8, 6),
    gamma           NUMERIC(10, 8),
    theta           NUMERIC(10, 6),
    vega            NUMERIC(10, 6)
);

SELECT create_hypertable(
    'option_chain',
    'timestamp',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '1 day'
);

CREATE INDEX IF NOT EXISTS idx_optchain_underlying_expiry
    ON option_chain (underlying, expiry, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_optchain_strike
    ON option_chain (underlying, strike, option_type, timestamp DESC);

-- ---------------------------------------------------------------------------
-- 4. Trade log (every order placed by the system)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trade_log (
    id              BIGSERIAL       PRIMARY KEY,
    timestamp       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    symbol          TEXT            NOT NULL,
    side            TEXT            NOT NULL,  -- 'BUY' or 'SELL'
    quantity        INT             NOT NULL,
    price           NUMERIC(12, 2) NOT NULL,
    order_type      TEXT            NOT NULL,  -- 'MARKET', 'LIMIT', etc.
    product_type    TEXT            NOT NULL,  -- 'INTRADAY', 'CNC'
    order_id        TEXT,
    status          TEXT            NOT NULL DEFAULT 'PENDING',
    strategy        TEXT,
    notes           TEXT,
    pnl             NUMERIC(12, 2)
);

CREATE INDEX IF NOT EXISTS idx_trade_log_time
    ON trade_log (timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_trade_log_symbol
    ON trade_log (symbol, timestamp DESC);

-- ---------------------------------------------------------------------------
-- 5. Compression policies (reduce storage for older data)
-- ---------------------------------------------------------------------------
-- Compress index_ohlc chunks older than 30 days
ALTER TABLE index_ohlc SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol, timeframe',
    timescaledb.compress_orderby = 'timestamp'
);

SELECT add_compression_policy('index_ohlc', INTERVAL '30 days', if_not_exists => TRUE);

-- Compress tick_data chunks older than 3 days
ALTER TABLE tick_data SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol',
    timescaledb.compress_orderby = 'timestamp'
);

SELECT add_compression_policy('tick_data', INTERVAL '3 days', if_not_exists => TRUE);

-- Compress option_chain chunks older than 14 days
ALTER TABLE option_chain SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'underlying, option_type',
    timescaledb.compress_orderby = 'timestamp'
);

SELECT add_compression_policy('option_chain', INTERVAL '14 days', if_not_exists => TRUE);

-- ---------------------------------------------------------------------------
-- 6. Data retention policies
-- ---------------------------------------------------------------------------
-- Drop tick data older than 7 days
SELECT add_retention_policy('tick_data', INTERVAL '7 days', if_not_exists => TRUE);

-- Drop option chain data older than 90 days
SELECT add_retention_policy('option_chain', INTERVAL '90 days', if_not_exists => TRUE);

-- index_ohlc: no retention — keep forever (compression handles storage)
