"""Tests for application settings."""

from pathlib import Path

from src.config.agent_universe import (
    DEFAULT_AGENT_NSE_SYMBOLS,
    DEFAULT_AGENT_US_SYMBOLS,
    DEFAULT_WATCHLIST_NSE_SYMBOLS,
    LEGACY_AGENT_NSE_INDEX_ONLY_SYMBOLS,
    LEGACY_AGENT_NSE_SYMBOLS_PRE_MARCH_2026,
    to_csv,
)
from src.config.settings import Environment, Settings, TradingMode


class TestSettings:
    def test_defaults(self) -> None:
        settings = Settings(
            fyers_app_id="test",
            fyers_secret_key="test",
            _env_file=None,
        )
        assert settings.app_env == Environment.DEVELOPMENT
        assert settings.trading_mode == TradingMode.PAPER
        assert settings.max_daily_loss_pct == 2.0
        assert settings.max_concentration_pct == 30.0
        assert settings.max_open_positions == 6
        assert settings.execution_core_backend == "python"
        assert settings.nats_enabled is False
        assert settings.kafka_enabled is False
        assert settings.clickhouse_enabled is False
        assert settings.questdb_enabled is False
        assert settings.agent_event_driven_enabled is False
        assert settings.event_direct_analytics_write_enabled is True
        assert settings.analytics_consumer_enabled is False
        assert settings.analytics_consumer_embedded_enabled is True
        assert settings.analytics_consumer_source == "kafka"
        assert settings.app_startup_task_stagger_ms == 750
        assert settings.agent_auto_start_delay_seconds == 20
        assert settings.agent_periodic_scan_batch_size == 96
        assert settings.agent_startup_initial_scan_limit == 24
        assert settings.agent_startup_scan_limit_step == 24
        assert settings.agent_startup_ramp_cycles == 4
        assert settings.us_provider_rate_limit_cooldown_seconds == 900
        assert settings.us_provider_auth_cooldown_seconds == 3600
        assert settings.us_provider_error_cooldown_seconds == 180
        assert settings.us_provider_error_threshold == 3

    def test_database_url(self) -> None:
        settings = Settings(
            db_user="user",
            db_password="pass",
            db_host="localhost",
            db_port=5432,
            db_name="testdb",
            _env_file=None,
        )
        assert "user:pass@localhost:5432/testdb" in settings.database_url

    def test_redis_url_no_password(self) -> None:
        settings = Settings(redis_password="", _env_file=None)
        assert settings.redis_url == "redis://localhost:6379/0"

    def test_redis_url_with_password(self) -> None:
        settings = Settings(redis_password="secret", _env_file=None)
        assert ":secret@" in settings.redis_url

    def test_analytics_urls(self) -> None:
        settings = Settings(
            clickhouse_host="clickhouse",
            clickhouse_http_port=8123,
            questdb_host="questdb",
            questdb_http_port=9001,
            _env_file=None,
        )
        assert settings.clickhouse_http_url == "http://clickhouse:8123"
        assert settings.questdb_http_url == "http://questdb:9001"

    def test_is_production(self) -> None:
        settings = Settings(app_env=Environment.PRODUCTION, _env_file=None)
        assert settings.is_production is True

    def test_is_not_live_trading_by_default(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.is_live_trading is False

    def test_persisted_credentials_restore_blank_runtime_values(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text(
            "\n".join(
                [
                    "FYERS_APP_ID=APP-123",
                    "FYERS_SECRET_KEY=SECRET-456",
                    "FINNHUB_API_KEY=FINN-KEY-789",
                    "ALPHAVANTAGE_API_KEY=ALPHA-KEY-999",
                ]
            ),
            encoding="utf-8",
        )

        settings = Settings(
            _env_file=None,
            data_dir=str(tmp_path),
            fyers_app_id="",
            fyers_secret_key="",
            finnhub_api_key="",
            alphavantage_api_key="",
        )

        assert settings.fyers_app_id == "APP-123"
        assert settings.fyers_secret_key == "SECRET-456"
        assert settings.finnhub_api_key == "FINN-KEY-789"
        assert settings.alphavantage_api_key == "ALPHA-KEY-999"

    def test_agent_default_symbols_expand_legacy_index_only_override(self) -> None:
        settings = Settings(
            _env_file=None,
            agent_default_symbols=to_csv(LEGACY_AGENT_NSE_INDEX_ONLY_SYMBOLS),
        )

        assert settings.agent_default_symbols == to_csv(DEFAULT_AGENT_NSE_SYMBOLS)

    def test_agent_default_symbols_upgrade_legacy_full_override(self) -> None:
        settings = Settings(
            _env_file=None,
            agent_default_symbols=to_csv(LEGACY_AGENT_NSE_SYMBOLS_PRE_MARCH_2026),
        )

        assert settings.agent_default_symbols == to_csv(DEFAULT_AGENT_NSE_SYMBOLS)

    def test_agent_default_symbols_upgrade_previous_watchlist_default(self) -> None:
        settings = Settings(
            _env_file=None,
            agent_default_symbols=to_csv(DEFAULT_WATCHLIST_NSE_SYMBOLS),
        )

        assert settings.agent_default_symbols == to_csv(DEFAULT_AGENT_NSE_SYMBOLS)

    def test_agent_us_default_symbols_use_curated_200_stock_universe(self) -> None:
        settings = Settings(_env_file=None)

        assert settings.agent_us_symbols == to_csv(DEFAULT_AGENT_US_SYMBOLS)
        assert len(DEFAULT_AGENT_US_SYMBOLS) == 200
