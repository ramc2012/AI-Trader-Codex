"""Alert system for trading notifications."""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any, Callable
from src.utils.logger import get_logger
from src.utils.pubsub import get_state_change_bus

logger = get_logger(__name__)


class AlertLevel(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"

# Priority ordering for cascade
_LEVEL_PRIORITY = {
    AlertLevel.INFO: 0,
    AlertLevel.WARNING: 1,
    AlertLevel.CRITICAL: 2,
    AlertLevel.EMERGENCY: 3,
}


@dataclass
class Alert:
    level: AlertLevel
    title: str
    message: str
    source: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    acknowledged: bool = False
    alert_id: str = ""


class AlertManager:
    def __init__(self, max_history: int = 1000) -> None:
        self._alerts: List[Alert] = []
        self._callbacks: Dict[AlertLevel, List[Callable[[Alert], None]]] = {
            level: [] for level in AlertLevel
        }
        self._max_history = max_history
        self._alert_counter = 0
        self._suppressed_sources: set = set()

    def send_alert(self, level: AlertLevel, title: str, message: str,
                   source: str = "", metadata: Optional[Dict[str, Any]] = None) -> Alert:
        if source in self._suppressed_sources:
            logger.debug("Alert suppressed", source=source, title=title)
            # Still create and return the alert but don't store or fire callbacks
            return Alert(level=level, title=title, message=message, source=source,
                         metadata=metadata or {})

        self._alert_counter += 1
        alert = Alert(level=level, title=title, message=message, source=source,
                      metadata=metadata or {}, alert_id=f"ALT-{self._alert_counter:06d}")

        self._alerts.append(alert)
        if len(self._alerts) > self._max_history:
            self._alerts = self._alerts[-self._max_history:]

        # Fire callbacks for this level and all lower levels
        alert_priority = _LEVEL_PRIORITY[level]
        for cb_level, cbs in self._callbacks.items():
            if _LEVEL_PRIORITY[cb_level] <= alert_priority:
                for cb in cbs:
                    try:
                        cb(alert)
                    except Exception as e:
                        logger.error("Alert callback failed", error=str(e))

        logger.info("Alert sent", level=level.value, title=title, source=source)
        try:
            get_state_change_bus().notify("alerts")
        except Exception:
            pass
        return alert

    def info(self, title: str, message: str, source: str = "", **kwargs: Any) -> Alert:
        return self.send_alert(AlertLevel.INFO, title, message, source, kwargs or None)

    def warning(self, title: str, message: str, source: str = "", **kwargs: Any) -> Alert:
        return self.send_alert(AlertLevel.WARNING, title, message, source, kwargs or None)

    def critical(self, title: str, message: str, source: str = "", **kwargs: Any) -> Alert:
        return self.send_alert(AlertLevel.CRITICAL, title, message, source, kwargs or None)

    def emergency(self, title: str, message: str, source: str = "", **kwargs: Any) -> Alert:
        return self.send_alert(AlertLevel.EMERGENCY, title, message, source, kwargs or None)

    def register_callback(self, level: AlertLevel, callback: Callable[[Alert], None]) -> None:
        self._callbacks[level].append(callback)

    def acknowledge_alert(self, alert_id: str) -> bool:
        for alert in self._alerts:
            if alert.alert_id == alert_id:
                alert.acknowledged = True
                return True
        return False

    def get_alerts(self, level: Optional[AlertLevel] = None,
                   source: Optional[str] = None,
                   unacknowledged_only: bool = False,
                   limit: int = 50) -> List[Alert]:
        result = list(self._alerts)
        if level is not None:
            result = [a for a in result if a.level == level]
        if source is not None:
            result = [a for a in result if a.source == source]
        if unacknowledged_only:
            result = [a for a in result if not a.acknowledged]
        return result[-limit:]

    def get_alert_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {level.value: 0 for level in AlertLevel}
        for alert in self._alerts:
            counts[alert.level.value] += 1
        return counts

    def suppress_source(self, source: str) -> None:
        self._suppressed_sources.add(source)

    def unsuppress_source(self, source: str) -> None:
        self._suppressed_sources.discard(source)

    def clear_history(self) -> None:
        self._alerts.clear()
        self._alert_counter = 0
