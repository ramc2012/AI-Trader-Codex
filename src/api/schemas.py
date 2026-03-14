"""Pydantic response and request models for the dashboard API.

Mirrors the dataclasses in execution, strategies, risk, and monitoring
modules, providing JSON-serializable schemas for FastAPI endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator
from src.config.agent_universe import (
    DEFAULT_AGENT_CRYPTO_SYMBOLS,
    DEFAULT_AGENT_US_SYMBOLS,
    normalize_nse_agent_symbols,
    parse_symbol_values,
)
from src.config.constants import DEFAULT_AGENT_NSE_SYMBOLS


# =========================================================================
# Order / Trading Schemas
# =========================================================================


class OrderResponse(BaseModel):
    """Serialized representation of an Order."""

    symbol: str
    quantity: int
    side: str  # OrderSide.name
    order_type: str  # OrderType.name
    product_type: str  # ProductType.value
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    tag: str = ""
    order_id: Optional[str] = None
    status: str = "pending"  # OrderStatus.value
    fill_price: Optional[float] = None
    fill_quantity: int = 0
    placed_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    is_buy: bool = False
    is_complete: bool = False
    value: float = 0.0


class PlaceOrderRequest(BaseModel):
    """Request payload for creating an order."""

    symbol: str
    quantity: int = Field(..., ge=1)
    side: str = Field(..., description="BUY or SELL")
    order_type: str = Field(default="MARKET", description="MARKET, LIMIT, STOP, STOP_LIMIT")
    product_type: str = Field(default="INTRADAY", description="INTRADAY, CNC, MARGIN")
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    market_price_hint: Optional[float] = Field(
        default=None,
        description="Price hint for market orders in paper mode.",
    )
    tag: str = ""
    stop_loss: Optional[float] = Field(
        default=None,
        description="Optional stop-loss used for pre-trade risk validation.",
    )
    validate_risk: bool = True


class ModifyOrderRequest(BaseModel):
    """Request payload for modifying an existing order."""

    quantity: Optional[int] = Field(default=None, ge=1)
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None


class PositionResponse(BaseModel):
    """Serialized representation of a Position."""

    symbol: str
    market: str = "NSE"
    market_open: bool = False
    quantity: int
    side: str  # PositionSide.value
    avg_price: float
    current_price: float = 0.0
    entry_time: Optional[datetime] = None
    strategy_tag: str = ""
    order_ids: List[str] = Field(default_factory=list)
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    market_value: float = 0.0
    is_profitable: bool = False
    currency: str = "INR"
    currency_symbol: str = "₹"
    fx_to_inr: float = 1.0
    unrealized_pnl_inr: float = 0.0
    market_value_inr: float = 0.0
    stop_loss: Optional[float] = None
    target: Optional[float] = None
    time_exit_at: Optional[datetime] = None
    time_left_seconds: Optional[int] = None
    distance_to_stop_pct: Optional[float] = None
    distance_to_target_pct: Optional[float] = None
    progress_to_target_pct: Optional[float] = None


class PortfolioSummaryResponse(BaseModel):
    """Portfolio-level summary from PositionManager.get_portfolio_summary()."""

    position_count: int = 0
    total_market_value: float = 0.0
    total_unrealized_pnl: float = 0.0
    total_realized_pnl: float = 0.0
    total_pnl: float = 0.0
    total_market_value_inr: float = 0.0
    total_unrealized_pnl_inr: float = 0.0
    total_realized_pnl_inr: float = 0.0
    total_pnl_inr: float = 0.0
    total_allocated_capital_inr: float = 0.0
    total_pnl_pct_on_allocated: float = 0.0
    base_currency: str = "INR"
    usd_inr_rate: float = 83.0
    currency_breakdown: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    market_breakdown: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    positions: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class ClosedTradeResponse(BaseModel):
    """A single closed trade from PositionManager._closed_positions."""

    symbol: str
    side: str
    quantity: int
    entry_price: float
    exit_price: float
    pnl: float
    closed_at: Optional[datetime] = None
    strategy_tag: str = ""


class TradePairResponse(BaseModel):
    """A matched trade pair (entry + exit) built from fill history."""

    pair_id: str
    symbol: str
    side: str
    quantity: int
    entry_price: float
    exit_price: Optional[float] = None
    pnl: float
    pnl_pct: float = 0.0
    currency: str = "INR"
    currency_symbol: str = "₹"
    fx_to_inr: float = 1.0
    pnl_inr: float = 0.0
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    entry_order_id: Optional[str] = None
    exit_order_id: Optional[str] = None
    strategy_tag: str = ""


class InstrumentPerformanceRowResponse(BaseModel):
    """Performance summary for one instrument over a selected period."""

    symbol: str
    market: str = "NSE"
    currency: str = "INR"
    currency_symbol: str = "₹"
    fx_to_inr: float = 1.0
    trades: int = 0
    wins: int = 0
    losses: int = 0
    buy_notional: float = 0.0
    sell_notional: float = 0.0
    realized_pnl: float = 0.0
    realized_pnl_inr: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_inr: float = 0.0
    net_pnl: float = 0.0
    net_pnl_inr: float = 0.0
    avg_hold_minutes: float = 0.0
    last_trade_time: Optional[datetime] = None
    open_quantity: int = 0
    open_market_value: float = 0.0
    open_market_value_inr: float = 0.0


class PortfolioInstrumentSummaryResponse(BaseModel):
    """Portfolio summary grouped by instrument for a selected period."""

    period: str
    from_time: datetime
    to_time: datetime
    total_instruments: int = 0
    total_trades: int = 0
    total_realized_pnl_inr: float = 0.0
    total_unrealized_pnl_inr: float = 0.0
    total_net_pnl_inr: float = 0.0
    rows: List[InstrumentPerformanceRowResponse] = Field(default_factory=list)


# =========================================================================
# Strategy / Executor Schemas
# =========================================================================


class StrategyStateResponse(BaseModel):
    """Runtime state of a single registered strategy."""

    name: str
    enabled: bool = True
    signals_generated: int = 0
    trades_executed: int = 0
    total_pnl: float = 0.0
    last_signal_time: Optional[datetime] = None
    last_error: Optional[str] = None


class ExecutorSummaryResponse(BaseModel):
    """Overall executor summary from StrategyExecutor.get_summary()."""

    state: str  # ExecutorState.value
    paper_mode: bool = True
    strategies_count: int = 0
    enabled_count: int = 0
    total_signals: int = 0
    total_trades: int = 0
    strategies: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


# =========================================================================
# Signal Schema
# =========================================================================


class SignalResponse(BaseModel):
    """Serialized representation of a trading Signal."""

    timestamp: datetime
    symbol: str
    signal_type: str  # SignalType.value
    strength: str  # SignalStrength.value
    price: Optional[float] = None
    stop_loss: Optional[float] = None
    target: Optional[float] = None
    strategy_name: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


# =========================================================================
# Risk Schemas
# =========================================================================


class RiskSummaryResponse(BaseModel):
    """Risk state summary from RiskManager.get_risk_summary()."""

    date: str
    capital: float = 0.0
    total_allocated_capital_inr: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_pnl: float = 0.0
    total_pnl_pct_on_allocated: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    open_positions: int = 0
    max_open_positions: int = 0
    daily_loss_limit: float = 0.0
    available_risk: float = 0.0
    circuit_breaker_enabled: bool = True
    circuit_breaker_triggered: bool = False
    emergency_stop: bool = False
    position_values: Dict[str, float] = Field(default_factory=dict)
    market_allocations: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class RiskMetricsResponse(BaseModel):
    """Comprehensive risk and performance metrics from RiskCalculator."""

    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_duration: int = 0
    var_95: float = 0.0
    var_99: float = 0.0
    cvar_95: float = 0.0
    volatility: float = 0.0
    downside_volatility: float = 0.0
    profit_factor: float = 0.0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    expectancy: float = 0.0
    total_return: float = 0.0
    annualized_return: float = 0.0


# =========================================================================
# Alert / Monitoring Schemas
# =========================================================================


class AlertResponse(BaseModel):
    """Serialized representation of an Alert."""

    alert_id: str = ""
    level: str  # AlertLevel.value
    title: str
    message: str
    source: str = ""
    timestamp: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    acknowledged: bool = False


class AlertCountsResponse(BaseModel):
    """Alert counts grouped by level."""

    info: int = 0
    warning: int = 0
    critical: int = 0
    emergency: int = 0


class ComponentHealthResponse(BaseModel):
    """Health status of a single system component."""

    name: str
    status: str  # HealthStatus.value
    last_check: Optional[datetime] = None
    message: str = ""
    latency_ms: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SystemHealthResponse(BaseModel):
    """Aggregate system health from HealthMonitor."""

    overall_status: str  # HealthStatus.value
    checked_at: Optional[datetime] = None
    components: Dict[str, ComponentHealthResponse] = Field(default_factory=dict)


# =========================================================================
# Backtest Schemas
# =========================================================================


class BacktestTradeResponse(BaseModel):
    """A single trade from a backtest run."""

    entry_time: datetime
    exit_time: Optional[datetime] = None
    symbol: str = ""
    side: str = ""
    entry_price: float = 0.0
    exit_price: Optional[float] = None
    quantity: int = 1
    pnl: float = 0.0
    pnl_pct: float = 0.0
    stop_loss: Optional[float] = None
    target: Optional[float] = None
    exit_reason: str = ""


class BacktestResultResponse(BaseModel):
    """Aggregated results from a strategy backtest."""

    id: int = 0
    strategy_name: str
    symbol: str
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_capital: float
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    total_return_pct: float = 0.0
    max_drawdown: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    data_source: str = "database"
    trades: List[BacktestTradeResponse] = Field(default_factory=list)


class BacktestRunRequest(BaseModel):
    """POST body for /backtest/run."""

    strategy: str = Field(..., description="Strategy name (e.g. 'ema_crossover')")
    symbol: str = Field(
        default="NSE:NIFTY50-INDEX", description="Symbol to backtest"
    )
    timeframe: str = Field(
        default="15", description="Candle timeframe (1, 3, 5, 15, 30, 60, D, W, M)"
    )
    start_date: Optional[datetime] = Field(
        default=None, description="Backtest start date (ISO 8601)"
    )
    end_date: Optional[datetime] = Field(
        default=None, description="Backtest end date (ISO 8601)"
    )
    initial_capital: float = Field(default=100000.0, description="Starting capital")
    quantity: int = Field(default=1, description="Trade quantity per signal")
    commission: float = Field(default=0.0, description="Per-trade commission")
    slippage_pct: float = Field(default=0.0, description="Slippage as % of price")


# =========================================================================
# Auth Schemas
# =========================================================================


class AuthStatusResponse(BaseModel):
    """Fyers authentication status."""

    authenticated: bool = False
    profile: Optional[Dict[str, Any]] = None
    app_configured: bool = False


class AuthLoginUrlResponse(BaseModel):
    """OAuth authorization URL response."""

    url: str


class FyersCredentialsRequest(BaseModel):
    """Request model for saving Fyers API credentials."""

    app_id: str = Field(..., min_length=1, description="Fyers App ID")
    secret_key: str = Field(..., min_length=1, description="Fyers Secret Key")
    redirect_uri: str = Field(
        default="https://trade.fyers.in/api-login/redirect-uri/index.html",
        description="OAuth redirect URI",
    )


class FyersCredentialsResponse(BaseModel):
    """Response model for Fyers credentials (without secret)."""

    app_id: str
    redirect_uri: str
    configured: bool = True
    secret_configured: bool = False
    credentials_path: Optional[str] = None


class MarketDataProvidersRequest(BaseModel):
    """Request model for market-data provider API keys."""

    finnhub_api_key: str = ""
    alphavantage_api_key: str = ""


class MarketDataProvidersResponse(BaseModel):
    """Response model exposing provider-key availability state."""

    finnhub_configured: bool = False
    alphavantage_configured: bool = False
    finnhub_key_preview: Optional[str] = None
    alphavantage_key_preview: Optional[str] = None
    credentials_path: Optional[str] = None


class TelegramConfigRequest(BaseModel):
    """Request model for Telegram integration credentials."""

    enabled: Optional[bool] = None
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None
    status_interval_minutes: Optional[int] = Field(default=None, ge=0, le=1440)


class TelegramConfigResponse(BaseModel):
    """Response model for Telegram integration status."""

    configured: bool = False
    enabled: bool = True
    bot_configured: bool = False
    chat_configured: bool = False
    active: bool = False
    status_interval_minutes: int = 30
    last_error: Optional[str] = None


class ValidateCredentialsResponse(BaseModel):
    """Response model for credential validation."""

    valid: bool
    message: str
    login_url: Optional[str] = None


class ManualAuthCodeRequest(BaseModel):
    """Request model for manual authorization code entry."""

    auth_code: str = Field(..., min_length=1, description="Authorization code from Fyers")


class ManualAuthResponse(BaseModel):
    """Response model for manual auth code submission."""

    success: bool
    message: str
    authenticated: bool


class TokenRefreshRequest(BaseModel):
    """Request model for token refresh with PIN."""

    pin: str = Field(..., min_length=4, max_length=6, description="FYERS PIN")


class TokenRefreshResponse(BaseModel):
    """Response model for token refresh."""

    success: bool
    message: str
    access_token_expires_at: Optional[str] = None
    refresh_token_expires_in_days: Optional[float] = None
    needs_full_reauth: bool = False


class SavePinRequest(BaseModel):
    """Request model for saving encrypted PIN."""

    pin: str = Field(..., min_length=4, max_length=6, description="FYERS PIN")
    save_pin: bool = Field(default=True, description="Whether to save PIN for auto-refresh")


class SavePinResponse(BaseModel):
    """Response model for PIN save operation."""

    success: bool
    message: str
    pin_saved: bool = False


class TokenStatusResponse(BaseModel):
    """Detailed token status information."""

    access_token_valid: bool
    access_token_expires_in_hours: Optional[float] = None
    refresh_token_valid: bool
    refresh_token_expires_in_days: Optional[float] = None
    needs_full_reauth: bool
    has_saved_pin: bool = False
    has_access_token: bool = False
    has_refresh_token: bool = False
    status_message: Optional[str] = None


# =========================================================================
# Watchlist / Data Collection Schemas
# =========================================================================


class DataSummaryItem(BaseModel):
    """Data availability for one symbol-timeframe pair."""

    timeframe: str
    count: int = 0
    latest_timestamp: Optional[str] = None


class WatchlistSymbolResponse(BaseModel):
    """Symbol with data collection summary."""

    symbol: str
    display_name: str
    data_summary: List[DataSummaryItem] = Field(default_factory=list)
    latest_price: Optional[float] = None
    price_change_pct: Optional[float] = None


class CollectionRequest(BaseModel):
    """POST body for triggering data collection."""

    symbol: str = Field(..., description="Symbol to collect data for")
    timeframe: str = Field(default="D", description="Timeframe to collect")
    days_back: int = Field(default=90, ge=1, le=730, description="Days of history to collect")


class CollectionStatusResponse(BaseModel):
    """Status of a data collection job."""

    symbol: str
    timeframe: str
    status: str = "idle"  # idle, collecting, completed, failed
    progress: float = 0.0
    candles_collected: int = 0
    error: Optional[str] = None


# =========================================================================
# AI Agent Schemas
# =========================================================================


class AgentConfigRequest(BaseModel):
    """POST body for /agent/start — configures the trading agent."""

    symbols: List[str] = Field(
        default=list(DEFAULT_AGENT_NSE_SYMBOLS),
        description="Primary NSE symbols to trade",
    )
    us_symbols: List[str] = Field(
        default=list(DEFAULT_AGENT_US_SYMBOLS),
        description="US symbols activated during US session",
    )
    crypto_symbols: List[str] = Field(
        default=list(DEFAULT_AGENT_CRYPTO_SYMBOLS),
        description="Crypto pairs for 24x7 execution",
    )
    trade_nse_when_open: bool = Field(
        default=True,
        description="Enable NSE universe during NSE market hours",
    )
    trade_us_when_open: bool = Field(
        default=True,
        description="Enable US universe during US market hours",
    )
    trade_us_options: bool = Field(
        default=True,
        description="Route US directional signals to US option contracts (ATM) in paper/live simulation",
    )
    trade_crypto_24x7: bool = Field(
        default=True,
        description="Enable crypto universe continuously (24x7)",
    )
    strategies: List[str] = Field(
        default=[
            "EMA_Crossover",
            "RSI_Reversal",
            "Supertrend_Breakout",
            "MP_OrderFlow_Breakout",
            "Fractal_Profile_Breakout",
        ],
        description="Strategy names to activate",
    )
    scan_interval_seconds: int = Field(default=30, ge=10, le=300)
    paper_mode: bool = Field(default=True, description="Paper or live trading")
    capital: Optional[float] = Field(
        default=None,
        ge=10000,
        description="Deprecated overall capital field; total capital is derived from market allocations.",
    )
    india_capital: float = Field(default=250000.0, ge=10000, description="Allocated India/NSE capital in INR")
    us_capital: float = Field(default=250000.0, ge=1000, description="Allocated US capital in USD")
    crypto_capital: float = Field(default=250000.0, ge=1000, description="Allocated crypto capital in USD")
    india_max_instrument_pct: float = Field(default=25.0, ge=1.0, le=100.0)
    us_max_instrument_pct: float = Field(default=20.0, ge=1.0, le=100.0)
    crypto_max_instrument_pct: float = Field(default=20.0, ge=1.0, le=100.0)
    max_daily_loss_pct: float = Field(default=2.0, ge=0.1, le=10.0)
    timeframe: str = Field(default="15", description="Candle timeframe in minutes")
    execution_timeframes: List[str] = Field(
        default=["3", "5", "15"],
        description="Primary execution timeframes used for signal generation",
    )
    reference_timeframes: List[str] = Field(
        default=["60", "D"],
        description="Higher timeframes used for spot trend confirmation",
    )
    event_driven_enabled: bool = Field(
        default=False,
        description="Enable tick-triggered symbol scans between periodic full scans",
    )
    event_driven_markets: List[str] = Field(default=["NSE"])
    event_driven_debounce_ms: int = Field(default=1000, ge=100, le=5000)
    event_driven_batch_size: int = Field(default=8, ge=1, le=50)
    liberal_bootstrap_enabled: bool = Field(
        default=True,
        description="Temporarily loosen risk constraints for aggressive early learning",
    )
    bootstrap_cycles: int = Field(
        default=300,
        ge=1,
        le=5000,
        description="Number of initial scan cycles to run in liberal mode",
    )
    bootstrap_size_multiplier: float = Field(default=2.0, ge=1.0, le=5.0)
    bootstrap_max_concentration_pct: float = Field(default=100.0, ge=30.0, le=100.0)
    bootstrap_max_open_positions: int = Field(default=20, ge=1, le=100)
    bootstrap_risk_per_trade_pct: float = Field(default=2.0, ge=0.1, le=10.0)
    option_time_exit_minutes: int = Field(
        default=30,
        ge=1,
        le=480,
        description="Force-exit option positions after this holding time",
    )
    option_default_stop_loss_pct: float = Field(default=10.0, ge=1.0, le=90.0)
    option_default_target_pct: float = Field(default=18.0, ge=1.0, le=400.0)
    reinforcement_enabled: bool = Field(default=True)
    reinforcement_alpha: float = Field(default=0.2, ge=0.01, le=1.0)
    reinforcement_size_boost_pct: float = Field(default=60.0, ge=0.0, le=300.0)
    strategy_capital_bucket_enabled: bool = Field(default=False)
    strategy_max_concurrent_positions: int = Field(default=4, ge=1, le=20)
    telegram_status_interval_minutes: int = Field(
        default=30,
        ge=0,
        le=1440,
        description="Periodic Telegram status update interval (0 disables periodic updates)",
    )

    @model_validator(mode="after")
    def _normalize_symbol_universe(self) -> "AgentConfigRequest":
        self.symbols = normalize_nse_agent_symbols(self.symbols)
        self.us_symbols = parse_symbol_values(self.us_symbols)
        self.crypto_symbols = parse_symbol_values(self.crypto_symbols)
        return self


class AgentStatusResponse(BaseModel):
    """Agent runtime status and metrics."""

    state: str
    paper_mode: bool = True
    uptime_seconds: float = 0.0
    current_cycle: int = 0
    symbols: List[str] = Field(default_factory=list)
    us_symbols: List[str] = Field(default_factory=list)
    crypto_symbols: List[str] = Field(default_factory=list)
    trade_nse_when_open: bool = True
    trade_us_when_open: bool = True
    trade_crypto_24x7: bool = True
    trade_us_options: bool = True
    active_strategies: List[str] = Field(default_factory=list)
    active_symbols: List[str] = Field(default_factory=list)
    active_sessions: List[str] = Field(default_factory=list)
    market_readiness: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    execution_timeframes: List[str] = Field(default_factory=list)
    reference_timeframes: List[str] = Field(default_factory=list)
    event_driven_enabled: bool = False
    event_driven_markets: List[str] = Field(default_factory=list)
    event_driven_debounce_ms: int = 1000
    event_driven_batch_size: int = 8
    pending_live_entries: int = 0
    pending_live_exits: int = 0
    execution_backend: str = "python"
    execution_signal_lane: Dict[str, Any] = Field(default_factory=dict)
    execution_core_status: Dict[str, Any] = Field(default_factory=dict)
    execution_transport: str = "inmemory"
    streaming_backends: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    analytics_backends: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    execution_latency: Dict[str, Any] = Field(default_factory=dict)
    telegram_status_interval_minutes: int = 30
    strategy_capital_bucket_enabled: bool = False
    strategy_max_concurrent_positions: int = 4
    capital_allocations: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    total_allocated_capital_inr: float = 0.0
    positions_count: int = 0
    daily_pnl: float = 0.0
    total_signals: int = 0
    total_trades: int = 0
    market_stats: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    market_pnl_inr: Dict[str, float] = Field(default_factory=dict)
    strategy_stats: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    strategy_market_stats: Dict[str, Dict[str, Dict[str, Any]]] = Field(default_factory=dict)
    strategy_instrument_stats: Dict[str, Dict[str, Dict[str, Any]]] = Field(default_factory=dict)
    strategy_controls: List[Dict[str, Any]] = Field(default_factory=list)
    last_scan_time: Optional[str] = None
    bootstrap_mode_active: bool = False
    emergency_stop: bool = False
    online_learning_active: bool = False
    online_learning_stats: Dict[str, Any] = Field(default_factory=dict)
    strategy_reward_ema: Dict[str, float] = Field(default_factory=dict)
    strategy_reward_ema_by_market: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    error: Optional[str] = None


class AgentEventResponse(BaseModel):
    """A single agent event."""

    event_id: str
    event_type: str
    timestamp: str
    title: str
    message: str
    severity: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
