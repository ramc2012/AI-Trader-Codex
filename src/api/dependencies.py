"""FastAPI dependency injection for database sessions and manager singletons."""

from __future__ import annotations

from typing import AsyncGenerator, Optional
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.events import AgentEventBus
from src.agent.telegram_notifier import TelegramNotifier
from src.agent.trading_agent import AgentConfig, TradingAgent
from src.database.connection import get_session_factory
from src.data.live.tick_aggregator import RealTimeAggregator
from src.data.ohlc_cache import OHLCCache, get_ohlc_cache as _get_cache
from src.data.runtime_manager import RuntimeManager
from src.execution.order_manager import OrderManager
from src.execution.position_manager import PositionManager
from src.execution.strategy_executor import StrategyExecutor
from src.integrations.fyers_client import FyersClient
from src.monitoring.alerts import AlertManager
from src.monitoring.health import ComponentHealth, HealthMonitor, HealthStatus
from src.risk.risk_calculator import RiskCalculator
from src.risk.risk_manager import RiskConfig, RiskManager
from src.config.settings import get_settings
from src.watchlist.instrument_registry_service import InstrumentRegistryService


# =========================================================================
# Database Dependency
# =========================================================================


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session for a single request."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


# =========================================================================
# Manager Singletons (lazy-init)
# =========================================================================

_order_manager: Optional[OrderManager] = None
_position_manager: Optional[PositionManager] = None
_strategy_executor: Optional[StrategyExecutor] = None
_risk_manager: Optional[RiskManager] = None
_risk_calculator: Optional[RiskCalculator] = None
_health_monitor: Optional[HealthMonitor] = None
_alert_manager: Optional[AlertManager] = None
_fyers_client: Optional[FyersClient] = None
_instrument_registry: Optional[InstrumentRegistryService] = None
_runtime_manager: Optional[RuntimeManager] = None
_agent_event_bus: Optional[AgentEventBus] = None
_trading_agent: Optional[TradingAgent] = None
_telegram_notifier: Optional[TelegramNotifier] = None
_tick_aggregator: Optional[RealTimeAggregator] = None
_fractal_scan_notifier: Optional[FractalScanNotifier] = None


def get_order_manager() -> OrderManager:
    """Get or create the singleton OrderManager (paper mode)."""
    global _order_manager
    if _order_manager is None:
        _order_manager = OrderManager(paper_mode=True)
    return _order_manager


def get_position_manager() -> PositionManager:
    """Get or create the singleton PositionManager."""
    global _position_manager
    if _position_manager is None:
        _position_manager = PositionManager()
    return _position_manager


def get_strategy_executor() -> StrategyExecutor:
    """Get or create the singleton StrategyExecutor.

    Wires up the order manager and position manager automatically.
    """
    global _strategy_executor
    if _strategy_executor is None:
        _strategy_executor = StrategyExecutor(paper_mode=True)
        _strategy_executor.set_order_manager(get_order_manager())
    return _strategy_executor


def get_risk_manager() -> RiskManager:
    """Get or create the singleton RiskManager with default config."""
    global _risk_manager
    if _risk_manager is None:
        settings = get_settings()
        base_config = RiskConfig()
        max_daily_loss_pct = max(float(settings.max_daily_loss_pct), 0.0) / 100.0
        max_trade_risk_pct = max(float(settings.max_trade_risk_pct), 0.0) / 100.0
        max_position_size_pct = max(float(settings.max_position_size_pct), 0.0) / 100.0
        max_concentration_pct = max(float(settings.max_concentration_pct), 0.0) / 100.0

        _risk_manager = RiskManager(
            config=RiskConfig(
                max_daily_loss_pct=max_daily_loss_pct,
                max_risk_per_trade_pct=max_trade_risk_pct,
                max_open_positions=int(settings.max_open_positions),
                max_position_size=base_config.capital * max_position_size_pct,
                max_daily_loss=base_config.capital * max_daily_loss_pct,
                capital=base_config.capital,
                max_concentration_pct=max_concentration_pct or base_config.max_concentration_pct,
                circuit_breaker_enabled=bool(settings.risk_circuit_breaker_enabled),
                time_based_exit_minutes=base_config.time_based_exit_minutes,
            )
        )
    return _risk_manager


def get_risk_calculator() -> RiskCalculator:
    """Get or create the singleton RiskCalculator."""
    global _risk_calculator
    if _risk_calculator is None:
        _risk_calculator = RiskCalculator()
    return _risk_calculator


