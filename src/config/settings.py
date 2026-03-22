"""Application settings loaded from environment variables.

Uses pydantic-settings for validation and type coercion.
All settings have sensible defaults for local development.

Priority order (highest → lowest):
  1. OS environment variables (set by Docker compose or the process env)
  2. DATA_DIR/.env  — persistent credentials written by the Settings page UI
  3. .env           — project-root file for local development

IMPORTANT: FYERS_APP_ID and FYERS_SECRET_KEY are intentionally NOT passed
as Docker compose environment variables.  If they were set as empty OS vars
they would permanently override whatever the user saved in DATA_DIR/.env.
"""

from enum import Enum
from functools import lru_cache
import os
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.config.agent_universe import (
    DEFAULT_AGENT_CRYPTO_SYMBOLS,
    DEFAULT_AGENT_NSE_SYMBOLS,
    DEFAULT_AGENT_US_SYMBOLS,
    normalize_nse_agent_symbols,
    parse_symbol_values,
    to_csv,
)


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class TradingMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


def _env_files() -> tuple[str, ...]:
    """Return env-file paths for pydantic-settings in priority order.

    pydantic-settings loads env files left-to-right; later files override
    earlier ones, BUT OS env vars always win over all file values.

    We list the persistent DATA_DIR/.env AFTER the project-root .env so
    that when credentials are updated via the UI they take precedence over
    anything in the project-root .env (which typically has empty placeholders).
    """
    data_dir = os.environ.get("DATA_DIR", ".")
    persistent_env = str(Path(data_dir) / ".env")
    return (".env", persistent_env)


