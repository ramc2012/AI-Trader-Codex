"""Tests for the StrategyExecutor class."""

from unittest.mock import MagicMock

import pytest

from src.execution.strategy_executor import (
    ExecutorState,
    StrategyExecutor,
    StrategyState,
)


class _MockStrategy:
    """A simple mock strategy that returns predefined signals."""

    def __init__(self, signals: list | None = None) -> None:
        self._signals = signals if signals is not None else []

    def generate_signals(self, data):  # noqa: ANN001, ANN201
        return list(self._signals)


class _ErrorStrategy:
    """A strategy that always raises an exception."""

    def generate_signals(self, data):  # noqa: ANN001, ANN201
        raise RuntimeError("strategy blew up")


# =============================================================================
# Registration tests
# =============================================================================


class TestStrategyRegistration:
    """Tests for registering and unregistering strategies."""

    def test_register_strategy(self) -> None:
        """Registering a strategy adds it to the executor."""
        executor = StrategyExecutor()
        strategy = _MockStrategy()
        executor.register_strategy("alpha", strategy)
        states = executor.get_strategy_states()
        assert "alpha" in states
        assert states["alpha"].enabled is True

    def test_register_strategy_disabled(self) -> None:
        """Registering with enabled=False creates a disabled strategy."""
        executor = StrategyExecutor()
        executor.register_strategy("alpha", _MockStrategy(), enabled=False)
        states = executor.get_strategy_states()
        assert states["alpha"].enabled is False

    def test_unregister_strategy(self) -> None:
        """Unregistering removes the strategy completely."""
        executor = StrategyExecutor()
        executor.register_strategy("alpha", _MockStrategy())
        executor.unregister_strategy("alpha")
        states = executor.get_strategy_states()
        assert "alpha" not in states

    def test_unregister_nonexistent_no_error(self) -> None:
        """Unregistering a non-existent strategy does not raise."""
        executor = StrategyExecutor()
        executor.unregister_strategy("nonexistent")  # should not raise


# =============================================================================
# Enable / disable tests
# =============================================================================


class TestStrategyEnableDisable:
    """Tests for enabling and disabling strategies."""

    def test_enable_strategy(self) -> None:
        """Enabling a disabled strategy sets enabled=True."""
        executor = StrategyExecutor()
        executor.register_strategy("alpha", _MockStrategy(), enabled=False)
        executor.enable_strategy("alpha")
        assert executor.get_strategy_states()["alpha"].enabled is True

    def test_disable_strategy(self) -> None:
        """Disabling an enabled strategy sets enabled=False."""
        executor = StrategyExecutor()
        executor.register_strategy("alpha", _MockStrategy(), enabled=True)
        executor.disable_strategy("alpha")
        assert executor.get_strategy_states()["alpha"].enabled is False

    def test_enable_nonexistent_no_error(self) -> None:
        """Enabling a non-existent strategy does not raise."""
        executor = StrategyExecutor()
        executor.enable_strategy("nonexistent")  # should not raise

    def test_disable_nonexistent_no_error(self) -> None:
        """Disabling a non-existent strategy does not raise."""
        executor = StrategyExecutor()
        executor.disable_strategy("nonexistent")  # should not raise


# =============================================================================
# State transition tests
# =============================================================================


class TestExecutorStateTransitions:
    """Tests for start/pause/resume/stop lifecycle."""

    def test_initial_state_idle(self) -> None:
        """Executor starts in IDLE state."""
        executor = StrategyExecutor()
        assert executor.state == ExecutorState.IDLE

    def test_start(self) -> None:
        """start() transitions to RUNNING."""
        executor = StrategyExecutor()
        executor.start()
        assert executor.state == ExecutorState.RUNNING

    def test_pause(self) -> None:
        """pause() transitions to PAUSED."""
        executor = StrategyExecutor()
        executor.start()
        executor.pause()
        assert executor.state == ExecutorState.PAUSED

    def test_resume_from_paused(self) -> None:
        """resume() transitions from PAUSED back to RUNNING."""
        executor = StrategyExecutor()
        executor.start()
        executor.pause()
        executor.resume()
        assert executor.state == ExecutorState.RUNNING

    def test_resume_from_non_paused_no_change(self) -> None:
        """resume() does nothing when not in PAUSED state."""
        executor = StrategyExecutor()
        executor.start()
        executor.resume()  # already RUNNING
        assert executor.state == ExecutorState.RUNNING

    def test_stop(self) -> None:
        """stop() transitions to STOPPED."""
        executor = StrategyExecutor()
        executor.start()
        executor.stop()
        assert executor.state == ExecutorState.STOPPED


# =============================================================================
# Data processing tests
# =============================================================================


