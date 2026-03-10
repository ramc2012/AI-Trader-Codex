"""Session-aware trading agent behavior."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from src.agent.trading_agent import AgentConfig, OptionExitPlan, TradingAgent
from src.config.market_hours import IST
from src.execution.order_manager import OrderSide
from src.execution.order_manager import OrderStatus
from src.execution.position_manager import PositionManager, PositionSide
from src.strategies.base import Signal, SignalStrength, SignalType


def _build_agent(config: AgentConfig) -> TradingAgent:
    return TradingAgent(
        config=config,
        strategy_executor=MagicMock(),
        order_manager=MagicMock(),
        position_manager=MagicMock(),
        risk_manager=MagicMock(),
        event_bus=MagicMock(),
        fyers_client=MagicMock(),
    )


def _frame_from_prices(prices: list[float]) -> pd.DataFrame:
    rows = []
    start = datetime(2026, 3, 10, 9, 15, tzinfo=IST)
    for index, price in enumerate(prices):
        rows.append(
            {
                "timestamp": start + timedelta(minutes=5 * index),
                "open": price,
                "high": price * 1.002,
                "low": price * 0.998,
                "close": price,
                "volume": 1000 + index,
            }
        )
    return pd.DataFrame(rows)


def test_active_symbols_when_nse_closed_and_us_open() -> None:
    agent = _build_agent(
        AgentConfig(
            symbols=["NSE:NIFTY50-INDEX"],
            us_symbols=["US:SPY", "US:QQQ"],
            crypto_symbols=["CRYPTO:BTCUSDT"],
        )
    )
    active = agent._resolve_active_symbols({"nse": False, "us": True, "crypto": True})
    assert active == ["US:SPY", "US:QQQ", "CRYPTO:BTCUSDT"]


def test_active_symbols_respect_market_toggles() -> None:
    agent = _build_agent(
        AgentConfig(
            symbols=["NSE:NIFTY50-INDEX"],
            us_symbols=["US:SPY"],
            crypto_symbols=["CRYPTO:BTCUSDT"],
            trade_us_when_open=False,
            trade_crypto_24x7=False,
        )
    )
    active = agent._resolve_active_symbols({"nse": False, "us": True, "crypto": True})
    assert active == []


def test_us_positions_force_eod_exit_near_close() -> None:
    agent = _build_agent(AgentConfig())
    # 2026-03-05 02:28 IST == 2026-03-04 15:58 US/Eastern.
    now_ist = datetime(2026, 3, 5, 2, 28, tzinfo=IST)
    assert agent._should_force_eod_exit("US:SPY", now_ist, buffer_minutes=5) is True


def test_crypto_positions_skip_eod_exit() -> None:
    agent = _build_agent(AgentConfig())
    now_ist = datetime(2026, 3, 5, 2, 28, tzinfo=IST)
    assert agent._should_force_eod_exit("CRYPTO:BTCUSDT", now_ist, buffer_minutes=5) is False


def test_agent_status_exposes_market_and_strategy_stats() -> None:
    config = AgentConfig()
    order_manager = MagicMock()
    order_manager.get_all_orders.return_value = []
    position_manager = MagicMock()
    position_manager.get_portfolio_summary.return_value = {"position_count": 0}
    position_manager.get_all_positions.return_value = []
    position_manager.get_closed_trades.return_value = []
    position_manager.get_position_views.return_value = []
    position_manager.total_realized_pnl = 0.0
    risk_manager = MagicMock()
    risk_manager.get_risk_summary.return_value = {"total_pnl": 0.0, "total_trades": 0}
    risk_manager.emergency_stop = False

    agent = TradingAgent(
        config=config,
        strategy_executor=MagicMock(),
        order_manager=order_manager,
        position_manager=position_manager,
        risk_manager=risk_manager,
        event_bus=MagicMock(),
        fyers_client=MagicMock(),
    )
    status = agent.get_status()
    assert "market_stats" in status
    assert "strategy_stats" in status
    assert "capital_allocations" in status
    assert "strategy_market_stats" in status
    assert "strategy_instrument_stats" in status
    assert set(status["market_stats"].keys()) >= {"NSE", "US", "CRYPTO"}
    assert "MP_OrderFlow_Breakout" in status["strategy_stats"]


def test_agent_status_counts_open_entries_as_trades() -> None:
    config = AgentConfig()
    order_manager = MagicMock()
    order_manager.get_all_orders.return_value = []

    open_position = MagicMock()
    open_position.symbol = "CRYPTO:BTCUSDT"
    open_position.strategy_tag = "EMA_Crossover"
    open_position.current_price = 100.0
    open_position.avg_price = 90.0
    open_position.quantity = 10
    open_position.market_value = 1000.0
    open_position.unrealized_pnl = 100.0

    position_manager = MagicMock()
    position_manager.get_portfolio_summary.return_value = {"position_count": 1}
    position_manager.get_all_positions.return_value = [open_position]
    position_manager.get_closed_trades.return_value = [
        {"symbol": "CRYPTO:BTCUSDT", "strategy_tag": "EMA_Crossover", "pnl": 10.0},
        {"symbol": "CRYPTO:BTCUSDT", "strategy_tag": "EMA_Crossover", "pnl": -5.0},
    ]
    position_manager.get_position_views.return_value = [open_position]
    position_manager.get_positions_by_tag.return_value = [open_position]
    position_manager.total_realized_pnl = 0.0

    risk_manager = MagicMock()
    risk_manager.get_risk_summary.return_value = {"total_pnl": 0.0, "total_trades": 0}
    risk_manager.emergency_stop = False

    agent = TradingAgent(
        config=config,
        strategy_executor=MagicMock(),
        order_manager=order_manager,
        position_manager=position_manager,
        risk_manager=risk_manager,
        event_bus=MagicMock(),
        fyers_client=MagicMock(),
    )
    status = agent.get_status()
    assert status["positions_count"] == 1
    assert status["total_trades"] == 3


def test_synthetic_option_fallback_is_disabled() -> None:
    agent = _build_agent(AgentConfig(paper_mode=True))
    assert not hasattr(agent, "_build_paper_index_option_fallback")


def test_strategy_budget_limits_split_capital_evenly() -> None:
    config = AgentConfig(
        capital=250000.0,
        strategies=["EMA_Crossover", "RSI_Reversal", "Supertrend_Breakout", "MP_OrderFlow_Breakout"],
        strategy_max_concurrent_positions=4,
    )
    agent = _build_agent(config)
    agent.risk_manager.config.capital = 250000.0
    agent.executor.get_strategy_states.return_value = {}

    open_view = MagicMock()
    open_view.symbol = "US:AAPL260313C00190000"
    open_view.quantity = 100
    open_view.current_price = 10.0
    open_view.avg_price = 9.5
    agent.position_manager.get_positions_by_tag.return_value = [open_view]

    budget = agent._strategy_budget_limits("EMA_Crossover", "US:AAPL260313C00190000")

    assert budget["strategy_budget"] == 62500.0
    assert budget["per_trade_budget"] == 15625.0
    assert budget["remaining_budget"] == 61500.0
    assert budget["remaining_trade_budget"] == 14625.0
    assert budget["available_slots"] == 3.0


@pytest.mark.asyncio
async def test_rank_execution_timeframes_prefers_slower_frames_in_trend() -> None:
    agent = _build_agent(AgentConfig(execution_timeframes=["3", "5", "15"]))
    agent._fetch_market_data = AsyncMock(return_value=_frame_from_prices([100 + i for i in range(30)]))

    ranked = await agent._rank_execution_timeframes("US:SPY", ["3", "5", "15"])

    assert ranked == ["15", "5"]


@pytest.mark.asyncio
async def test_rank_execution_timeframes_prefers_faster_frames_in_bracket() -> None:
    agent = _build_agent(AgentConfig(execution_timeframes=["3", "5", "15"]))
    prices = [100.0, 100.3, 99.9, 100.2, 99.8, 100.1] * 5
    agent._fetch_market_data = AsyncMock(return_value=_frame_from_prices(prices))

    ranked = await agent._rank_execution_timeframes("US:SPY", ["3", "5", "15"])

    assert ranked == ["3", "5"]


def test_signal_priority_score_penalizes_small_timeframe_in_trend() -> None:
    agent = _build_agent(AgentConfig())
    signal = Signal(
        timestamp=datetime.now(tz=IST),
        symbol="US:SPY",
        signal_type=SignalType.BUY,
        strength=SignalStrength.MODERATE,
        price=100.0,
        strategy_name="EMA_Crossover",
        metadata={
            "conviction_score": 74.0,
            "reference_timeframe_bias": {"bullish_votes": 2, "bearish_votes": 0},
        },
    )
    regime = {"regime": "trending", "trend": "bullish"}

    score_15 = agent._signal_priority_score("EMA_Crossover", signal, "15", regime)
    score_3 = agent._signal_priority_score("EMA_Crossover", signal, "3", regime)

    assert score_15 > score_3


def test_resolve_trade_budget_cap_can_borrow_unused_global_capital_for_high_priority() -> None:
    agent = _build_agent(AgentConfig(capital=200000.0))
    agent.position_manager.get_all_positions.return_value = []

    resolved = agent._resolve_trade_budget_cap(
        {
            "market_budget": 250000.0,
            "market_remaining_budget": 250000.0,
            "max_instrument_budget": 62500.0,
            "strategy_budget": 25000.0,
            "per_trade_budget": 6250.0,
            "remaining_budget": 0.0,
            "remaining_trade_budget": 0.0,
            "open_positions": 4.0,
            "available_slots": 0.0,
        },
        priority_score=82.0,
        entry_price=100.0,
        lot_size=1,
        market="NSE",
    )

    assert resolved["budget_cap"] > 0.0
    assert resolved["allow_slot_override"] == 1.0


@pytest.mark.asyncio
async def test_resolve_liquidity_quantity_cap_uses_option_volume_and_oi() -> None:
    agent = _build_agent(AgentConfig())

    result = await agent._resolve_liquidity_quantity_cap(
        execution_symbol="US:SPY260313C00600000",
        underlying_symbol="US:SPY",
        execution_market="US",
        execution_timeframe="15",
        side=OrderSide.BUY,
        lot_size=1,
        options_analytics={
            "selected_contract": {
                "symbol": "US:SPY260313C00600000",
                "volume": 1200,
                "oi": 5000,
                "bid": 4.8,
                "ask": 5.0,
            }
        },
    )

    assert result["volume_cap"] == 60
    assert result["oi_cap"] == 100
    assert result["max_quantity"] == 60


@pytest.mark.asyncio
async def test_resolve_liquidity_quantity_cap_uses_visible_orderbook_for_nse() -> None:
    fyers_client = MagicMock()
    fyers_client.get_market_depth.return_value = {
        "s": "ok",
        "d": {
            "NSE:NIFTY2631322500CE": {
                "ask": [
                    {"price": 100.0, "qty": 80},
                    {"price": 100.5, "qty": 70},
                    {"price": 101.0, "qty": 50},
                ]
            }
        },
    }
    agent = TradingAgent(
        config=AgentConfig(),
        strategy_executor=MagicMock(),
        order_manager=MagicMock(),
        position_manager=MagicMock(),
        risk_manager=MagicMock(),
        event_bus=MagicMock(),
        fyers_client=fyers_client,
    )

    result = await agent._resolve_liquidity_quantity_cap(
        execution_symbol="NSE:NIFTY2631322500CE",
        underlying_symbol="NSE:NIFTY50-INDEX",
        execution_market="NSE",
        execution_timeframe="5",
        side=OrderSide.BUY,
        lot_size=25,
        options_analytics=None,
    )

    assert result["visible_orderbook_qty"] == 200
    assert result["orderbook_cap"] == 50
    assert result["max_quantity"] == 50


@pytest.mark.asyncio
async def test_close_position_removes_stale_strategy_plan_without_crashing() -> None:
    position_manager = PositionManager()
    position_manager.open_position(
        symbol="CRYPTO:XRPUSDT",
        quantity=16,
        side=PositionSide.LONG,
        price=1.0,
        strategy_tag="EMA_Crossover",
    )

    order_manager = MagicMock()
    event_bus = MagicMock()
    event_bus.emit = AsyncMock()
    risk_manager = MagicMock()

    agent = TradingAgent(
        config=AgentConfig(),
        strategy_executor=MagicMock(),
        order_manager=order_manager,
        position_manager=position_manager,
        risk_manager=risk_manager,
        event_bus=event_bus,
        fyers_client=MagicMock(),
    )
    plan = OptionExitPlan(
        symbol="CRYPTO:XRPUSDT",
        underlying_symbol="CRYPTO:XRPUSDT",
        strategy="RSI_Reversal",
        quantity=16,
        execution_timeframe="5",
        entry_price=1.0,
        stop_loss=0.9,
        target=1.1,
        opened_at=datetime.now(tz=IST),
        time_exit_at=datetime.now(tz=IST) + timedelta(minutes=10),
    )
    agent._option_exit_plans["CRYPTO:XRPUSDT"] = {plan.strategy: plan}

    await agent._close_position(
        symbol="CRYPTO:XRPUSDT",
        short_name="XRPUSDT",
        current_price=1.05,
        reason="time_exit",
        plan=plan,
    )

    order_manager.place_order.assert_not_called()
    assert agent._symbol_exit_plans("CRYPTO:XRPUSDT") == []
    assert position_manager.get_position("CRYPTO:XRPUSDT") is not None


@pytest.mark.asyncio
async def test_close_position_caps_exit_quantity_to_strategy_slice() -> None:
    position_manager = PositionManager()
    position_manager.open_position(
        symbol="CRYPTO:ADAUSDT",
        quantity=10,
        side=PositionSide.LONG,
        price=1.0,
        strategy_tag="EMA_Crossover",
    )
    position_manager.open_position(
        symbol="CRYPTO:ADAUSDT",
        quantity=10,
        side=PositionSide.LONG,
        price=1.1,
        strategy_tag="RSI_Reversal",
    )

    placed_order = MagicMock()
    placed_order.status = OrderStatus.FILLED
    placed_order.fill_price = 1.2
    order_manager = MagicMock()
    order_manager.place_order.return_value = MagicMock(success=True, order=placed_order)

    event_bus = MagicMock()
    event_bus.emit = AsyncMock()
    risk_manager = MagicMock()

    agent = TradingAgent(
        config=AgentConfig(),
        strategy_executor=MagicMock(),
        order_manager=order_manager,
        position_manager=position_manager,
        risk_manager=risk_manager,
        event_bus=event_bus,
        fyers_client=MagicMock(),
    )
    plan = OptionExitPlan(
        symbol="CRYPTO:ADAUSDT",
        underlying_symbol="CRYPTO:ADAUSDT",
        strategy="EMA_Crossover",
        quantity=20,
        execution_timeframe="5",
        entry_price=1.0,
        stop_loss=0.9,
        target=1.2,
        opened_at=datetime.now(tz=IST),
        time_exit_at=datetime.now(tz=IST) + timedelta(minutes=10),
    )
    agent._option_exit_plans["CRYPTO:ADAUSDT"] = {plan.strategy: plan}

    await agent._close_position(
        symbol="CRYPTO:ADAUSDT",
        short_name="ADAUSDT",
        current_price=1.2,
        reason="target",
        plan=plan,
    )

    assert order_manager.place_order.call_args.args[0].quantity == 10
    assert position_manager.get_position_views(symbol="CRYPTO:ADAUSDT", strategy_tag="EMA_Crossover") == []
    remaining_views = position_manager.get_position_views(symbol="CRYPTO:ADAUSDT", strategy_tag="RSI_Reversal")
    assert len(remaining_views) == 1
    assert remaining_views[0].quantity == 10
