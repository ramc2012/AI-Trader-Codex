"""Application settings loaded from environment variables.

Uses pydantic-settings for validation and type coercion.
All settings have sensible defaults for local development.
"""

from enum import Enum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class TradingMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class Settings(BaseSettings):
    """Application settings with validation."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # --- App ---
    app_env: Environment = Environment.DEVELOPMENT
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_log_level: str = "DEBUG"
    secret_key: str = "change_me_to_random_string_in_production"

    # --- Fyers API ---
    fyers_app_id: str = ""
    fyers_secret_key: str = ""
    fyers_redirect_uri: str = "http://localhost:8000/api/v1/auth/callback"

    # --- Database ---
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "nifty_trader"
    db_user: str = "trader"
    db_password: str = "change_me_in_production"

    # --- Redis ---
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""

    # --- Trading ---
    trading_mode: TradingMode = TradingMode.PAPER
    max_daily_loss_pct: float = Field(default=2.0, ge=0.1, le=10.0)
    max_position_size_pct: float = Field(default=5.0, ge=0.1, le=25.0)
    max_open_positions: int = Field(default=3, ge=1, le=10)

    # --- Data Collection ---
    fyers_rate_limit_per_sec: int = 1
    tick_batch_insert_interval: int = 10
    historical_data_retention_days: int = 730

    # --- Monitoring ---
    prometheus_port: int = 9090
    grafana_port: int = 3000

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def database_url_sync(self) -> str:
        return (
            f"postgresql+psycopg2://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def redis_url(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def is_production(self) -> bool:
        return self.app_env == Environment.PRODUCTION

    @property
    def is_live_trading(self) -> bool:
        return self.trading_mode == TradingMode.LIVE


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
