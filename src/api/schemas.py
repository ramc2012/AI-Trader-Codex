"""Pydantic response and request models for the dashboard API.

Mirrors the dataclasses in execution, strategies, risk, and monitoring
modules, providing JSON-serializable schemas for FastAPI endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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


class PositionResponse(BaseModel):
    """Serialized representation of a Position."""

    symbol: str
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


class PortfolioSummaryResponse(BaseModel):
    """Portfolio-level summary from PositionManager.get_portfolio_summary()."""

    position_count: int = 0
    total_market_value: float = 0.0
    total_unrealized_pnl: float = 0.0
    total_realized_pnl: float = 0.0
    total_pnl: float = 0.0
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
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_pnl: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    open_positions: int = 0
    max_open_positions: int = 0
    daily_loss_limit: float = 0.0
    available_risk: float = 0.0
    circuit_breaker_triggered: bool = False
    emergency_stop: bool = False
    position_values: Dict[str, float] = Field(default_factory=dict)


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
    trades: List[BacktestTradeResponse] = Field(default_factory=list)


class BacktestRunRequest(BaseModel):
    """POST body for /backtest/run."""

    strategy: str = Field(..., description="Strategy name (e.g. 'ema_crossover')")
    symbol: str = Field(
        default="NSE:NIFTY50-INDEX", description="Symbol to backtest"
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
