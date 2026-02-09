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
        assert settings.max_open_positions == 3

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

    def test_is_production(self) -> None:
        settings = Settings(app_env=Environment.PRODUCTION, _env_file=None)
        assert settings.is_production is True

    def test_is_not_live_trading_by_default(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.is_live_trading is False
