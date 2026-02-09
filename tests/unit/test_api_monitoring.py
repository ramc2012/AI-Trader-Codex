"""Tests for the monitoring API routes (system health and alerts).

Validates the /health/system, /alerts, /alerts/counts, and
/alerts/{alert_id}/acknowledge endpoints, ensuring correct
serialization and filtering of HealthMonitor and AlertManager
output through the FastAPI dependency injection layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Tuple

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.dependencies import (
    get_alert_manager,
    get_health_monitor,
    reset_managers,
)
from src.api.main import create_app
from src.monitoring.alerts import AlertLevel, AlertManager
from src.monitoring.health import ComponentHealth, HealthMonitor, HealthStatus


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def app() -> Tuple[FastAPI, HealthMonitor, AlertManager]:
    """Create a test app with fresh monitor and alert manager instances.

    Yields:
        Tuple of (FastAPI app, HealthMonitor, AlertManager).
    """
    reset_managers()
    application = create_app()

    hm = HealthMonitor()
    am = AlertManager()

    application.dependency_overrides[get_health_monitor] = lambda: hm
    application.dependency_overrides[get_alert_manager] = lambda: am

    yield application, hm, am

    reset_managers()


@pytest.fixture
def client(app: Tuple[FastAPI, HealthMonitor, AlertManager]) -> TestClient:
    """Create a TestClient bound to the test app.

    Args:
        app: The app fixture tuple.

    Returns:
        TestClient instance.
    """
    application, *_ = app
    return TestClient(application, raise_server_exceptions=False)


# =========================================================================
# System Health Endpoint Tests
# =========================================================================


class TestSystemHealth:
    """Tests for GET /api/v1/health/system."""

    def test_default_health_no_checks(
        self,
        app: Tuple[FastAPI, HealthMonitor, AlertManager],
        client: TestClient,
    ) -> None:
        """When no health checks are registered, overall status is UNKNOWN."""
        resp = client.get("/api/v1/health/system")
        assert resp.status_code == 200

        data = resp.json()
        assert data["overall_status"] == "unknown"
        assert data["components"] == {}
        assert "checked_at" in data

    def test_health_all_healthy(
        self,
        app: Tuple[FastAPI, HealthMonitor, AlertManager],
        client: TestClient,
    ) -> None:
        """When all registered checks pass, overall status is HEALTHY."""
        _, hm, _ = app

        def check_db() -> ComponentHealth:
            return ComponentHealth(
                name="database",
                status=HealthStatus.HEALTHY,
                last_check=datetime.now(),
                message="OK",
                latency_ms=5.2,
            )

        def check_redis() -> ComponentHealth:
            return ComponentHealth(
                name="redis",
                status=HealthStatus.HEALTHY,
                last_check=datetime.now(),
                message="Connected",
                latency_ms=1.1,
            )

        hm.register_check("database", check_db)
        hm.register_check("redis", check_redis)

        resp = client.get("/api/v1/health/system")
        assert resp.status_code == 200

        data = resp.json()
        assert data["overall_status"] == "healthy"
        assert "database" in data["components"]
        assert "redis" in data["components"]
        assert data["components"]["database"]["status"] == "healthy"
        assert data["components"]["database"]["message"] == "OK"
        assert data["components"]["database"]["latency_ms"] == 5.2
        assert data["components"]["redis"]["status"] == "healthy"

    def test_health_degraded(
        self,
        app: Tuple[FastAPI, HealthMonitor, AlertManager],
        client: TestClient,
    ) -> None:
        """When one check is degraded but none unhealthy, overall is DEGRADED."""
        _, hm, _ = app

        hm.register_check(
            "database",
            lambda: ComponentHealth(
                name="database",
                status=HealthStatus.HEALTHY,
                last_check=datetime.now(),
            ),
        )
        hm.register_check(
            "cache",
            lambda: ComponentHealth(
                name="cache",
                status=HealthStatus.DEGRADED,
                last_check=datetime.now(),
                message="High latency",
            ),
        )

        resp = client.get("/api/v1/health/system")
        assert resp.status_code == 200

        data = resp.json()
        assert data["overall_status"] == "degraded"
        assert data["components"]["cache"]["status"] == "degraded"
        assert data["components"]["cache"]["message"] == "High latency"

    def test_health_unhealthy(
        self,
        app: Tuple[FastAPI, HealthMonitor, AlertManager],
        client: TestClient,
    ) -> None:
        """When any check is unhealthy, overall status is UNHEALTHY."""
        _, hm, _ = app

        hm.register_check(
            "database",
            lambda: ComponentHealth(
                name="database",
                status=HealthStatus.UNHEALTHY,
                last_check=datetime.now(),
                message="Connection refused",
            ),
        )
        hm.register_check(
            "redis",
            lambda: ComponentHealth(
                name="redis",
                status=HealthStatus.HEALTHY,
                last_check=datetime.now(),
            ),
        )

        resp = client.get("/api/v1/health/system")
        assert resp.status_code == 200

        data = resp.json()
        assert data["overall_status"] == "unhealthy"
        assert data["components"]["database"]["status"] == "unhealthy"
        assert data["components"]["database"]["message"] == "Connection refused"

    def test_health_check_exception(
        self,
        app: Tuple[FastAPI, HealthMonitor, AlertManager],
        client: TestClient,
    ) -> None:
        """A check that raises an exception should report as UNHEALTHY."""
        _, hm, _ = app

        def failing_check() -> ComponentHealth:
            raise RuntimeError("DB connection timeout")

        hm.register_check("database", failing_check)

        resp = client.get("/api/v1/health/system")
        assert resp.status_code == 200

        data = resp.json()
        assert data["overall_status"] == "unhealthy"
        assert data["components"]["database"]["status"] == "unhealthy"
        assert "Check failed" in data["components"]["database"]["message"]


# =========================================================================
# Alerts List Endpoint Tests
# =========================================================================


class TestAlerts:
    """Tests for GET /api/v1/alerts."""

    def test_empty_alerts(
        self,
        app: Tuple[FastAPI, HealthMonitor, AlertManager],
        client: TestClient,
    ) -> None:
        """Empty alert list when no alerts have been sent."""
        resp = client.get("/api/v1/alerts")
        assert resp.status_code == 200

        data = resp.json()
        assert data == []

    def test_alerts_with_data(
        self,
        app: Tuple[FastAPI, HealthMonitor, AlertManager],
        client: TestClient,
    ) -> None:
        """Alerts list should include sent alerts with correct fields."""
        _, _, am = app

        am.send_alert(
            AlertLevel.INFO,
            "System started",
            "Trading system initialized",
            source="system",
        )
        am.send_alert(
            AlertLevel.WARNING,
            "High latency",
            "API latency above 500ms",
            source="api",
            metadata={"latency_ms": 650},
        )

        resp = client.get("/api/v1/alerts")
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) == 2

        # Verify first alert
        assert data[0]["level"] == "info"
        assert data[0]["title"] == "System started"
        assert data[0]["message"] == "Trading system initialized"
        assert data[0]["source"] == "system"
        assert data[0]["acknowledged"] is False
        assert data[0]["alert_id"].startswith("ALT-")

        # Verify second alert
        assert data[1]["level"] == "warning"
        assert data[1]["title"] == "High latency"
        assert data[1]["metadata"]["latency_ms"] == 650

    def test_filter_by_level(
        self,
        app: Tuple[FastAPI, HealthMonitor, AlertManager],
        client: TestClient,
    ) -> None:
        """Filtering alerts by level should return only matching alerts."""
        _, _, am = app

        am.send_alert(AlertLevel.INFO, "Info 1", "msg", source="sys")
        am.send_alert(AlertLevel.WARNING, "Warn 1", "msg", source="sys")
        am.send_alert(AlertLevel.CRITICAL, "Critical 1", "msg", source="sys")
        am.send_alert(AlertLevel.INFO, "Info 2", "msg", source="sys")

        # Filter for WARNING only
        resp = client.get("/api/v1/alerts?level=warning")
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) == 1
        assert data[0]["level"] == "warning"
        assert data[0]["title"] == "Warn 1"

    def test_filter_by_level_critical(
        self,
        app: Tuple[FastAPI, HealthMonitor, AlertManager],
        client: TestClient,
    ) -> None:
        """Filtering by critical level should return only critical alerts."""
        _, _, am = app

        am.send_alert(AlertLevel.INFO, "Info", "msg", source="a")
        am.send_alert(AlertLevel.CRITICAL, "Crit 1", "msg", source="b")
        am.send_alert(AlertLevel.CRITICAL, "Crit 2", "msg", source="c")

        resp = client.get("/api/v1/alerts?level=critical")
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) == 2
        assert all(a["level"] == "critical" for a in data)

    def test_filter_invalid_level(
        self,
        app: Tuple[FastAPI, HealthMonitor, AlertManager],
        client: TestClient,
    ) -> None:
        """An invalid level filter should return a 400 error."""
        resp = client.get("/api/v1/alerts?level=invalid_level")
        assert resp.status_code == 400
        assert "Invalid alert level" in resp.json()["detail"]

    def test_unacknowledged_only(
        self,
        app: Tuple[FastAPI, HealthMonitor, AlertManager],
        client: TestClient,
    ) -> None:
        """Filtering for unacknowledged_only should exclude acknowledged alerts."""
        _, _, am = app

        alert1 = am.send_alert(AlertLevel.INFO, "Alert 1", "msg", source="sys")
        am.send_alert(AlertLevel.WARNING, "Alert 2", "msg", source="sys")
        am.send_alert(AlertLevel.INFO, "Alert 3", "msg", source="sys")

        # Acknowledge the first alert
        am.acknowledge_alert(alert1.alert_id)

        resp = client.get("/api/v1/alerts?unacknowledged_only=true")
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) == 2
        assert all(a["acknowledged"] is False for a in data)

        # The acknowledged one should not be present
        alert_ids = [a["alert_id"] for a in data]
        assert alert1.alert_id not in alert_ids

    def test_filter_by_source(
        self,
        app: Tuple[FastAPI, HealthMonitor, AlertManager],
        client: TestClient,
    ) -> None:
        """Filtering by source should return only matching alerts."""
        _, _, am = app

        am.send_alert(AlertLevel.INFO, "A", "msg", source="risk")
        am.send_alert(AlertLevel.INFO, "B", "msg", source="strategy")
        am.send_alert(AlertLevel.WARNING, "C", "msg", source="risk")

        resp = client.get("/api/v1/alerts?source=risk")
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) == 2
        assert all(a["source"] == "risk" for a in data)

    def test_alerts_limit(
        self,
        app: Tuple[FastAPI, HealthMonitor, AlertManager],
        client: TestClient,
    ) -> None:
        """The limit parameter should cap the number of returned alerts."""
        _, _, am = app

        for i in range(10):
            am.send_alert(AlertLevel.INFO, f"Alert {i}", "msg", source="sys")

        resp = client.get("/api/v1/alerts?limit=3")
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) == 3


# =========================================================================
# Alert Counts Endpoint Tests
# =========================================================================


class TestAlertCounts:
    """Tests for GET /api/v1/alerts/counts."""

    def test_counts_empty(
        self,
        app: Tuple[FastAPI, HealthMonitor, AlertManager],
        client: TestClient,
    ) -> None:
        """All counts should be zero when no alerts exist."""
        resp = client.get("/api/v1/alerts/counts")
        assert resp.status_code == 200

        data = resp.json()
        assert data == {
            "info": 0,
            "warning": 0,
            "critical": 0,
            "emergency": 0,
        }

    def test_counts_with_mixed_levels(
        self,
        app: Tuple[FastAPI, HealthMonitor, AlertManager],
        client: TestClient,
    ) -> None:
        """Counts should accurately reflect alert distribution by level."""
        _, _, am = app

        # Send alerts across multiple levels
        am.send_alert(AlertLevel.INFO, "I1", "msg", source="a")
        am.send_alert(AlertLevel.INFO, "I2", "msg", source="a")
        am.send_alert(AlertLevel.INFO, "I3", "msg", source="b")
        am.send_alert(AlertLevel.WARNING, "W1", "msg", source="a")
        am.send_alert(AlertLevel.WARNING, "W2", "msg", source="b")
        am.send_alert(AlertLevel.CRITICAL, "C1", "msg", source="c")
        am.send_alert(AlertLevel.EMERGENCY, "E1", "msg", source="d")
        am.send_alert(AlertLevel.EMERGENCY, "E2", "msg", source="d")

        resp = client.get("/api/v1/alerts/counts")
        assert resp.status_code == 200

        data = resp.json()
        assert data["info"] == 3
        assert data["warning"] == 2
        assert data["critical"] == 1
        assert data["emergency"] == 2

    def test_counts_single_level(
        self,
        app: Tuple[FastAPI, HealthMonitor, AlertManager],
        client: TestClient,
    ) -> None:
        """Counts should work when all alerts are a single level."""
        _, _, am = app

        am.send_alert(AlertLevel.CRITICAL, "C1", "msg")
        am.send_alert(AlertLevel.CRITICAL, "C2", "msg")
        am.send_alert(AlertLevel.CRITICAL, "C3", "msg")

        resp = client.get("/api/v1/alerts/counts")
        assert resp.status_code == 200

        data = resp.json()
        assert data["info"] == 0
        assert data["warning"] == 0
        assert data["critical"] == 3
        assert data["emergency"] == 0


# =========================================================================
# Acknowledge Alert Endpoint Tests
# =========================================================================


class TestAcknowledgeAlert:
    """Tests for POST /api/v1/alerts/{alert_id}/acknowledge."""

    def test_acknowledge_existing_alert(
        self,
        app: Tuple[FastAPI, HealthMonitor, AlertManager],
        client: TestClient,
    ) -> None:
        """Acknowledging an existing alert should succeed with a message."""
        _, _, am = app

        alert = am.send_alert(
            AlertLevel.WARNING,
            "Test Alert",
            "Something happened",
            source="test",
        )
        alert_id = alert.alert_id

        resp = client.post(f"/api/v1/alerts/{alert_id}/acknowledge")
        assert resp.status_code == 200

        data = resp.json()
        assert "message" in data
        assert alert_id in data["message"]
        assert "acknowledged" in data["message"].lower()

        # Verify the alert is now acknowledged in the manager
        alerts = am.get_alerts(unacknowledged_only=False)
        matched = [a for a in alerts if a.alert_id == alert_id]
        assert len(matched) == 1
        assert matched[0].acknowledged is True

    def test_acknowledge_nonexistent_alert(
        self,
        app: Tuple[FastAPI, HealthMonitor, AlertManager],
        client: TestClient,
    ) -> None:
        """Acknowledging a non-existent alert should return 404."""
        resp = client.post("/api/v1/alerts/ALT-999999/acknowledge")
        assert resp.status_code == 404

        data = resp.json()
        assert "detail" in data
        assert "ALT-999999" in data["detail"]

    def test_acknowledge_idempotent(
        self,
        app: Tuple[FastAPI, HealthMonitor, AlertManager],
        client: TestClient,
    ) -> None:
        """Acknowledging an already-acknowledged alert should still succeed."""
        _, _, am = app

        alert = am.send_alert(
            AlertLevel.CRITICAL, "Crit", "msg", source="test"
        )
        alert_id = alert.alert_id

        # Acknowledge twice
        resp1 = client.post(f"/api/v1/alerts/{alert_id}/acknowledge")
        assert resp1.status_code == 200

        resp2 = client.post(f"/api/v1/alerts/{alert_id}/acknowledge")
        assert resp2.status_code == 200

    def test_acknowledge_does_not_affect_others(
        self,
        app: Tuple[FastAPI, HealthMonitor, AlertManager],
        client: TestClient,
    ) -> None:
        """Acknowledging one alert should not affect other alerts."""
        _, _, am = app

        alert1 = am.send_alert(AlertLevel.INFO, "A1", "msg", source="sys")
        alert2 = am.send_alert(AlertLevel.WARNING, "A2", "msg", source="sys")

        client.post(f"/api/v1/alerts/{alert1.alert_id}/acknowledge")

        # alert2 should still be unacknowledged
        unacked = am.get_alerts(unacknowledged_only=True)
        unacked_ids = [a.alert_id for a in unacked]
        assert alert2.alert_id in unacked_ids
        assert alert1.alert_id not in unacked_ids
