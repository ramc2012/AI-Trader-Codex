"""System health monitoring for trading infrastructure."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional, List, Any, Callable
from enum import Enum
from src.utils.logger import get_logger

logger = get_logger(__name__)


class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ComponentHealth:
    name: str
    status: HealthStatus
    last_check: datetime
    message: str = ""
    latency_ms: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_healthy(self) -> bool:
        return self.status == HealthStatus.HEALTHY


@dataclass
class SystemHealth:
    components: Dict[str, ComponentHealth] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=datetime.now)

    @property
    def overall_status(self) -> HealthStatus:
        if not self.components:
            return HealthStatus.UNKNOWN
        statuses = [c.status for c in self.components.values()]
        if all(s == HealthStatus.HEALTHY for s in statuses):
            return HealthStatus.HEALTHY
        if any(s == HealthStatus.UNHEALTHY for s in statuses):
            return HealthStatus.UNHEALTHY
        return HealthStatus.DEGRADED

    @property
    def is_healthy(self) -> bool:
        return self.overall_status == HealthStatus.HEALTHY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_status": self.overall_status.value,
            "checked_at": self.checked_at.isoformat(),
            "components": {
                name: {"status": c.status.value, "last_check": c.last_check.isoformat(),
                       "message": c.message, "latency_ms": c.latency_ms}
                for name, c in self.components.items()
            },
        }


class HealthMonitor:
    def __init__(self) -> None:
        self._checks: Dict[str, Callable[[], ComponentHealth]] = {}
        self._last_results: Dict[str, ComponentHealth] = {}

    def register_check(self, name: str, check_fn: Callable[[], ComponentHealth]) -> None:
        self._checks[name] = check_fn

    def unregister_check(self, name: str) -> None:
        self._checks.pop(name, None)
        self._last_results.pop(name, None)

    def run_checks(self) -> SystemHealth:
        health = SystemHealth(checked_at=datetime.now())
        for name, fn in self._checks.items():
            result = self.run_check(name)
            health.components[name] = result
        return health

    def run_check(self, name: str) -> ComponentHealth:
        if name not in self._checks:
            raise ValueError(f"No check registered with name '{name}'")
        try:
            result = self._checks[name]()
            self._last_results[name] = result
            return result
        except Exception as e:
            result = ComponentHealth(name=name, status=HealthStatus.UNHEALTHY,
                                     last_check=datetime.now(), message=f"Check failed: {e}")
            self._last_results[name] = result
            return result

    def get_status(self) -> SystemHealth:
        health = SystemHealth(checked_at=datetime.now())
        health.components = dict(self._last_results)
        return health

    def get_unhealthy_components(self) -> List[ComponentHealth]:
        return [c for c in self._last_results.values() if not c.is_healthy]