def get_health_monitor() -> HealthMonitor:
    """Get or create the singleton HealthMonitor."""
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = HealthMonitor()
        _health_monitor.register_check(
            "fyers_api",
            lambda: ComponentHealth(
                name="fyers_api",
                status=(
                    HealthStatus.HEALTHY
                    if get_fyers_client().is_authenticated
                    else HealthStatus.DEGRADED
                ),
                last_check=datetime.now(),
                message=(
                    "Authenticated"
                    if get_fyers_client().is_authenticated
                    else "Not authenticated"
                ),
            ),
        )
        _health_monitor.register_check(
            "runtime_manager",
            lambda: ComponentHealth(
                name="runtime_manager",
                status=(
                    HealthStatus.HEALTHY
                    if get_runtime_manager().is_running
                    else HealthStatus.DEGRADED
                ),
                last_check=datetime.now(),
                message=(
                    "Runtime manager running"
                    if get_runtime_manager().is_running
                    else "Runtime manager stopped"
                ),
            ),
        )
        _health_monitor.register_check(
            "ohlc_cache",
            lambda: ComponentHealth(
                name="ohlc_cache",
                status=HealthStatus.HEALTHY if get_ohlc_cache().is_ready else HealthStatus.DEGRADED,
                last_check=datetime.now(),
                message="Cache warmed" if get_ohlc_cache().is_ready else "Cache warming/pending",
            ),
        )
    return _health_monitor


def get_alert_manager() -> AlertManager:
    """Get or create the singleton AlertManager."""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager()
    return _alert_manager


def get_fyers_client() -> FyersClient:
    """Get or create the singleton FyersClient."""
    global _fyers_client
    if _fyers_client is None:
        _fyers_client = FyersClient()
    return _fyers_client


def get_instrument_registry() -> InstrumentRegistryService:
    """Get or create the singleton instrument registry service."""
    global _instrument_registry
    if _instrument_registry is None:
        _instrument_registry = InstrumentRegistryService()
    return _instrument_registry


def get_runtime_manager() -> RuntimeManager:
    """Get or create the singleton runtime manager."""
    global _runtime_manager
    if _runtime_manager is None:
        _runtime_manager = RuntimeManager(
            client=get_fyers_client(),
            registry=get_instrument_registry(),
        )
    return _runtime_manager


# =========================================================================
# AI Agent Singletons
# =========================================================================


def get_agent_event_bus() -> AgentEventBus:
    """Get or create the singleton AgentEventBus."""
    global _agent_event_bus
    if _agent_event_bus is None:
        _agent_event_bus = AgentEventBus()
    return _agent_event_bus


