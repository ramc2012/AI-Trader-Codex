"""Lightweight in-memory execution latency telemetry."""

from __future__ import annotations

from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass, field
import math
from threading import Lock
import time
from typing import Any, Deque, Dict, Iterator


@dataclass
class LatencySample:
    duration_ms: float
    context: Dict[str, Any] = field(default_factory=dict)


class ExecutionLatencyTracker:
    """Collect bounded latency samples for hot-path observability."""

    def __init__(self, *, enabled: bool = True, max_samples: int = 256) -> None:
        self._enabled = bool(enabled)
        self._max_samples = max(int(max_samples), 1)
        self._samples: Dict[str, Deque[LatencySample]] = defaultdict(
            lambda: deque(maxlen=self._max_samples)
        )
        self._lock = Lock()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def record(self, metric: str, duration_ms: float, **context: Any) -> None:
        if not self._enabled or not str(metric or "").strip():
            return

        sample = LatencySample(
            duration_ms=max(float(duration_ms), 0.0),
            context={k: v for k, v in context.items() if v is not None},
        )
        with self._lock:
            self._samples[metric].append(sample)

    @contextmanager
    def track(self, metric: str, **context: Any) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            self.record(metric, elapsed_ms, **context)

    def snapshot(self) -> Dict[str, Any]:
        if not self._enabled:
            return {"enabled": False, "window_size": self._max_samples, "metrics": {}}

        with self._lock:
            buckets = {
                metric: list(samples)
                for metric, samples in self._samples.items()
                if samples
            }

        metrics: Dict[str, Any] = {}
        for metric, samples in buckets.items():
            durations = sorted(sample.duration_ms for sample in samples)
            count = len(durations)
            last_sample = samples[-1]
            metrics[metric] = {
                "count": count,
                "last_ms": round(last_sample.duration_ms, 2),
                "avg_ms": round(sum(durations) / count, 2),
                "min_ms": round(durations[0], 2),
                "p50_ms": round(self._percentile(durations, 0.50), 2),
                "p95_ms": round(self._percentile(durations, 0.95), 2),
                "max_ms": round(durations[-1], 2),
                "last_context": dict(last_sample.context),
            }

        return {
            "enabled": True,
            "window_size": self._max_samples,
            "metrics": metrics,
        }

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float:
        if not values:
            return 0.0
        if len(values) == 1:
            return values[0]
        rank = max(0, min(len(values) - 1, math.ceil(len(values) * percentile) - 1))
        return values[rank]
