-- Incremental migration for canonical options data (safe to re-run).

ALTER TABLE IF EXISTS option_chain
    ADD COLUMN IF NOT EXISTS symbol TEXT,
    ADD COLUMN IF NOT EXISTS prev_oi BIGINT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS oich BIGINT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS source_ts TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS source_latency_ms INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS integrity_score NUMERIC(6,4) DEFAULT 0,
    ADD COLUMN IF NOT EXISTS is_stale BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS is_partial BOOLEAN DEFAULT FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS idx_option_chain_unique
    ON option_chain (timestamp, underlying, expiry, strike, option_type);

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
