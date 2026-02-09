"""Tests for system health monitoring."""
import pytest
from datetime import datetime

from src.monitoring.health import (
    HealthStatus,
    ComponentHealth,
    SystemHealth,
    HealthMonitor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_healthy(name: str = "test") -> ComponentHealth:
    return ComponentHealth(
        name=name, status=HealthStatus.HEALTHY, last_check=datetime.now()
    )


def _make_unhealthy(name: str = "test") -> ComponentHealth:
    return ComponentHealth(
        name=name,
        status=HealthStatus.UNHEALTHY,
        last_check=datetime.now(),
        message="something broke",
    )


def _make_degraded(name: str = "test") -> ComponentHealth:
    return ComponentHealth(
        name=name, status=HealthStatus.DEGRADED, last_check=datetime.now()
    )


# ---------------------------------------------------------------------------
# ComponentHealth tests
# ---------------------------------------------------------------------------

class TestComponentHealth:
    def test_is_healthy_true(self) -> None:
        comp = _make_healthy()
        assert comp.is_healthy is True

    def test_is_healthy_false_when_unhealthy(self) -> None:
        comp = _make_unhealthy()
        assert comp.is_healthy is False

    def test_is_healthy_false_when_degraded(self) -> None:
        comp = _make_degraded()
        assert comp.is_healthy is False


# ---------------------------------------------------------------------------
# SystemHealth tests
# ---------------------------------------------------------------------------

class TestSystemHealth:
    def test_overall_status_unknown_when_empty(self) -> None:
        health = SystemHealth()
        assert health.overall_status == HealthStatus.UNKNOWN

    def test_overall_status_healthy(self) -> None:
        health = SystemHealth(
            components={"a": _make_healthy("a"), "b": _make_healthy("b")}
        )
        assert health.overall_status == HealthStatus.HEALTHY

    def test_overall_status_unhealthy(self) -> None:
        health = SystemHealth(
            components={"a": _make_healthy("a"), "b": _make_unhealthy("b")}
        )
        assert health.overall_status == HealthStatus.UNHEALTHY

    def test_overall_status_degraded(self) -> None:
        health = SystemHealth(
            components={"a": _make_healthy("a"), "b": _make_degraded("b")}
        )
        assert health.overall_status == HealthStatus.DEGRADED

    def test_is_healthy_property(self) -> None:
        healthy = SystemHealth(components={"a": _make_healthy("a")})
        assert healthy.is_healthy is True

        unhealthy = SystemHealth(
            components={"a": _make_unhealthy("a")}
        )
        assert unhealthy.is_healthy is False

    def test_to_dict_serialization(self) -> None:
        comp = _make_healthy("db")
        health = SystemHealth(components={"db": comp})
        d = health.to_dict()

        assert d["overall_status"] == "healthy"
        assert "checked_at" in d
        assert "db" in d["components"]
        assert d["components"]["db"]["status"] == "healthy"
        assert "last_check" in d["components"]["db"]
        assert "latency_ms" in d["components"]["db"]


# ---------------------------------------------------------------------------
# HealthMonitor tests
# ---------------------------------------------------------------------------

class TestHealthMonitor:
    def test_register_and_run_checks(self) -> None:
        monitor = HealthMonitor()
        monitor.register_check("db", lambda: _make_healthy("db"))
        monitor.register_check("redis", lambda: _make_healthy("redis"))

        result = monitor.run_checks()
        assert len(result.components) == 2
        assert result.overall_status == HealthStatus.HEALTHY

    def test_run_check_single_component(self) -> None:
        monitor = HealthMonitor()
        monitor.register_check("db", lambda: _make_healthy("db"))

        comp = monitor.run_check("db")
        assert comp.name == "db"
        assert comp.is_healthy is True

    def test_run_check_unknown_name_raises(self) -> None:
        monitor = HealthMonitor()
        with pytest.raises(ValueError, match="No check registered"):
            monitor.run_check("nonexistent")

    def test_check_function_raises_exception_returns_unhealthy(self) -> None:
        def bad_check() -> ComponentHealth:
            raise RuntimeError("connection refused")

        monitor = HealthMonitor()
        monitor.register_check("db", bad_check)

        comp = monitor.run_check("db")
        assert comp.status == HealthStatus.UNHEALTHY
        assert "connection refused" in comp.message

    def test_unregister_check(self) -> None:
        monitor = HealthMonitor()
        monitor.register_check("db", lambda: _make_healthy("db"))
        monitor.run_check("db")

        monitor.unregister_check("db")
        # Check is gone
        with pytest.raises(ValueError):
            monitor.run_check("db")

        # Last results also cleared
        status = monitor.get_status()
        assert len(status.components) == 0

    def test_get_unhealthy_components(self) -> None:
        monitor = HealthMonitor()
        monitor.register_check("db", lambda: _make_healthy("db"))
        monitor.register_check("redis", lambda: _make_unhealthy("redis"))
        monitor.run_checks()

        unhealthy = monitor.get_unhealthy_components()
        assert len(unhealthy) == 1
        assert unhealthy[0].name == "redis"

    def test_get_unhealthy_components_empty_when_all_healthy(self) -> None:
        monitor = HealthMonitor()
        monitor.register_check("db", lambda: _make_healthy("db"))
        monitor.run_checks()

        assert monitor.get_unhealthy_components() == []

    def test_get_status_returns_last_known_results(self) -> None:
        monitor = HealthMonitor()
        monitor.register_check("db", lambda: _make_healthy("db"))
        monitor.run_checks()

        status = monitor.get_status()
        assert "db" in status.components
        assert status.components["db"].is_healthy is True

    def test_get_status_empty_before_any_checks(self) -> None:
        monitor = HealthMonitor()
        monitor.register_check("db", lambda: _make_healthy("db"))
        # No run_checks() called
        status = monitor.get_status()
        assert len(status.components) == 0
        assert status.overall_status == HealthStatus.UNKNOWN

    def test_run_checks_mixed_health(self) -> None:
        monitor = HealthMonitor()
        monitor.register_check("db", lambda: _make_healthy("db"))
        monitor.register_check("redis", lambda: _make_degraded("redis"))

        result = monitor.run_checks()
        assert result.overall_status == HealthStatus.DEGRADED

    def test_component_health_metadata(self) -> None:
        comp = ComponentHealth(
            name="db",
            status=HealthStatus.HEALTHY,
            last_check=datetime.now(),
            latency_ms=12.5,
            metadata={"version": "14.2"},
        )
        assert comp.latency_ms == 12.5
        assert comp.metadata["version"] == "14.2"
