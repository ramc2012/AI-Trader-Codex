"""Session-aware trading agent behavior."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from src.agent.trading_agent import AgentConfig, TradingAgent
from src.config.market_hours import IST


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
    position_manager.total_realized_pnl = 0.0

    agent = TradingAgent(
        config=config,
        strategy_executor=MagicMock(),
        order_manager=order_manager,
        position_manager=position_manager,
        risk_manager=MagicMock(),
        event_bus=MagicMock(),
        fyers_client=MagicMock(),
    )
    status = agent.get_status()
    assert "market_stats" in status
    assert "strategy_stats" in status
    assert set(status["market_stats"].keys()) >= {"NSE", "US", "CRYPTO"}
    assert "MP_OrderFlow_Breakout" in status["strategy_stats"]


def test_synthetic_option_fallback_is_disabled() -> None:
    agent = _build_agent(AgentConfig(paper_mode=True))
    assert not hasattr(agent, "_build_paper_index_option_fallback")
