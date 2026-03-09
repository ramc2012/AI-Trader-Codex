"""Tests for the AI agent inspector endpoint."""

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


class DummyInspectorStrategy(BaseStrategy):
    """Deterministic strategy for agent inspector endpoint tests."""

    name = "Dummy_Test"

    def __init__(self, threshold: float = 20.0, allow_short: bool = False) -> None:
        self.threshold = threshold
        self.allow_short = allow_short

    def generate_signals(self, data):  # type: ignore[override]
        if len(data) < 20:
            return []
        ts_value = data["timestamp"].iloc[-1]
        ts = ts_value.to_pydatetime() if hasattr(ts_value, "to_pydatetime") else ts_value
        close = float(data["close"].iloc[-1])
        return [
            Signal(
                timestamp=ts,
                symbol=str(data["symbol"].iloc[-1]) if "symbol" in data.columns else "NSE:NIFTY50-INDEX",
                signal_type=SignalType.BUY,
                strength=SignalStrength.MODERATE,
                price=close,
                stop_loss=close * 0.99,
                target=close * 1.02,
                strategy_name=self.name,
                metadata={"test_indicator": close - 10.0},
            )
        ]


def _seed_cache(symbol: str, timeframe: str, bars: int) -> None:
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    token = str(timeframe).upper()
    if token == "D":
        step = timedelta(days=1)
    else:
        step = timedelta(minutes=max(int(token), 1))

    candles: list[dict[str, Any]] = []
    price = 24_000.0
    for i in range(bars):
        ts = now - (step * (bars - i))
        price += 4.0
        candles.append(
            {
                "timestamp": ts.isoformat(),
                "open": price - 6.0,
                "high": price + 10.0,
                "low": price - 8.0,
                "close": price,
                "volume": 1_000 + i,
            }
        )
    cache = get_ohlc_cache()
    asyncio.run(cache.warm_up({symbol: {timeframe: candles}}))


def _mock_options_analytics() -> dict[str, Any]:
    return {
        "market": "NSE",
        "underlying_symbol": "NSE:NIFTY50-INDEX",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "nearest_expiry": "2026-03-12",
        "days_to_expiry": 4,
        "spot": 24050.0,
        "lot_size": 25,
        "pcr": 0.94,
        "total_call_oi": 120000,
        "total_put_oi": 112000,
        "call_oi_change": 5000,
        "put_oi_change": 4300,
        "avg_call_iv": 0.18,
        "avg_put_iv": 0.19,
        "max_call_oi_strike": 24100.0,
        "max_put_oi_strike": 23900.0,
        "atm_strike": 24050.0,
        "atm_call": None,
        "atm_put": None,
        "bullish_call": None,
        "bearish_put": None,
        "suggested_side": "neutral",
        "selected_contract": None,
        "chain_quality": {"integrity_score": 100},
    }


def test_agent_inspector_returns_live_input_payload() -> None:
    reset_managers()
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    agent_module.STRATEGY_REGISTRY[DummyInspectorStrategy.name] = DummyInspectorStrategy
    symbol = "NSE:NIFTY50-INDEX"
    _seed_cache(symbol, "5", bars=140)
    _seed_cache(symbol, "60", bars=60)
    _seed_cache(symbol, "D", bars=40)

    try:
        agent = agent_module.get_trading_agent()

        async def fake_options(*_args, **_kwargs):
            return _mock_options_analytics()

        agent.get_options_trade_analytics = fake_options  # type: ignore[method-assign]
        resp = client.get(
            "/api/v1/agent/inspector",
            params={
                "symbol": symbol,
                "timeframe": "5",
                "lookback_bars": 120,
                "strategies": DummyInspectorStrategy.name,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["symbol"] == symbol
        assert body["timeframe"] == "5"
        assert body["data_window"]["bars"] == 120
        assert body["latest_bar"]["close"] > 0
        assert len(body["recent_bars"]) > 0
        assert "common_indicators" in body
        assert body["reference_bias"]["timeframes"]
        assert body["options_analytics"]["underlying_symbol"] == symbol
        assert len(body["strategies"]) == 1
        assert body["strategies"][0]["name"] == DummyInspectorStrategy.name
        assert body["strategies"][0]["algorithm_summary"]
        assert body["strategies"][0]["settings_schema"][0]["name"] == "threshold"
        assert body["strategies"][0]["latest_signal"]["signal_type"] == "BUY"
    finally:
        agent_module.STRATEGY_REGISTRY.pop(DummyInspectorStrategy.name, None)
        reset_managers()


def test_agent_strategy_parameters_update_changes_runtime_params() -> None:
    reset_managers()
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    agent_module.STRATEGY_REGISTRY[DummyInspectorStrategy.name] = DummyInspectorStrategy
    symbol = "NSE:NIFTY50-INDEX"
    _seed_cache(symbol, "5", bars=140)
    _seed_cache(symbol, "60", bars=60)
    _seed_cache(symbol, "D", bars=40)

    try:
        agent = agent_module.get_trading_agent()

        async def fake_options(*_args, **_kwargs):
            return _mock_options_analytics()

        agent.get_options_trade_analytics = fake_options  # type: ignore[method-assign]
        update_resp = client.post(
            f"/api/v1/agent/strategy-parameters/{DummyInspectorStrategy.name}",
            json={"params": {"threshold": 42.5, "allow_short": True}},
        )
        assert update_resp.status_code == 200, update_resp.text
        update_body = update_resp.json()
        assert update_body["success"] is True
        assert update_body["params"]["threshold"] == 42.5
        assert update_body["params"]["allow_short"] is True

        inspect_resp = client.get(
            "/api/v1/agent/inspector",
            params={
                "symbol": symbol,
                "timeframe": "5",
                "lookback_bars": 120,
                "strategies": DummyInspectorStrategy.name,
            },
        )
        assert inspect_resp.status_code == 200, inspect_resp.text
        inspect_body = inspect_resp.json()
        assert inspect_body["strategies"][0]["params"]["threshold"] == 42.5
        assert inspect_body["strategies"][0]["params"]["allow_short"] is True
    finally:
        agent_module.STRATEGY_REGISTRY.pop(DummyInspectorStrategy.name, None)
        reset_managers()


def test_agent_inspector_falls_back_to_last_available_timeframe() -> None:
    reset_managers()
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    agent_module.STRATEGY_REGISTRY[DummyInspectorStrategy.name] = DummyInspectorStrategy
    symbol = "NSE:NIFTY50-INDEX"
    _seed_cache(symbol, "5", bars=140)
    _seed_cache(symbol, "60", bars=60)
    _seed_cache(symbol, "D", bars=40)

    try:
        agent = agent_module.get_trading_agent()

        async def fake_options(*_args, **_kwargs):
            return _mock_options_analytics()

        agent.get_options_trade_analytics = fake_options  # type: ignore[method-assign]
        resp = client.get(
            "/api/v1/agent/inspector",
            params={
                "symbol": symbol,
                "timeframe": "3",
                "lookback_bars": 120,
                "strategies": DummyInspectorStrategy.name,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["timeframe"] == "3"
        assert body["resolved_timeframe"] == "5"
        assert body["data_source"]["fallback_used"] is True
        assert body["data_source"]["resolved_timeframe"] == "5"
        assert body["strategies"][0]["timeframe"] == "5"
    finally:
        agent_module.STRATEGY_REGISTRY.pop(DummyInspectorStrategy.name, None)
        reset_managers()
