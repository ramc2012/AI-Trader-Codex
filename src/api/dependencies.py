"""FastAPI dependency injection for database sessions and manager singletons."""

from __future__ import annotations

from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.connection import get_session_factory
from src.execution.order_manager import OrderManager
from src.execution.position_manager import PositionManager
from src.execution.strategy_executor import StrategyExecutor
from src.integrations.fyers_client import FyersClient
from src.monitoring.alerts import AlertManager
from src.monitoring.health import HealthMonitor
from src.risk.risk_calculator import RiskCalculator
from src.risk.risk_manager import RiskConfig, RiskManager


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
        _risk_manager = RiskManager(config=RiskConfig())
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


def reset_managers() -> None:
    """Reset all manager singletons to None (for testing)."""
    global _order_manager, _position_manager, _strategy_executor
    global _risk_manager, _risk_calculator, _health_monitor, _alert_manager
    global _fyers_client

    _order_manager = None
    _position_manager = None
    _strategy_executor = None
    _risk_manager = None
    _risk_calculator = None
    _health_monitor = None
    _alert_manager = None
    _fyers_client = None
