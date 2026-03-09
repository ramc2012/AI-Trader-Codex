"""Tests for AI agent historical simulation endpoint."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi.testclient import TestClient

import src.api.routes.agent as agent_module
from src.api.dependencies import reset_managers
from src.api.main import create_app
from src.data.ohlc_cache import get_ohlc_cache
from src.strategies.base import BaseStrategy, Signal, SignalStrength, SignalType


class DummyStrategy(BaseStrategy):
    """Deterministic strategy for simulate endpoint tests."""

    name = "DummyStrategy"

    def generate_signals(self, data):  # type: ignore[override]
        if len(data) < 30:
            return []
        ts_value = data["timestamp"].iloc[-1]
        ts = ts_value.to_pydatetime() if hasattr(ts_value, "to_pydatetime") else ts_value
        close = float(data["close"].iloc[-1])
        return [
            Signal(
                timestamp=ts,
                symbol="NSE:NIFTY50-INDEX",
                signal_type=SignalType.BUY,
                strength=SignalStrength.STRONG,
                price=close,
                stop_loss=close * 0.995,
                target=close * 1.005,
                strategy_name=self.name,
            )
        ]


def _seed_cache(symbol: str, timeframe: str, bars: int = 80) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None, second=0, microsecond=0)
    candles: list[dict[str, Any]] = []
    price = 24_000.0
    for i in range(bars):
        ts = now - timedelta(minutes=(bars - i) * 15)
        price += 2.0
        candles.append(
            {
                # Keep explicit UTC suffix to exercise tz-aware simulation clipping.
                "timestamp": ts.isoformat() + "Z",
                "open": price - 5.0,
                "high": price + 8.0,
                "low": price - 8.0,
                "close": price,
                "volume": 1_000 + i,
            }
        )
    cache = get_ohlc_cache()
    asyncio.run(cache.warm_up({symbol: {timeframe: candles}}))


def test_simulate_uses_cached_data_and_returns_trade_metrics() -> None:
    reset_managers()
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    strategy_key = "Dummy_Test"
    agent_module.STRATEGY_REGISTRY[strategy_key] = DummyStrategy
    _seed_cache("NSE:NIFTY50-INDEX", "15")

    try:
        resp = client.post(
            "/api/v1/agent/simulate",
            json={
                "symbols": ["NSE:NIFTY50-INDEX"],
                "strategies": [strategy_key],
                "timeframe": "15",
                "lookback_days": 10,
                "step_bars": 1,
                "capital": 250000,
                "max_hold_bars": 1,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "signals" in body
        assert "trades" in body
        assert "summary" in body
        assert len(body["signals"]) > 0
        assert len(body["trades"]) > 0
        assert body["summary"]["symbols_with_data"] == 1
        assert body["summary"]["data_sources"]["NSE:NIFTY50-INDEX"] == "cache"
        assert "total_trades" in body["summary"]
        assert body["summary"]["total_trades"] > 0
        assert "ending_capital" in body["summary"]
    finally:
        agent_module.STRATEGY_REGISTRY.pop(strategy_key, None)
        reset_managers()


def test_simulate_no_data_path_is_stable() -> None:
    reset_managers()
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    strategy_key = "Dummy_Test"
    agent_module.STRATEGY_REGISTRY[strategy_key] = DummyStrategy
    try:
        resp = client.post(
            "/api/v1/agent/simulate",
            json={
                "symbols": ["NSE:NONEXISTENT-INDEX"],
                "strategies": [strategy_key],
                "timeframe": "15",
                "lookback_days": 10,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["signals"] == []
        assert body["summary"]["symbols_with_data"] == 0
        assert "NSE:NONEXISTENT-INDEX" in body["summary"]["no_data_symbols"]
    finally:
        agent_module.STRATEGY_REGISTRY.pop(strategy_key, None)
        reset_managers()
