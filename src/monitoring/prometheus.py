"""Prometheus metrics telemetry for the AI Trading Agent."""

import time
from typing import Any

from prometheus_client import Counter, Gauge, Histogram

# --- Metrics Registry ---
# Metrics will be automatically exposed if the app uses prometheus_fastapi_instrumentator or similar
# We define them globally so they can be updated anywhere in the code.

AGENT_TRADES_EXECUTED = Counter(
    "agent_trades_executed_total",
    "Total number of trades executed by the AI agent",
    ["strategy", "signal_type"]
)

AGENT_SIGNALS_GENERATED = Counter(
    "agent_signals_generated_total",
    "Total number of valid signals generated",
    ["strategy", "symbol"]
)

AGENT_LIVE_PNL = Gauge(
    "agent_live_pnl_gauge",
    "Current aggregate unrealized and realized P&L",
)

ML_INFERENCE_LATENCY = Histogram(
    "ml_inference_latency_ms",
    "Latency of batched ML inferences in milliseconds",
    buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000]
)

ACTIVE_POSITIONS_COUNT = Gauge(
    "agent_active_positions",
    "Number of currently open trading positions",
)

MARKET_DATA_LATENCY = Histogram(
    "market_data_fetch_latency_ms",
    "Latency of fetching historical OHLC data from broker API",
    buckets=[50, 100, 250, 500, 1000, 2000, 5000]
)

class MetricsMiddleware:
    """Helper functions to update metrics in a clean way."""
    
    @staticmethod
    def record_trade(strategy: str, signal_type: str) -> None:
        """Increment trade execution counter."""
        AGENT_TRADES_EXECUTED.labels(strategy=strategy, signal_type=signal_type).inc()
        
    @staticmethod
    def record_signal(strategy: str, symbol: str) -> None:
        """Increment generated signal counter."""
        AGENT_SIGNALS_GENERATED.labels(strategy=strategy, symbol=symbol).inc()
        
    @staticmethod
    def update_pnl(pnl: float) -> None:
        """Update the aggregate P&L gauge."""
        AGENT_LIVE_PNL.set(pnl)
        
    @staticmethod
    def update_open_positions(count: int) -> None:
        """Update active positions count."""
        ACTIVE_POSITIONS_COUNT.set(count)
        
    @staticmethod
    def record_ml_latency(latency_ms: float) -> None:
        """Record inference timing."""
        ML_INFERENCE_LATENCY.observe(latency_ms)

    @staticmethod
    def record_data_latency(latency_ms: float) -> None:
        """Record broker API timing."""
        MARKET_DATA_LATENCY.observe(latency_ms)
