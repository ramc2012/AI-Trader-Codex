from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

from src.agent.trading_agent import AgentConfig, TradingAgent
from src.config.market_hours import IST
from src.strategies.base import Signal, SignalStrength, SignalType
from src.strategies.directional.mp_orderflow_strategy import MarketProfileOrderFlowStrategy


def _build_agent(config: AgentConfig | None = None) -> TradingAgent:
    return TradingAgent(
        config=config or AgentConfig(),
        strategy_executor=MagicMock(),
        order_manager=MagicMock(),
        position_manager=MagicMock(),
        risk_manager=MagicMock(),
        event_bus=MagicMock(),
        fyers_client=MagicMock(),
    )


def _mp_frame(symbol: str) -> pd.DataFrame:
    start = datetime(2026, 3, 8, 9, 15, tzinfo=IST)
    rows: list[dict[str, object]] = []
    close = 100.0
    for idx in range(90):
        if idx >= 87:
            close = [103.95, 104.02, 104.55][idx - 87]
        else:
            close += 0.045
        rows.append(
            {
                "timestamp": start + timedelta(minutes=5 * idx),
                "open": close - 0.22,
                "high": close + 0.28,
                "low": close - 0.34,
                "close": close,
                "volume": (
                    1_100 + (idx * 3)
                    if idx < 85
                    else [1_850, 1_950, 2_050, 2_200, 4_400][idx - 85]
                ),
                "symbol": symbol,
            }
        )
    return pd.DataFrame(rows)


def _volatile_frame(symbol: str) -> pd.DataFrame:
    start = datetime(2026, 3, 8, 0, 0, tzinfo=IST)
    rows: list[dict[str, object]] = []
    close = 100.0
    for idx in range(40):
        close = close * (1.018 if idx % 2 == 0 else 0.987)
        rows.append(
            {
                "timestamp": start + timedelta(minutes=15 * idx),
                "open": close * 0.992,
                "high": close * 1.01,
                "low": close * 0.988,
                "close": close,
                "volume": 2_000 + idx * 40,
                "symbol": symbol,
            }
        )
    return pd.DataFrame(rows)


def test_mp_orderflow_strategy_emits_crypto_metadata() -> None:
    strategy = MarketProfileOrderFlowStrategy(profile_lookback=60, delta_lookback=5)
    data = _mp_frame("CRYPTO:BTCUSDT")

    with patch(
        "src.strategies.directional.mp_orderflow_strategy.compute_tpo_profile",
        return_value=SimpleNamespace(poc=103.2, vah=104.0, val=101.8),
    ):
        with patch.object(
            strategy,
            "_orderflow_summary",
            return_value={
                "avg_buying_pressure": 0.64,
                "imbalance_ratio": 0.19,
                "latest_delta": 2_400.0,
                "delta_trend": "up",
                "stacked_levels": 6,
            },
        ):
            signals = strategy.generate_signals(data)

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal_type == SignalType.BUY
    assert signal.metadata["market"] == "CRYPTO"
    assert signal.metadata["conviction_score"] >= 64.0
    assert signal.metadata["position_size_multiplier"] >= 1.0
    assert signal.metadata["adaptive_risk_reward"] >= 1.4
    assert signal.metadata["orderflow_summary"]["delta_trend"] == "up"


def test_trading_agent_adapts_size_and_timeframe_for_mp_orderflow_conditions() -> None:
    agent = _build_agent()
    signal = Signal(
        timestamp=datetime(2026, 3, 8, 12, 0, tzinfo=IST),
        symbol="CRYPTO:BTCUSDT",
        signal_type=SignalType.BUY,
        strength=SignalStrength.STRONG,
        price=104.55,
        stop_loss=102.8,
        target=108.9,
        strategy_name="MP_OrderFlow_Breakout",
        metadata={
            "conviction_score": 82.0,
            "position_size_multiplier": 1.15,
            "reference_timeframe_bias": {"bullish_votes": 2, "bearish_votes": 0},
            "execution_timeframe": "15",
        },
    )

    strong_mult = agent._market_condition_size_multiplier(signal, "15")
    assert strong_mult > 1.2

    volatile = _volatile_frame("CRYPTO:BTCUSDT")

    async def fake_fetch_market_data(symbol: str, timeframe: str):
        return volatile

    agent._fetch_market_data = fake_fetch_market_data  # type: ignore[method-assign]
    ranked = asyncio.run(agent._rank_execution_timeframes("CRYPTO:BTCUSDT", ["3", "5", "15"]))
    assert ranked == ["15", "5", "3"]