class TestProcessData:
    """Tests for process_data feeding data to strategies."""

    def test_process_data_calls_enabled_strategies(self) -> None:
        """process_data collects signals from enabled strategies."""
        signal_a = MagicMock()
        signal_b = MagicMock()
        executor = StrategyExecutor()
        executor.register_strategy("alpha", _MockStrategy([signal_a]))
        executor.register_strategy("beta", _MockStrategy([signal_b]))
        results = executor.process_data(data=None)
        assert len(results) == 2
        strategy_names = {r["strategy"] for r in results}
        assert strategy_names == {"alpha", "beta"}

    def test_process_data_skips_disabled_strategies(self) -> None:
        """process_data does not call disabled strategies."""
        executor = StrategyExecutor()
        executor.register_strategy("alpha", _MockStrategy([MagicMock()]))
        executor.register_strategy(
            "beta", _MockStrategy([MagicMock()]), enabled=False
        )
        results = executor.process_data(data=None)
        assert len(results) == 1
        assert results[0]["strategy"] == "alpha"

    def test_process_data_paused_returns_empty(self) -> None:
        """When paused, process_data returns no results."""
        executor = StrategyExecutor()
        executor.register_strategy("alpha", _MockStrategy([MagicMock()]))
        executor.pause()
        results = executor.process_data(data=None)
        assert results == []

    def test_process_data_handles_strategy_error(self) -> None:
        """process_data catches strategy errors and continues."""
        executor = StrategyExecutor()
        executor.register_strategy("broken", _ErrorStrategy())
        executor.register_strategy("good", _MockStrategy([MagicMock()]))
        results = executor.process_data(data=None)
        # Only the good strategy produces results
        assert len(results) == 1
        assert results[0]["strategy"] == "good"
        # Error is recorded in strategy state
        states = executor.get_strategy_states()
        assert states["broken"].last_error == "strategy blew up"

    def test_process_data_tracks_signal_count(self) -> None:
        """process_data increments signals_generated on the strategy state."""
        executor = StrategyExecutor()
        executor.register_strategy(
            "alpha", _MockStrategy([MagicMock(), MagicMock()])
        )
        executor.process_data(data=None)
        states = executor.get_strategy_states()
        assert states["alpha"].signals_generated == 2

    def test_process_data_updates_last_signal_time(self) -> None:
        """process_data sets last_signal_time when signals are generated."""
        executor = StrategyExecutor()
        executor.register_strategy("alpha", _MockStrategy([MagicMock()]))
        executor.process_data(data=None)
        states = executor.get_strategy_states()
        assert states["alpha"].last_signal_time is not None

    def test_process_data_no_signals_no_last_signal_time(self) -> None:
        """last_signal_time stays None when strategy produces no signals."""
        executor = StrategyExecutor()
        executor.register_strategy("alpha", _MockStrategy([]))
        executor.process_data(data=None)
        states = executor.get_strategy_states()
        assert states["alpha"].last_signal_time is None
        assert states["alpha"].signals_generated == 0


# =============================================================================
# Summary and setter tests
# =============================================================================


class TestExecutorSummaryAndSetters:
    """Tests for get_summary and component setters."""

    def test_get_summary(self) -> None:
        """get_summary includes all required fields and counts."""
        executor = StrategyExecutor(paper_mode=True)
        executor.register_strategy("alpha", _MockStrategy([MagicMock()]))
        executor.register_strategy(
            "beta", _MockStrategy(), enabled=False
        )
        executor.start()
        executor.process_data(data=None)

        summary = executor.get_summary()
        assert summary["state"] == "running"
        assert summary["paper_mode"] is True
        assert summary["strategies_count"] == 2
        assert summary["enabled_count"] == 1
        assert summary["total_signals"] == 1
        assert summary["total_trades"] == 0
        assert "alpha" in summary["strategies"]
        assert "beta" in summary["strategies"]
        assert summary["strategies"]["alpha"]["enabled"] is True
        assert summary["strategies"]["alpha"]["signals"] == 1
        assert summary["strategies"]["beta"]["enabled"] is False

    def test_set_order_manager(self) -> None:
        """set_order_manager stores the order manager."""
        executor = StrategyExecutor()
        om = MagicMock()
        executor.set_order_manager(om)
        assert executor._order_manager is om

    def test_set_risk_manager(self) -> None:
        """set_risk_manager stores the risk manager."""
        executor = StrategyExecutor()
        rm = MagicMock()
        executor.set_risk_manager(rm)
        assert executor._risk_manager is rm

    def test_set_alert_manager(self) -> None:
        """set_alert_manager stores the alert manager."""
        executor = StrategyExecutor()
        am = MagicMock()
        executor.set_alert_manager(am)
        assert executor._alert_manager is am
