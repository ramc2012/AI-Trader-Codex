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
    symbol          TEXT,
    ltp             NUMERIC(12, 2),
    oi              BIGINT          DEFAULT 0,
    prev_oi         BIGINT          DEFAULT 0,
    oich            BIGINT          DEFAULT 0,
    volume          BIGINT          DEFAULT 0,
    iv              NUMERIC(8, 4),
    delta           NUMERIC(8, 6),
    gamma           NUMERIC(10, 8),
    theta           NUMERIC(10, 6),
    vega            NUMERIC(10, 6),
    source_ts       TIMESTAMPTZ,
    source_latency_ms INT           DEFAULT 0,
    integrity_score NUMERIC(6, 4)   DEFAULT 0,
    is_stale        BOOLEAN         DEFAULT FALSE,
    is_partial      BOOLEAN         DEFAULT FALSE
);

SELECT create_hypertable(
    'option_chain',
    'timestamp',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '1 day'
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_option_chain_unique
    ON option_chain (timestamp, underlying, expiry, strike, option_type);

CREATE INDEX IF NOT EXISTS idx_optchain_underlying_expiry
    ON option_chain (underlying, expiry, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_optchain_strike
    ON option_chain (underlying, strike, option_type, timestamp DESC);

-- ---------------------------------------------------------------------------
-- 4. Option OHLC candles
-- ---------------------------------------------------------------------------
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
);

SELECT create_hypertable(
    'option_ohlc',
    'timestamp',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '1 day'
);

CREATE INDEX IF NOT EXISTS idx_option_ohlc_symbol_tf_time
    ON option_ohlc (symbol, timeframe, timestamp DESC);

-- ---------------------------------------------------------------------------
-- 5. Trade log (every order placed by the system)
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
-- 6. Compression policies (reduce storage for older data)
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

-- Continuous aggregate for older tick history (1-minute buckets)
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
WITH NO DATA;

CREATE INDEX IF NOT EXISTS idx_tick_data_1m_symbol_time
    ON tick_data_1m (symbol, bucket DESC);

SELECT add_continuous_aggregate_policy(
    'tick_data_1m',
    start_offset => INTERVAL '30 days',
    end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '5 minutes',
    if_not_exists => TRUE
);

-- Compress option_chain chunks older than 14 days
ALTER TABLE option_chain SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'underlying, option_type',
    timescaledb.compress_orderby = 'timestamp'
);

SELECT add_compression_policy('option_chain', INTERVAL '14 days', if_not_exists => TRUE);

-- Compress option_ohlc chunks older than 14 days
ALTER TABLE option_ohlc SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol, timeframe',
    timescaledb.compress_orderby = 'timestamp'
);

SELECT add_compression_policy('option_ohlc', INTERVAL '14 days', if_not_exists => TRUE);

-- ---------------------------------------------------------------------------
-- 7. Data retention policies
-- ---------------------------------------------------------------------------
-- Keep raw tick data for at least 10 days
SELECT add_retention_policy('tick_data', INTERVAL '10 days', if_not_exists => TRUE);

-- Keep aggregated 1-minute tick buckets for a longer horizon
SELECT add_retention_policy('tick_data_1m', INTERVAL '180 days', if_not_exists => TRUE);

-- Drop option chain data older than 90 days
SELECT add_retention_policy('option_chain', INTERVAL '90 days', if_not_exists => TRUE);

-- Drop option OHLC data older than 180 days
SELECT add_retention_policy('option_ohlc', INTERVAL '180 days', if_not_exists => TRUE);

-- index_ohlc: no retention — keep forever (compression handles storage)
