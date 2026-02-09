"""Strategy execution framework - orchestrates strategies to order execution.

Manages multiple trading strategies, routing their signals through
risk checks and into the order management pipeline. Supports
start/stop/pause lifecycle and per-strategy tracking.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


class ExecutorState(Enum):
    """Lifecycle state of the strategy executor."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"


@dataclass
class StrategyState:
    """Runtime state tracked per registered strategy.

    Attributes:
        name: Strategy name.
        enabled: Whether the strategy is active.
        signals_generated: Total signals produced.
        trades_executed: Total trades executed from signals.
        total_pnl: Accumulated P&L from this strategy.
        last_signal_time: Timestamp of the most recent signal.
        last_error: Most recent error message, if any.
    """

    name: str
    enabled: bool = True
    signals_generated: int = 0
    trades_executed: int = 0
    total_pnl: float = 0.0
    last_signal_time: Optional[datetime] = None
    last_error: Optional[str] = None


class StrategyExecutor:
    """Orchestrate multiple strategies.

    Registers strategies, feeds them market data, collects signals,
    and manages the executor lifecycle (start/pause/resume/stop).

    Args:
        paper_mode: If True, operate in paper trading mode.
    """

    def __init__(self, paper_mode: bool = True) -> None:
        self.paper_mode = paper_mode
        self.state = ExecutorState.IDLE
        self._strategies: Dict[str, Any] = {}
        self._strategy_states: Dict[str, StrategyState] = {}
        self._order_manager: Optional[Any] = None
        self._risk_manager: Optional[Any] = None
        self._alert_manager: Optional[Any] = None
        logger.info(
            "strategy_executor_initialized",
            paper_mode=paper_mode,
        )

    def register_strategy(
        self, name: str, strategy: Any, enabled: bool = True
    ) -> None:
        """Register a strategy for execution.

        Args:
            name: Unique name for the strategy.
            strategy: Strategy object with a generate_signals() method.
            enabled: Whether the strategy should be active immediately.
        """
        self._strategies[name] = strategy
        self._strategy_states[name] = StrategyState(name=name, enabled=enabled)
        logger.info(
            "strategy_registered",
            strategy=name,
            enabled=enabled,
        )

    def unregister_strategy(self, name: str) -> None:
        """Remove a strategy from the executor.

        Args:
            name: Name of the strategy to remove.
        """
        self._strategies.pop(name, None)
        self._strategy_states.pop(name, None)
        logger.info("strategy_unregistered", strategy=name)

    def enable_strategy(self, name: str) -> None:
        """Enable a registered strategy.

        Args:
            name: Name of the strategy to enable.
        """
        if name in self._strategy_states:
            self._strategy_states[name].enabled = True
            logger.info("strategy_enabled", strategy=name)

    def disable_strategy(self, name: str) -> None:
        """Disable a registered strategy (it remains registered).

        Args:
            name: Name of the strategy to disable.
        """
        if name in self._strategy_states:
            self._strategy_states[name].enabled = False
            logger.info("strategy_disabled", strategy=name)

    def set_order_manager(self, om: Any) -> None:
        """Set the order manager for live/paper order routing.

        Args:
            om: An OrderManager instance.
        """
        self._order_manager = om

    def set_risk_manager(self, rm: Any) -> None:
        """Set the risk manager for pre-trade risk checks.

        Args:
            rm: A RiskManager instance.
        """
        self._risk_manager = rm

    def set_alert_manager(self, am: Any) -> None:
        """Set the alert manager for notifications.

        Args:
            am: An AlertManager instance.
        """
        self._alert_manager = am

    def process_data(
        self, data: Any, symbol: str = ""
    ) -> List[Dict[str, Any]]:
        """Feed market data to all enabled strategies and collect signals.

        When the executor is paused, no strategies are processed and
        an empty list is returned.

        Args:
            data: Market data (typically a pandas DataFrame).
            symbol: Symbol the data belongs to.

        Returns:
            List of result dicts, each containing strategy name, signal,
            and action taken.
        """
        if self.state == ExecutorState.PAUSED:
            return []

        results: List[Dict[str, Any]] = []

        for name, strategy in self._strategies.items():
            state = self._strategy_states[name]
            if not state.enabled:
                continue

            try:
                signals = strategy.generate_signals(data)
                state.signals_generated += len(signals)

                if signals:
                    state.last_signal_time = datetime.now()

                for signal in signals:
                    result: Dict[str, Any] = {
                        "strategy": name,
                        "signal": signal,
                        "action": None,
                    }
                    results.append(result)

            except Exception as e:
                state.last_error = str(e)
                logger.error(
                    "strategy_error",
                    strategy=name,
                    error=str(e),
                )

        return results

    def start(self) -> None:
        """Start the executor (transition to RUNNING state)."""
        self.state = ExecutorState.RUNNING
        logger.info("executor_started")

    def pause(self) -> None:
        """Pause the executor (strategies will not be processed)."""
        self.state = ExecutorState.PAUSED
        logger.info("executor_paused")

    def resume(self) -> None:
        """Resume from paused state back to running."""
        if self.state == ExecutorState.PAUSED:
            self.state = ExecutorState.RUNNING
            logger.info("executor_resumed")

    def stop(self) -> None:
        """Stop the executor."""
        self.state = ExecutorState.STOPPED
        logger.info("executor_stopped")

    def get_strategy_states(self) -> Dict[str, StrategyState]:
        """Get the runtime state of all registered strategies.

        Returns:
            Dictionary mapping strategy name to its StrategyState.
        """
        return dict(self._strategy_states)

    def get_summary(self) -> Dict[str, Any]:
        """Get an overall executor summary.

        Returns:
            Dictionary with executor state, strategy counts, and
            per-strategy metrics.
        """
        return {
            "state": self.state.value,
            "paper_mode": self.paper_mode,
            "strategies_count": len(self._strategies),
            "enabled_count": sum(
                1 for s in self._strategy_states.values() if s.enabled
            ),
            "total_signals": sum(
                s.signals_generated for s in self._strategy_states.values()
            ),
            "total_trades": sum(
                s.trades_executed for s in self._strategy_states.values()
            ),
            "strategies": {
                name: {
                    "enabled": st.enabled,
                    "signals": st.signals_generated,
                    "trades": st.trades_executed,
                    "pnl": st.total_pnl,
                }
                for name, st in self._strategy_states.items()
            },
        }
