"""Monitoring API endpoints -- system health and alerts.

Provides REST access to system health checks, alert history,
alert counts, and alert acknowledgement.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.dependencies import get_alert_manager, get_health_monitor
from src.api.schemas import (
    AlertCountsResponse,
    AlertResponse,
    ComponentHealthResponse,
    SystemHealthResponse,
)
from src.monitoring.alerts import AlertLevel, AlertManager
from src.monitoring.health import HealthMonitor

router = APIRouter(tags=["Monitoring"])


# =========================================================================
# Endpoints
# =========================================================================


@router.get("/health/system", response_model=SystemHealthResponse)
def system_health(
    monitor: HealthMonitor = Depends(get_health_monitor),
) -> SystemHealthResponse:
    """Run all registered health checks and return system status.

    Executes each registered check function, then returns the
    overall status and per-component results.
    """
    monitor.run_checks()
    status = monitor.get_status()

    components: Dict[str, ComponentHealthResponse] = {}
    for name, comp in status.components.items():
        components[name] = ComponentHealthResponse(
            name=comp.name,
            status=comp.status.value,
            last_check=comp.last_check,
            message=comp.message,
            latency_ms=comp.latency_ms,
            metadata=comp.metadata,
        )

    return SystemHealthResponse(
        overall_status=status.overall_status.value,
        checked_at=status.checked_at,
        components=components,
    )


@router.get("/alerts", response_model=List[AlertResponse])
def list_alerts(
    level: Optional[str] = Query(
        default=None,
        description="Filter by alert level (info, warning, critical, emergency)",
    ),
    source: Optional[str] = Query(
        default=None, description="Filter by alert source"
    ),
    unacknowledged_only: bool = Query(
        default=False, description="Only return unacknowledged alerts"
    ),
    limit: int = Query(
        default=50, ge=1, le=1000, description="Max alerts to return"
    ),
    am: AlertManager = Depends(get_alert_manager),
) -> List[AlertResponse]:
    """List alerts with optional filters.

    Args:
        level: Filter by alert level string.
        source: Filter by source component.
        unacknowledged_only: If True, return only unacknowledged alerts.
        limit: Maximum number of alerts to return.

    Returns:
        List of alerts matching the filters.
    """
    # Convert level string to AlertLevel enum if provided
    alert_level: Optional[AlertLevel] = None
    if level is not None:
        try:
            alert_level = AlertLevel(level.lower())
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid alert level '{level}'. "
                       f"Valid: info, warning, critical, emergency",
            )

    alerts = am.get_alerts(
        level=alert_level,
        source=source,
        unacknowledged_only=unacknowledged_only,
        limit=limit,
    )

    return [
        AlertResponse(
            alert_id=a.alert_id,
            level=a.level.value,
            title=a.title,
            message=a.message,
            source=a.source,
            timestamp=a.timestamp,
            metadata=a.metadata,
            acknowledged=a.acknowledged,
        )
        for a in alerts
    ]


@router.get("/alerts/counts", response_model=AlertCountsResponse)
def alert_counts(
    am: AlertManager = Depends(get_alert_manager),
) -> AlertCountsResponse:
    """Get alert counts grouped by level."""
    counts = am.get_alert_counts()
    return AlertCountsResponse(
        info=counts.get("info", 0),
        warning=counts.get("warning", 0),
        critical=counts.get("critical", 0),
        emergency=counts.get("emergency", 0),
    )


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(
    alert_id: str,
    am: AlertManager = Depends(get_alert_manager),
) -> Dict[str, str]:
    """Acknowledge an alert by its ID.

    Args:
        alert_id: The unique alert identifier (e.g. 'ALT-000001').

    Returns:
        Confirmation message.

    Raises:
        HTTPException: If the alert is not found.
    """
    success = am.acknowledge_alert(alert_id)
    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"Alert '{alert_id}' not found.",
        )
    return {"message": f"Alert '{alert_id}' acknowledged."}
