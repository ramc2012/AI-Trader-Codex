"""Tests for the alert system."""
import pytest
from unittest.mock import MagicMock

from src.monitoring.alerts import AlertLevel, Alert, AlertManager


class TestAlertManager:
    """Tests for AlertManager."""

    def test_send_alert_creates_alert_with_correct_fields(self) -> None:
        mgr = AlertManager()
        alert = mgr.send_alert(
            AlertLevel.WARNING, "High latency", "DB latency > 500ms",
            source="db_monitor", metadata={"latency_ms": 520},
        )
        assert alert.level == AlertLevel.WARNING
        assert alert.title == "High latency"
        assert alert.message == "DB latency > 500ms"
        assert alert.source == "db_monitor"
        assert alert.metadata == {"latency_ms": 520}
        assert alert.alert_id == "ALT-000001"
        assert alert.acknowledged is False

    def test_alert_id_increments(self) -> None:
        mgr = AlertManager()
        a1 = mgr.info("t1", "m1")
        a2 = mgr.info("t2", "m2")
        assert a1.alert_id == "ALT-000001"
        assert a2.alert_id == "ALT-000002"

    # ---- Convenience methods ----

    def test_info_convenience(self) -> None:
        mgr = AlertManager()
        alert = mgr.info("Info title", "Info message", source="src")
        assert alert.level == AlertLevel.INFO

    def test_warning_convenience(self) -> None:
        mgr = AlertManager()
        alert = mgr.warning("Warn title", "Warn msg", source="src")
        assert alert.level == AlertLevel.WARNING

    def test_critical_convenience(self) -> None:
        mgr = AlertManager()
        alert = mgr.critical("Crit title", "Crit msg", source="src")
        assert alert.level == AlertLevel.CRITICAL

    def test_emergency_convenience(self) -> None:
        mgr = AlertManager()
        alert = mgr.emergency("Emerg title", "Emerg msg", source="src")
        assert alert.level == AlertLevel.EMERGENCY

    # ---- Callback tests ----

    def test_callback_registration_and_invocation(self) -> None:
        mgr = AlertManager()
        cb = MagicMock()
        mgr.register_callback(AlertLevel.WARNING, cb)

        alert = mgr.warning("test", "msg")
        cb.assert_called_once_with(alert)

    def test_critical_triggers_warning_and_info_callbacks(self) -> None:
        """CRITICAL alert should cascade and trigger WARNING and INFO callbacks."""
        mgr = AlertManager()
        info_cb = MagicMock()
        warn_cb = MagicMock()
        crit_cb = MagicMock()

        mgr.register_callback(AlertLevel.INFO, info_cb)
        mgr.register_callback(AlertLevel.WARNING, warn_cb)
        mgr.register_callback(AlertLevel.CRITICAL, crit_cb)

        alert = mgr.critical("critical event", "something bad")

        info_cb.assert_called_once_with(alert)
        warn_cb.assert_called_once_with(alert)
        crit_cb.assert_called_once_with(alert)

    def test_emergency_triggers_all_callbacks(self) -> None:
        mgr = AlertManager()
        callbacks = {level: MagicMock() for level in AlertLevel}
        for level, cb in callbacks.items():
            mgr.register_callback(level, cb)

        alert = mgr.emergency("emergency", "total failure")

        for cb in callbacks.values():
            cb.assert_called_once_with(alert)

    def test_info_only_triggers_info_callbacks(self) -> None:
        mgr = AlertManager()
        info_cb = MagicMock()
        warn_cb = MagicMock()

        mgr.register_callback(AlertLevel.INFO, info_cb)
        mgr.register_callback(AlertLevel.WARNING, warn_cb)

        mgr.info("low priority", "just fyi")

        info_cb.assert_called_once()
        warn_cb.assert_not_called()

    def test_callback_exception_does_not_break_alert(self) -> None:
        mgr = AlertManager()
        bad_cb = MagicMock(side_effect=RuntimeError("boom"))
        mgr.register_callback(AlertLevel.INFO, bad_cb)

        # Should not raise
        alert = mgr.info("test", "msg")
        assert alert.alert_id == "ALT-000001"

    # ---- Filtering ----

    def test_get_alerts_filter_by_level(self) -> None:
        mgr = AlertManager()
        mgr.info("a", "m")
        mgr.warning("b", "m")
        mgr.info("c", "m")

        result = mgr.get_alerts(level=AlertLevel.INFO)
        assert len(result) == 2
        assert all(a.level == AlertLevel.INFO for a in result)

    def test_get_alerts_filter_by_source(self) -> None:
        mgr = AlertManager()
        mgr.info("a", "m", source="db")
        mgr.info("b", "m", source="redis")
        mgr.info("c", "m", source="db")

        result = mgr.get_alerts(source="db")
        assert len(result) == 2

    def test_get_alerts_unacknowledged_only(self) -> None:
        mgr = AlertManager()
        a1 = mgr.info("a", "m")
        mgr.info("b", "m")
        mgr.acknowledge_alert(a1.alert_id)

        result = mgr.get_alerts(unacknowledged_only=True)
        assert len(result) == 1
        assert result[0].title == "b"

    def test_get_alerts_limit(self) -> None:
        mgr = AlertManager()
        for i in range(10):
            mgr.info(f"alert-{i}", "msg")

        result = mgr.get_alerts(limit=3)
        assert len(result) == 3
        # Should return last 3
        assert result[0].title == "alert-7"

    # ---- Acknowledge ----

    def test_acknowledge_alert(self) -> None:
        mgr = AlertManager()
        alert = mgr.info("test", "msg")
        assert mgr.acknowledge_alert(alert.alert_id) is True

        alerts = mgr.get_alerts()
        assert alerts[0].acknowledged is True

    def test_acknowledge_unknown_id_returns_false(self) -> None:
        mgr = AlertManager()
        assert mgr.acknowledge_alert("ALT-999999") is False

    # ---- Suppression ----

    def test_suppress_source_prevents_storage_and_callbacks(self) -> None:
        mgr = AlertManager()
        cb = MagicMock()
        mgr.register_callback(AlertLevel.INFO, cb)

        mgr.suppress_source("noisy")
        alert = mgr.info("test", "msg", source="noisy")

        # Alert returned but not stored
        assert alert.title == "test"
        assert len(mgr.get_alerts()) == 0
        cb.assert_not_called()

    def test_unsuppress_source_re_enables(self) -> None:
        mgr = AlertManager()
        mgr.suppress_source("src")
        mgr.unsuppress_source("src")

        mgr.info("after unsuppress", "msg", source="src")
        assert len(mgr.get_alerts()) == 1

    # ---- History management ----

    def test_max_history_limit_enforced(self) -> None:
        mgr = AlertManager(max_history=5)
        for i in range(10):
            mgr.info(f"alert-{i}", "msg")

        alerts = mgr.get_alerts(limit=100)
        assert len(alerts) == 5
        # Should keep the most recent
        assert alerts[0].title == "alert-5"
        assert alerts[-1].title == "alert-9"

    def test_get_alert_counts(self) -> None:
        mgr = AlertManager()
        mgr.info("a", "m")
        mgr.info("b", "m")
        mgr.warning("c", "m")
        mgr.critical("d", "m")

        counts = mgr.get_alert_counts()
        assert counts["info"] == 2
        assert counts["warning"] == 1
        assert counts["critical"] == 1
        assert counts["emergency"] == 0

    def test_clear_history_resets(self) -> None:
        mgr = AlertManager()
        mgr.info("a", "m")
        mgr.warning("b", "m")

        mgr.clear_history()
        assert len(mgr.get_alerts()) == 0

        # Counter also resets
        alert = mgr.info("after clear", "m")
        assert alert.alert_id == "ALT-000001"
