"""Tests for application settings."""

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
