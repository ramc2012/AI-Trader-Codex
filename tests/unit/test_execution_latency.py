"""Tests for execution latency telemetry."""

from src.monitoring.latency import ExecutionLatencyTracker


def test_latency_tracker_snapshot_includes_stats_and_context() -> None:
    tracker = ExecutionLatencyTracker(enabled=True, max_samples=8)
    tracker.record("agent_cycle_ms", 10.0, cycle=1)
    tracker.record("agent_cycle_ms", 20.0, cycle=2)
    tracker.record("agent_cycle_ms", 30.0, cycle=3)

    snapshot = tracker.snapshot()

    assert snapshot["enabled"] is True
    metric = snapshot["metrics"]["agent_cycle_ms"]
    assert metric["count"] == 3
    assert metric["last_ms"] == 30.0
    assert metric["avg_ms"] == 20.0
    assert metric["p50_ms"] == 20.0
    assert metric["p95_ms"] == 30.0
    assert metric["last_context"] == {"cycle": 3}


def test_latency_tracker_disabled_snapshot_is_empty() -> None:
    tracker = ExecutionLatencyTracker(enabled=False, max_samples=8)

    tracker.record("agent_cycle_ms", 42.0, cycle=1)

    assert tracker.snapshot() == {
        "enabled": False,
        "window_size": 8,
        "metrics": {},
    }