class Settings(BaseSettings):
    """Application settings with validation."""

    model_config = SettingsConfigDict(
        env_file=_env_files(),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Allow extra environment variables without error
    )

    # --- App ---
    app_env: Environment = Environment.DEVELOPMENT
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_log_level: str = "DEBUG"
    app_startup_task_stagger_ms: int = Field(default=750, ge=0, le=10000)
    secret_key: str = "change_me_to_random_string_in_production"

    # --- Persistent data directory ---
    # In Docker this is /app/data (mounted as a named volume) so credentials
    # and token files survive container restarts.  Locally it defaults to the
    # project root (i.e. "." which resolves to where the process runs from).
    data_dir: str = "."

    # --- Fyers API ---
    fyers_app_id: str = ""
    fyers_secret_key: str = ""
    fyers_redirect_uri: str = "https://trade.fyers.in/api-login/redirect-uri/index.html"
    fyers_redirect_frontend_url: str = "http://localhost:3000/settings"
    finnhub_api_key: str = ""
    alphavantage_api_key: str = ""

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
    max_position_size_pct: float = Field(default=25.0, ge=0.1, le=25.0)
    max_concentration_pct: float = Field(default=30.0, ge=5.0, le=100.0)
    max_trade_risk_pct: float = Field(default=0.5, ge=0.05, le=5.0)
    max_open_positions: int = Field(default=6, ge=1, le=20)
    risk_circuit_breaker_enabled: bool = True

    # --- Data Collection ---
    fyers_rate_limit_per_sec: int = 1
    tick_batch_insert_interval: int = 10
    historical_data_retention_days: int = 730
    us_provider_rate_limit_cooldown_seconds: int = Field(default=900, ge=30, le=86400)
    us_provider_auth_cooldown_seconds: int = Field(default=3600, ge=60, le=86400)
    us_provider_error_cooldown_seconds: int = Field(default=180, ge=5, le=3600)
    us_provider_error_threshold: int = Field(default=3, ge=1, le=20)

    # --- Monitoring ---
    prometheus_port: int = 9090
    grafana_port: int = 3000

    # --- Alerts ---
    telegram_enabled: bool = True
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_status_interval_minutes: int = Field(default=30, ge=0, le=1440)

    # --- FX references (for consolidated multi-currency P&L) ---
    usd_inr_reference_rate: float = Field(default=83.0, ge=1.0, le=200.0)

    # --- AI Agent ---
    agent_auto_start: bool = False
    agent_auto_start_delay_seconds: int = Field(default=20, ge=0, le=600)
    agent_scan_interval: int = 30
    agent_periodic_scan_batch_size: int = Field(default=96, ge=0, le=500)
    agent_startup_initial_scan_limit: int = Field(default=24, ge=1, le=500)
    agent_startup_scan_limit_step: int = Field(default=24, ge=1, le=500)
    agent_startup_ramp_cycles: int = Field(default=4, ge=0, le=50)
    agent_default_timeframe: str = "5"
    agent_execution_timeframes: str = "3,5,15"
    agent_reference_timeframes: str = "60,D"
    agent_event_driven_enabled: bool = False
    agent_event_driven_markets: str = "NSE"
    agent_event_driven_debounce_ms: int = Field(default=1000, ge=100, le=5000)
    agent_event_driven_batch_size: int = Field(default=8, ge=1, le=50)
    agent_default_symbols: str = to_csv(DEFAULT_AGENT_NSE_SYMBOLS)
    agent_us_symbols: str = to_csv(DEFAULT_AGENT_US_SYMBOLS)
    agent_crypto_symbols: str = to_csv(DEFAULT_AGENT_CRYPTO_SYMBOLS)
    agent_trade_nse_when_open: bool = True
    agent_trade_us_when_open: bool = True
    agent_trade_us_options: bool = True
    agent_trade_crypto_24x7: bool = True
    agent_india_capital: float = Field(default=250000.0, ge=10000.0)
    agent_us_capital: float = Field(default=250000.0, ge=1000.0)
    agent_crypto_capital: float = Field(default=250000.0, ge=1000.0)
    agent_india_max_instrument_pct: float = Field(default=25.0, ge=1.0, le=100.0)
    agent_us_max_instrument_pct: float = Field(default=20.0, ge=1.0, le=100.0)
    agent_crypto_max_instrument_pct: float = Field(default=20.0, ge=1.0, le=100.0)
    agent_strategy_capital_bucket_enabled: bool = False
    agent_strategy_max_concurrent_positions: int = Field(default=4, ge=1, le=20)
    agent_liberal_bootstrap_enabled: bool = True
    agent_bootstrap_cycles: int = Field(default=300, ge=1, le=5000)
    agent_bootstrap_size_multiplier: float = Field(default=2.0, ge=1.0, le=5.0)
    agent_bootstrap_max_concentration_pct: float = Field(default=100.0, ge=30.0, le=100.0)
    agent_bootstrap_max_open_positions: int = Field(default=20, ge=1, le=100)
    agent_bootstrap_risk_per_trade_pct: float = Field(default=2.0, ge=0.1, le=10.0)
    agent_option_time_exit_minutes: int = Field(default=30, ge=1, le=480)
    agent_option_default_stop_loss_pct: float = Field(default=10.0, ge=1.0, le=90.0)
    agent_option_default_target_pct: float = Field(default=18.0, ge=1.0, le=400.0)
    agent_reinforcement_enabled: bool = True
    agent_reinforcement_alpha: float = Field(default=0.2, ge=0.01, le=1.0)
    agent_reinforcement_size_boost_pct: float = Field(default=60.0, ge=0.0, le=300.0)

    # --- Execution Architecture ---
    execution_core_backend: str = "python"
    execution_core_status_url: str = "http://localhost:8081"
    execution_transport: str = "inmemory"
    transport_mirror_enabled: bool = False
    transport_mirror_embedded_enabled: bool = True
    agent_latency_metrics_enabled: bool = True
    agent_latency_metrics_window: int = Field(default=256, ge=32, le=4096)
    event_direct_analytics_write_enabled: bool = True
    analytics_consumer_enabled: bool = False
    analytics_consumer_embedded_enabled: bool = True
    analytics_consumer_source: str = "kafka"
    analytics_consumer_group_id: str = "ai_trader_analytics"

    # --- NATS / JetStream ---
    nats_enabled: bool = False
    nats_url: str = "nats://localhost:4222"
    nats_stream_prefix: str = "ai_trader"

    # --- Kafka ---
    kafka_enabled: bool = False
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_topic_prefix: str = "ai_trader"

    # --- ClickHouse ---
    clickhouse_enabled: bool = False
    clickhouse_host: str = "localhost"
    clickhouse_http_port: int = 8123
    clickhouse_native_port: int = 9000
    clickhouse_database: str = "ai_trader"
    clickhouse_user: str = "default"
    clickhouse_password: str = ""

    # --- QuestDB ---
    questdb_enabled: bool = False
    questdb_host: str = "localhost"
    questdb_http_port: int = 9001
    questdb_pg_port: int = 8812
    questdb_ilp_port: int = 9009

    @property
    def data_path(self) -> Path:
        """Resolved Path for persistent data directory."""
        p = Path(self.data_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def credentials_env_path(self) -> Path:
        """Path to the persistent .env file that stores Fyers credentials."""
        return self.data_path / ".env"

    @property
    def token_file_path(self) -> Path:
        """Path to the persistent Fyers access-token JSON file."""
        return self.data_path / ".fyers_token.json"

    @property
    def pin_file_path(self) -> Path:
        """Path to the persistent encrypted FYERS PIN file."""
        return self.data_path / ".fyers_pin"

    @property
    def crypto_key_path(self) -> Path:
        """Path to the persistent Fernet key used for PIN encryption."""
        return self.data_path / ".crypto_key"

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
    def clickhouse_http_url(self) -> str:
        return f"http://{self.clickhouse_host}:{self.clickhouse_http_port}"

    @property
    def questdb_http_url(self) -> str:
        return f"http://{self.questdb_host}:{self.questdb_http_port}"

    @property
    def is_production(self) -> bool:
        return self.app_env == Environment.PRODUCTION

    @property
    def is_live_trading(self) -> bool:
        return self.trading_mode == TradingMode.LIVE

    @model_validator(mode="after")
    def _apply_persistent_secret_fallbacks(self) -> "Settings":
        """Prefer saved DATA_DIR/.env values when process env provides empty strings.

        Docker compose currently injects some optional credentials as empty OS env vars.
        Pydantic treats those empty OS values as higher priority than the persisted
        DATA_DIR/.env file, which makes saved provider keys disappear after restart.
        This validator restores the persisted values only when the resolved field is blank.
        """
        persistent_path = self.credentials_env_path
        if persistent_path.exists():
            try:
                persisted: dict[str, str] = {}
                for raw_line in persistent_path.read_text(encoding="utf-8").splitlines():
                    line = raw_line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    persisted[key] = value

                fallback_map = {
                    "FYERS_APP_ID": "fyers_app_id",
                    "FYERS_SECRET_KEY": "fyers_secret_key",
                    "FYERS_REDIRECT_URI": "fyers_redirect_uri",
                    "FINNHUB_API_KEY": "finnhub_api_key",
                    "ALPHAVANTAGE_API_KEY": "alphavantage_api_key",
                    "TELEGRAM_BOT_TOKEN": "telegram_bot_token",
                    "TELEGRAM_CHAT_ID": "telegram_chat_id",
                }

                for env_key, field_name in fallback_map.items():
                    current = getattr(self, field_name, "")
                    if str(current or "").strip():
                        continue
                    persisted_value = str(persisted.get(env_key, "") or "").strip()
                    if persisted_value:
                        setattr(self, field_name, persisted_value)

                if "TELEGRAM_ENABLED" not in os.environ:
                    persisted_enabled = str(persisted.get("TELEGRAM_ENABLED", "") or "").strip().lower()
                    if persisted_enabled in {"1", "true", "yes", "on"}:
                        self.telegram_enabled = True
                    elif persisted_enabled in {"0", "false", "no", "off"}:
                        self.telegram_enabled = False
            except Exception:
                pass

        self.agent_default_symbols = to_csv(normalize_nse_agent_symbols(self.agent_default_symbols))
        self.agent_us_symbols = to_csv(parse_symbol_values(self.agent_us_symbols))
        self.agent_crypto_symbols = to_csv(parse_symbol_values(self.agent_crypto_symbols))

        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