def get_trading_agent(config: Optional[AgentConfig] = None) -> TradingAgent:
    """Get or create the singleton TradingAgent.

    On first call, the agent is created with the provided (or default) config.
    Subsequent calls return the existing instance. To replace the agent, call
    reset_trading_agent() first.
    """
    global _trading_agent
    if _trading_agent is None:
        if config is None:
            settings = get_settings()
            config = AgentConfig(
                symbols=[symbol.strip() for symbol in settings.agent_default_symbols.split(",") if symbol.strip()],
                us_symbols=[symbol.strip() for symbol in settings.agent_us_symbols.split(",") if symbol.strip()],
                crypto_symbols=[
                    symbol.strip() for symbol in settings.agent_crypto_symbols.split(",") if symbol.strip()
                ],
                trade_nse_when_open=settings.agent_trade_nse_when_open,
                trade_us_when_open=settings.agent_trade_us_when_open,
                trade_us_options=settings.agent_trade_us_options,
                trade_crypto_24x7=settings.agent_trade_crypto_24x7,
                scan_interval_seconds=settings.agent_scan_interval,
                timeframe=settings.agent_default_timeframe,
                execution_timeframes=[
                    tf.strip() for tf in settings.agent_execution_timeframes.split(",") if tf.strip()
                ],
                reference_timeframes=[
                    tf.strip() for tf in settings.agent_reference_timeframes.split(",") if tf.strip()
                ],
                event_driven_execution_enabled=settings.agent_event_driven_enabled,
                event_driven_markets=[
                    market.strip().upper()
                    for market in settings.agent_event_driven_markets.split(",")
                    if market.strip()
                ],
                event_driven_debounce_ms=settings.agent_event_driven_debounce_ms,
                event_driven_batch_size=settings.agent_event_driven_batch_size,
                liberal_bootstrap_enabled=settings.agent_liberal_bootstrap_enabled,
                bootstrap_cycles=settings.agent_bootstrap_cycles,
                bootstrap_size_multiplier=settings.agent_bootstrap_size_multiplier,
                bootstrap_max_concentration_pct=settings.agent_bootstrap_max_concentration_pct,
                bootstrap_max_open_positions=settings.agent_bootstrap_max_open_positions,
                bootstrap_risk_per_trade_pct=settings.agent_bootstrap_risk_per_trade_pct,
                option_time_exit_minutes=settings.agent_option_time_exit_minutes,
                option_default_stop_loss_pct=settings.agent_option_default_stop_loss_pct,
                option_default_target_pct=settings.agent_option_default_target_pct,
                reinforcement_enabled=settings.agent_reinforcement_enabled,
                reinforcement_alpha=settings.agent_reinforcement_alpha,
                reinforcement_size_boost_pct=settings.agent_reinforcement_size_boost_pct,
                telegram_status_interval_minutes=settings.telegram_status_interval_minutes,
            )
        _trading_agent = TradingAgent(
            config=config,
            strategy_executor=get_strategy_executor(),
            order_manager=get_order_manager(),
            position_manager=get_position_manager(),
            risk_manager=get_risk_manager(),
            event_bus=get_agent_event_bus(),
            fyers_client=get_fyers_client(),
            candle_broker=get_runtime_manager().candle_broker,
        )
    return _trading_agent


def reset_trading_agent() -> None:
    """Reset the TradingAgent singleton (for reconfiguration)."""
    global _trading_agent
    _trading_agent = None


def get_ohlc_cache() -> OHLCCache:
    """Return the global in-memory OHLC cache."""
    return _get_cache()


def get_tick_aggregator() -> RealTimeAggregator:
    """Get or create the singleton RealTimeAggregator.

    The aggregator subscribes to the tick broker and fans out footprint
    bar updates to WebSocket clients in real time.
    """
    global _tick_aggregator
    if _tick_aggregator is None:
        runtime = get_runtime_manager()
        _tick_aggregator = RealTimeAggregator(broker=runtime.broker)
    return _tick_aggregator


def get_telegram_notifier() -> TelegramNotifier:
    """Get or create the singleton TelegramNotifier."""
    global _telegram_notifier
    if _telegram_notifier is None:
        settings = get_settings()
        _telegram_notifier = TelegramNotifier(
            bot_token=settings.telegram_bot_token,
            chat_id=settings.telegram_chat_id,
            event_bus=get_agent_event_bus(),
            enabled=settings.telegram_enabled,
        )
    return _telegram_notifier


def get_fractal_scan_notifier() -> FractalScanNotifier:
    """Get or create the singleton fractal scan notifier."""
    global _fractal_scan_notifier
    if _fractal_scan_notifier is None:
        from src.agent.fractal_scan_notifier import FractalScanNotifier

        _fractal_scan_notifier = FractalScanNotifier(event_bus=get_agent_event_bus())
    return _fractal_scan_notifier


def reset_telegram_notifier() -> None:
    """Reset TelegramNotifier singleton so new credentials are picked up."""
    global _telegram_notifier
    _telegram_notifier = None


def reset_fyers_client() -> None:
    """Reset the FyersClient singleton so it picks up new credentials."""
    global _fyers_client
    global _instrument_registry
    global _runtime_manager
    _fyers_client = None
    _instrument_registry = None
    _runtime_manager = None


def reset_managers() -> None:
    """Reset all manager singletons to None (for testing)."""
    global _order_manager, _position_manager, _strategy_executor
    global _risk_manager, _risk_calculator, _health_monitor, _alert_manager
    global _fyers_client, _agent_event_bus, _trading_agent, _telegram_notifier, _fractal_scan_notifier

    _order_manager = None
    _position_manager = None
    _strategy_executor = None
    _risk_manager = None
    _risk_calculator = None
    _health_monitor = None
    _alert_manager = None
    _fyers_client = None
    _instrument_registry = None
    _runtime_manager = None
    _agent_event_bus = None
    _trading_agent = None
    _telegram_notifier = None
    _fractal_scan_notifier = None
