"""Session-aware trading agent behavior."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from src.agent.trading_agent import (
    AgentConfig,
    OptionContract,
    OptionExitPlan,
    PendingLiveEntryOrder,
    PendingLiveEntrySubmission,
    TradingAgent,
)
from src.agent.events import AgentEventType
from src.agent.trading_agent import AgentState
from src.config.market_hours import IST
from src.data.live.tick_stream import TickStreamBroker
from src.execution.order_manager import BrokerOrderUpdateResult, Order, OrderManager, OrderSide, OrderStatus, OrderType
from src.execution.order_submitter import OrderSubmitter
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


def _frame_with_end(end: datetime, minutes: int = 3, bars: int = 20, price: float = 100.0) -> pd.DataFrame:
    rows = []
    for index in range(bars):
        ts = end - timedelta(minutes=minutes * (bars - index - 1))
        rows.append(
            {
                "timestamp": ts,
                "open": price,
                "high": price * 1.002,
                "low": price * 0.998,
                "close": price,
                "volume": 1000 + index,
                "symbol": "NSE:NIFTY50-INDEX",
            }
        )
    return pd.DataFrame(rows)


def _recent_frame_from_prices(
    prices: list[float],
    *,
    minutes: int,
    symbol: str,
) -> pd.DataFrame:
    rows = []
    end = datetime.now(tz=IST).replace(second=0, microsecond=0)
    for index, price in enumerate(prices):
        ts = end - timedelta(minutes=minutes * (len(prices) - index - 1))
        rows.append(
            {
                "timestamp": ts,
                "open": price,
                "high": price * 1.002,
                "low": price * 0.998,
                "close": price,
                "volume": 1000 + index,
                "symbol": symbol,
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


def test_profile_swing_strategies_are_allowed_for_crypto() -> None:
    agent = _build_agent(AgentConfig())

    assert agent._is_strategy_allowed_for_market("Profile_Swing_Radar", "CRYPTO") is True
    assert agent._is_strategy_allowed_for_market("Profile_AI_Swing_Radar", "CRYPTO") is True


def test_learning_signal_policy_tightens_underperforming_short_term_strategy() -> None:
    agent = _build_agent(AgentConfig())
    agent._strategy_perf_tracker = MagicMock()
    agent._strategy_perf_tracker.get_strategy_snapshot.return_value = {
        "trade_count": 14,
        "reward_ema": -1.4,
        "rolling_sharpe": -0.2,
        "win_rate": 0.41,
        "enabled": True,
    }

    signal = Signal(
        timestamp=datetime.now(tz=IST),
        symbol="CRYPTO:BTCUSDT",
        signal_type=SignalType.BUY,
        strength=SignalStrength.WEAK,
        price=100.0,
        stop_loss=95.0,
        target=110.0,
        strategy_name="Profile_Swing_Radar",
        metadata={},
    )

    policy = agent._learning_signal_policy("Profile_Swing_Radar", "CRYPTO", "5", signal)

    assert policy["priority_delta"] > 0
    assert policy["min_strength"] == SignalStrength.MODERATE.value


@pytest.mark.asyncio
async def test_confirm_reference_timeframes_prefers_weighted_daily_bias() -> None:
    agent = _build_agent(AgentConfig(reference_timeframes=["60", "D"]))
    hourly_frame = _recent_frame_from_prices(
        [120.0, 119.8, 119.5, 119.2, 118.9, 118.6, 118.4, 118.2],
        minutes=60,
        symbol="US:NVDA",
    )
    daily_frame = _recent_frame_from_prices(
        [100.0 + (index * 1.8) for index in range(24)],
        minutes=24 * 60,
        symbol="US:NVDA",
    )

    async def _fake_fetch(symbol: str, timeframe: str, live_only: bool = False):  # noqa: ARG001
        if symbol == "US:NVDA" and timeframe == "60":
            return hourly_frame
        if symbol == "US:NVDA" and timeframe == "D":
            return daily_frame
        raise AssertionError(f"unexpected fetch: {symbol} {timeframe}")

    agent._fetch_market_data = AsyncMock(side_effect=_fake_fetch)

    confirmed, meta = await agent._confirm_reference_timeframes("US:NVDA", SignalType.BUY, live_only=True)

    assert confirmed is True
    assert meta["bullish_votes"] == 1
    assert meta["bearish_votes"] == 1
    assert meta["weighted_bullish_votes"] > meta["weighted_bearish_votes"]


@pytest.mark.asyncio
async def test_benchmark_alignment_profile_rewards_relative_strength() -> None:
    agent = _build_agent(AgentConfig())
    execution_frame = _recent_frame_from_prices(
        [200.0 + index for index in range(20)],
        minutes=15,
        symbol="US:NVDA",
    )
    symbol_daily = _recent_frame_from_prices(
        [100.0 + (index * 2.0) for index in range(30)],
        minutes=24 * 60,
        symbol="US:NVDA",
    )
    benchmark_daily = _recent_frame_from_prices(
        [100.0 + (index * 0.5) for index in range(30)],
        minutes=24 * 60,
        symbol="US:SPY",
    )

    async def _fake_fetch(symbol: str, timeframe: str, live_only: bool = False):  # noqa: ARG001
        if symbol == "US:NVDA" and timeframe == "D":
            return symbol_daily
        if symbol == "US:SPY" and timeframe == "D":
            return benchmark_daily
        raise AssertionError(f"unexpected fetch: {symbol} {timeframe}")

    agent._fetch_market_data = AsyncMock(side_effect=_fake_fetch)

    profile = await agent._benchmark_alignment_profile(
        symbol="US:NVDA",
        signal_type=SignalType.BUY,
        execution_timeframe="15",
        execution_frame=execution_frame,
        live_only=True,
    )

    assert profile["available"] is True
    assert profile["alignment"] == "aligned"
    assert profile["relative_strength_20d"] > 0
    assert profile["score"] > 0


def test_recent_trade_outcome_policy_penalizes_fresh_option_loss_streak() -> None:
    agent = _build_agent(AgentConfig())
    agent.position_manager.get_closed_trades.return_value = [
        {
            "symbol": "NSE:NIFTY26MAR22500CE",
            "strategy_tag": "EMA_Crossover",
            "pnl": -2500.0,
            "quantity": 25,
            "entry_price": 200.0,
            "closed_at": datetime.now(tz=IST) - timedelta(minutes=90),
        },
        {
            "symbol": "NSE:NIFTY26MAR22400PE",
            "strategy_tag": "EMA_Crossover",
            "pnl": -1500.0,
            "quantity": 25,
            "entry_price": 180.0,
            "closed_at": datetime.now(tz=IST) - timedelta(minutes=30),
        },
    ]

    recent_policy = agent._recent_trade_outcome_policy("NSE:NIFTY50-INDEX", "EMA_Crossover")
    signal = Signal(
        timestamp=datetime.now(tz=IST),
        symbol="NSE:NIFTY50-INDEX",
        signal_type=SignalType.BUY,
        strength=SignalStrength.MODERATE,
        price=100.0,
        stop_loss=95.0,
        target=110.0,
        strategy_name="EMA_Crossover",
        metadata={"recent_trade_memory": recent_policy},
    )
    learning_policy = agent._learning_signal_policy("EMA_Crossover", "NSE", "5", signal)

    assert recent_policy["symbol_identity"] == "NSE:NIFTY"
    assert recent_policy["loss_streak"] == 2
    assert recent_policy["priority_delta"] >= 6.0
    assert learning_policy["min_strength"] == SignalStrength.STRONG.value


def test_apply_candidate_consensus_rewards_support_and_penalizes_conflict() -> None:
    agent = _build_agent(AgentConfig())
    buy_primary = Signal(
        timestamp=datetime.now(tz=IST),
        symbol="CRYPTO:BTCUSDT",
        signal_type=SignalType.BUY,
        strength=SignalStrength.MODERATE,
        price=100.0,
        strategy_name="EMA_Crossover",
        metadata={},
    )
    buy_secondary = Signal(
        timestamp=datetime.now(tz=IST),
        symbol="CRYPTO:BTCUSDT",
        signal_type=SignalType.BUY,
        strength=SignalStrength.MODERATE,
        price=100.0,
        strategy_name="RSI_Reversal",
        metadata={},
    )
    sell_conflict = Signal(
        timestamp=datetime.now(tz=IST),
        symbol="CRYPTO:BTCUSDT",
        signal_type=SignalType.SELL,
        strength=SignalStrength.MODERATE,
        price=100.0,
        strategy_name="Supertrend_Breakout",
        metadata={},
    )
    candidates = [
        {"signal": buy_primary, "strategy": "EMA_Crossover", "timeframe": "15", "priority_score": 60.0},
        {"signal": buy_secondary, "strategy": "RSI_Reversal", "timeframe": "5", "priority_score": 61.0},
        {"signal": sell_conflict, "strategy": "Supertrend_Breakout", "timeframe": "15", "priority_score": 60.0},
    ]

    agent._apply_candidate_consensus(candidates)

    assert candidates[0]["priority_score"] > 60.0
    assert candidates[1]["priority_score"] > 61.0
    assert candidates[2]["priority_score"] < 60.0
    assert buy_primary.metadata["consensus_context"]["supporting_candidates"] == 1
    assert sell_conflict.metadata["consensus_context"]["opposing_candidates"] == 2


def test_market_condition_size_multiplier_uses_execution_risk_reward_profile() -> None:
    agent = _build_agent(AgentConfig())
    high_rr_signal = Signal(
        timestamp=datetime.now(tz=IST),
        symbol="US:NVDA",
        signal_type=SignalType.BUY,
        strength=SignalStrength.MODERATE,
        price=100.0,
        strategy_name="EMA_Crossover",
        metadata={"execution_risk_reward_profile": {"valid": True, "ratio": 2.4}},
    )
    low_rr_signal = Signal(
        timestamp=datetime.now(tz=IST),
        symbol="US:NVDA",
        signal_type=SignalType.BUY,
        strength=SignalStrength.MODERATE,
        price=100.0,
        strategy_name="EMA_Crossover",
        metadata={"execution_risk_reward_profile": {"valid": True, "ratio": 0.9}},
    )

    high_rr = agent._market_condition_size_multiplier(high_rr_signal, "15")
    low_rr = agent._market_condition_size_multiplier(low_rr_signal, "15")

    assert high_rr > low_rr


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
    assert "strategy_capital_bucket_enabled" in status
    assert "strategy_max_concurrent_positions" in status
    assert "strategy_market_stats" in status
    assert "strategy_instrument_stats" in status
    assert "online_learning_active" in status
    assert "online_learning_stats" in status
    assert "strategy_reward_ema_by_market" in status
    assert "execution_backend" in status
    assert "execution_signal_lane" in status
    assert "execution_transport" in status
    assert "event_driven_enabled" in status
    assert "event_driven_markets" in status
    assert "streaming_backends" in status
    assert "analytics_backends" in status
    assert "execution_latency" in status
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


def test_coerce_ist_timestamp_treats_naive_values_as_utc() -> None:
    agent = _build_agent(AgentConfig())

    ts = agent._coerce_ist_timestamp(datetime(2026, 3, 11, 9, 55))

    assert ts is not None
    assert ts.tzinfo == IST
    assert ts.hour == 15
    assert ts.minute == 25


def test_market_open_position_count_is_scoped_per_market() -> None:
    agent = _build_agent(AgentConfig())
    us_position = MagicMock()
    us_position.symbol = "US:SPY260313C00600000"
    us_position.quantity = 100
    crypto_position = MagicMock()
    crypto_position.symbol = "CRYPTO:BTCUSDT"
    crypto_position.quantity = 1
    nse_position = MagicMock()
    nse_position.symbol = "NSE:NIFTY50-INDEX"
    nse_position.quantity = 75
    agent.position_manager.get_all_positions.return_value = [us_position, crypto_position, nse_position]

    assert agent._market_open_position_count("NSE") == 1
    assert agent._market_open_position_count("US") == 1
    assert agent._market_open_position_count("CRYPTO") == 1


def test_crypto_swing_timeframe_is_added_only_for_crypto_market() -> None:
    agent = _build_agent(
        AgentConfig(
            strategies=["Crypto_Swing_Radar", "Fractal_Profile_Breakout"],
            execution_timeframes=["3", "5", "15"],
        )
    )

    assert "240" in agent._execution_timeframes_for_symbol("CRYPTO:BTCUSDT")
    assert "240" not in agent._execution_timeframes_for_symbol("NSE:NIFTY50-INDEX")


def test_crypto_market_disable_map_blocks_bootstrap_and_ema() -> None:
    agent = _build_agent(AgentConfig())

    assert agent._is_strategy_allowed_for_market("Bootstrap_Explorer", "CRYPTO") is False
    assert agent._is_strategy_allowed_for_market("EMA_Crossover", "CRYPTO") is False
    assert agent._is_strategy_allowed_for_market("Fractal_Profile_Breakout", "CRYPTO") is True
    assert agent._is_strategy_allowed_for_market("MP_OrderFlow_Breakout", "CRYPTO") is True


@pytest.mark.asyncio
async def test_init_online_learning_does_not_require_ml_ensemble(tmp_path) -> None:
    agent = _build_agent(AgentConfig(strategies=["EMA_Crossover"]))
    agent.executor._strategies = {}

    original_settings = agent._init_online_learning.__globals__["get_settings"]

    class _Settings:
        data_dir = str(tmp_path)

    agent._init_online_learning.__globals__["get_settings"] = lambda: _Settings()
    try:
        await agent._init_online_learning()
    finally:
        agent._init_online_learning.__globals__["get_settings"] = original_settings

    assert agent._online_learning_engine is not None


@pytest.mark.asyncio
async def test_start_sets_error_state_when_online_learning_init_fails() -> None:
    config = AgentConfig()
    event_bus = MagicMock()
    event_bus.emit = AsyncMock()
    executor = MagicMock()
    order_manager = MagicMock()
    position_manager = MagicMock()
    risk_manager = MagicMock()
    risk_manager.emergency_stop = False

    agent = TradingAgent(
        config=config,
        strategy_executor=executor,
        order_manager=order_manager,
        position_manager=position_manager,
        risk_manager=risk_manager,
        event_bus=event_bus,
        fyers_client=MagicMock(),
    )
    agent._init_online_learning = AsyncMock(side_effect=TypeError("boom"))

    with pytest.raises(TypeError, match="boom"):
        await agent.start()

    assert agent.state == AgentState.ERROR
    assert agent._error == "boom"
    executor.stop.assert_called_once()


def test_synthetic_option_fallback_is_disabled() -> None:
    agent = _build_agent(AgentConfig(paper_mode=True))
    assert not hasattr(agent, "_build_paper_index_option_fallback")


def test_strategy_budget_limits_split_capital_evenly() -> None:
    config = AgentConfig(
        capital=250000.0,
        strategies=["EMA_Crossover", "RSI_Reversal", "Supertrend_Breakout", "MP_OrderFlow_Breakout"],
        strategy_capital_bucket_enabled=True,
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


@pytest.mark.asyncio
async def test_fetch_market_data_prefers_fresh_db_frame_over_stale_cache(monkeypatch) -> None:
    agent = _build_agent(AgentConfig())
    stale_frame = _frame_with_end(datetime.now(tz=IST) - timedelta(days=2))
    fresh_frame = _frame_with_end(datetime.now(tz=IST) - timedelta(minutes=3), bars=180)

    class _Cache:
        def as_dataframe(self, symbol: str, timeframe: str, limit: int = 500) -> pd.DataFrame:
            return stale_frame.set_index("timestamp")

    monkeypatch.setattr("src.data.ohlc_cache.get_ohlc_cache", lambda: _Cache())
    agent._requires_live_bars = MagicMock(return_value=True)
    agent._fetch_database_market_data = AsyncMock(return_value=fresh_frame)
    agent._fetch_fyers_market_data = AsyncMock(return_value=None)

    frame = await agent._fetch_market_data("NSE:NIFTY50-INDEX", timeframe="3")

    assert frame is not None
    assert pd.to_datetime(frame["timestamp"].iloc[-1]) == pd.to_datetime(fresh_frame["timestamp"].iloc[-1])
    agent._fetch_fyers_market_data.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_market_data_prefers_newer_stale_db_frame_when_market_closed(monkeypatch) -> None:
    agent = _build_agent(AgentConfig())
    stale_cache_frame = _frame_with_end(datetime.now(tz=IST) - timedelta(days=2))
    newer_db_frame = _frame_with_end(datetime.now(tz=IST) - timedelta(hours=4))

    class _Cache:
        def as_dataframe(self, symbol: str, timeframe: str, limit: int = 500) -> pd.DataFrame:
            return stale_cache_frame.set_index("timestamp")

    monkeypatch.setattr("src.data.ohlc_cache.get_ohlc_cache", lambda: _Cache())
    agent._requires_live_bars = MagicMock(return_value=False)
    agent._fetch_database_market_data = AsyncMock(return_value=newer_db_frame)
    agent._fetch_fyers_market_data = AsyncMock(return_value=None)

    frame = await agent._fetch_market_data("NSE:NIFTY50-INDEX", timeframe="5")

    assert frame is not None
    assert pd.to_datetime(frame["timestamp"].iloc[-1]) == pd.to_datetime(newer_db_frame["timestamp"].iloc[-1])


@pytest.mark.asyncio
async def test_fetch_market_data_live_only_skips_db_and_rest_fallbacks(monkeypatch) -> None:
    agent = _build_agent(AgentConfig())
    stale_frame = _frame_with_end(datetime.now(tz=IST) - timedelta(days=2))

    class _Cache:
        def as_dataframe(self, symbol: str, timeframe: str, limit: int = 500) -> pd.DataFrame:
            return stale_frame.set_index("timestamp")

    monkeypatch.setattr("src.data.ohlc_cache.get_ohlc_cache", lambda: _Cache())
    agent._requires_live_bars = MagicMock(return_value=True)
    agent._fetch_database_market_data = AsyncMock(return_value=_frame_with_end(datetime.now(tz=IST)))
    agent._fetch_fyers_market_data = AsyncMock(return_value=_frame_with_end(datetime.now(tz=IST)))

    frame = await agent._fetch_market_data("NSE:NIFTY50-INDEX", timeframe="3", live_only=True)

    assert frame is None
    agent._fetch_database_market_data.assert_not_called()
    agent._fetch_fyers_market_data.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_market_data_ignores_shallow_fresh_crypto_cache(monkeypatch) -> None:
    agent = _build_agent(AgentConfig())
    shallow_frame = _frame_with_end(datetime.now(tz=IST) - timedelta(minutes=3), minutes=3, bars=2)
    shallow_frame["symbol"] = "CRYPTO:BTCUSDT"
    live_frame = _frame_with_end(datetime.now(tz=IST) - timedelta(minutes=3), minutes=3, bars=180)
    live_frame["symbol"] = "CRYPTO:BTCUSDT"

    class _Cache:
        def as_dataframe(self, symbol: str, timeframe: str, limit: int = 500) -> pd.DataFrame:
            return shallow_frame.set_index("timestamp")

    monkeypatch.setattr("src.data.ohlc_cache.get_ohlc_cache", lambda: _Cache())
    agent._requires_live_bars = MagicMock(return_value=True)
    agent._fetch_database_market_data = AsyncMock(return_value=None)
    agent._fetch_crypto_market_data = AsyncMock(return_value=live_frame)
    agent._fetch_fyers_market_data = AsyncMock(return_value=None)

    frame = await agent._fetch_market_data("CRYPTO:BTCUSDT", timeframe="3")

    assert frame is not None
    assert len(frame) == len(live_frame)
    agent._fetch_crypto_market_data.assert_awaited_once()


def test_periodic_scan_symbols_skip_event_driven_symbols() -> None:
    agent = _build_agent(AgentConfig(event_driven_execution_enabled=True))
    agent._candle_broker = MagicMock()
    agent._is_event_driven_symbol_eligible = MagicMock(
        side_effect=lambda symbol: symbol == "NSE:NIFTY50-INDEX"
    )

    filtered = agent._periodic_scan_symbols(["NSE:NIFTY50-INDEX", "CRYPTO:BTCUSDT"])

    assert filtered == ["CRYPTO:BTCUSDT"]


def test_periodic_scan_symbols_skip_execution_core_lane_symbols() -> None:
    agent = _build_agent(
        AgentConfig(
            event_driven_markets=["CRYPTO"],
            crypto_symbols=["CRYPTO:BTCUSDT"],
            us_symbols=["US:SPY"],
        )
    )
    agent._runtime_settings = SimpleNamespace(nats_enabled=True)
    agent._execution_core_backend = "rust"

    filtered = agent._periodic_scan_symbols(["CRYPTO:BTCUSDT", "US:SPY"])

    assert filtered == ["US:SPY"]


def test_periodic_scan_symbols_rotate_with_batch_budget() -> None:
    agent = _build_agent(
        AgentConfig(
            periodic_scan_batch_size=3,
            startup_initial_scan_limit=2,
            startup_scan_limit_step=1,
            startup_ramp_cycles=2,
        )
    )
    symbols = ["US:SPY", "US:QQQ", "US:MSFT", "US:AAPL"]

    agent._cycle_count = 1
    first = agent._periodic_scan_symbols(symbols)

    agent._cycle_count = 2
    second = agent._periodic_scan_symbols(symbols)

    agent._cycle_count = 3
    third = agent._periodic_scan_symbols(symbols)

    assert first == ["US:SPY", "US:QQQ"]
    assert second == ["US:MSFT", "US:AAPL", "US:SPY"]
    assert third == ["US:QQQ", "US:MSFT", "US:AAPL"]


def test_periodic_scan_symbols_always_include_open_positions() -> None:
    position_manager = PositionManager(state_path=None)
    position_manager.open_position(
        symbol="US:QQQ",
        quantity=1,
        side=PositionSide.LONG,
        price=500.0,
        strategy_tag="US_Swing_Radar",
    )
    agent = TradingAgent(
        config=AgentConfig(
            periodic_scan_batch_size=1,
            startup_initial_scan_limit=1,
            startup_scan_limit_step=1,
            startup_ramp_cycles=1,
        ),
        strategy_executor=MagicMock(),
        order_manager=MagicMock(),
        position_manager=position_manager,
        risk_manager=MagicMock(),
        event_bus=MagicMock(),
        fyers_client=MagicMock(),
    )
    agent._cycle_count = 1

    filtered = agent._periodic_scan_symbols(["US:SPY", "US:QQQ", "US:AAPL"])

    assert filtered == ["US:QQQ"]


def test_crypto_symbol_becomes_event_driven_only_after_live_candle() -> None:
    candle_broker = TickStreamBroker()
    agent = TradingAgent(
        config=AgentConfig(
            event_driven_execution_enabled=True,
            event_driven_markets=["CRYPTO"],
            crypto_symbols=["CRYPTO:BTCUSDT"],
        ),
        strategy_executor=MagicMock(),
        order_manager=MagicMock(),
        position_manager=MagicMock(),
        risk_manager=MagicMock(),
        event_bus=MagicMock(),
        fyers_client=MagicMock(),
        candle_broker=candle_broker,
    )
    agent.state = AgentState.RUNNING
    agent._warmed_symbols.add("CRYPTO:BTCUSDT")

    assert agent._is_event_driven_symbol_eligible("CRYPTO:BTCUSDT") is False

    candle_broker.publish(
        {
            "type": "candle",
            "symbol": "CRYPTO:BTCUSDT",
            "timeframe": "1",
            "timestamp": datetime.now(tz=IST).isoformat(),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 10,
        }
    )

    assert agent._is_event_driven_symbol_eligible("CRYPTO:BTCUSDT") is True


@pytest.mark.asyncio
async def test_fetch_live_prices_prefers_streamed_tick_snapshot() -> None:
    tick_broker = TickStreamBroker()
    tick_broker.publish(
        {
            "type": "tick",
            "symbol": "CRYPTO:BTCUSDT",
            "timestamp": datetime.now(tz=IST).isoformat(),
            "ltp": 43125.5,
        }
    )
    agent = TradingAgent(
        config=AgentConfig(crypto_symbols=["CRYPTO:BTCUSDT"]),
        strategy_executor=MagicMock(),
        order_manager=MagicMock(),
        position_manager=MagicMock(),
        risk_manager=MagicMock(),
        event_bus=MagicMock(),
        fyers_client=MagicMock(),
        tick_broker=tick_broker,
    )
    agent._fetch_crypto_live_prices = AsyncMock(side_effect=AssertionError("REST fallback should not run"))

    prices = await agent._fetch_live_prices(["CRYPTO:BTCUSDT"])

    assert prices == {"CRYPTO:BTCUSDT": 43125.5}


@pytest.mark.asyncio
async def test_fetch_us_yahoo_http_429_sets_provider_cooldown(monkeypatch) -> None:
    agent = _build_agent(AgentConfig())

    class _Response:
        status_code = 429

        def json(self) -> dict:
            return {}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            return _Response()

    monkeypatch.setattr("src.agent.trading_agent.httpx.AsyncClient", lambda *args, **kwargs: _Client())

    frame = await agent._fetch_us_yahoo_ohlcv("SPY", "1d", "2y", "US:SPY")

    assert frame is None
    assert agent._us_provider_available("yahoo") is False


@pytest.mark.asyncio
async def test_fetch_us_intraday_base_skips_finnhub_during_cooldown(monkeypatch) -> None:
    agent = _build_agent(AgentConfig())
    frame = _frame_with_end(datetime.now(tz=IST), minutes=1, bars=20, price=100.0)

    monkeypatch.setattr(
        "src.agent.trading_agent.get_settings",
        lambda: SimpleNamespace(finnhub_api_key="token", alphavantage_api_key=""),
    )
    agent._set_us_provider_cooldown("finnhub", 600, "test")
    agent._fetch_us_finnhub_ohlcv = AsyncMock(side_effect=AssertionError("finnhub should be skipped"))
    agent._fetch_us_alphavantage_ohlcv = AsyncMock(return_value=None)
    agent._fetch_us_yahoo_ohlcv = AsyncMock(return_value=frame)
    agent._fetch_us_nasdaq_ohlcv = AsyncMock(return_value=None)

    result = await agent._fetch_us_intraday_base("US:SPY", "SPY")

    assert result is not None
    agent._fetch_us_yahoo_ohlcv.assert_awaited_once()
    agent._fetch_us_finnhub_ohlcv.assert_not_called()


def test_event_driven_exit_symbol_requires_position_and_live_tick() -> None:
    tick_broker = TickStreamBroker()
    position_manager = PositionManager()
    agent = TradingAgent(
        config=AgentConfig(
            event_driven_execution_enabled=True,
            event_driven_markets=["CRYPTO"],
            crypto_symbols=["CRYPTO:BTCUSDT"],
        ),
        strategy_executor=MagicMock(),
        order_manager=MagicMock(),
        position_manager=position_manager,
        risk_manager=MagicMock(),
        event_bus=MagicMock(),
        fyers_client=MagicMock(),
        tick_broker=tick_broker,
    )
    agent.state = AgentState.RUNNING

    assert agent._is_event_driven_exit_symbol_eligible("CRYPTO:BTCUSDT") is False

    position_manager.open_position(
        symbol="CRYPTO:BTCUSDT",
        quantity=2,
        side=PositionSide.LONG,
        price=43000.0,
        strategy_tag="EMA_Crossover",
    )
    assert agent._is_event_driven_exit_symbol_eligible("CRYPTO:BTCUSDT") is False

    tick_broker.publish(
        {
            "type": "tick",
            "symbol": "CRYPTO:BTCUSDT",
            "timestamp": datetime.now(tz=IST).isoformat(),
            "ltp": 43125.5,
        }
    )

    assert agent._is_event_driven_exit_symbol_eligible("CRYPTO:BTCUSDT") is True


@pytest.mark.asyncio
async def test_check_position_exit_closes_target_without_position_update_event() -> None:
    position_manager = PositionManager()
    position_manager.open_position(
        symbol="CRYPTO:ADAUSDT",
        quantity=10,
        side=PositionSide.LONG,
        price=1.0,
        strategy_tag="EMA_Crossover",
    )

    placed_order = MagicMock()
    placed_order.status = OrderStatus.FILLED
    placed_order.fill_price = 1.2
    order_manager = MagicMock()
    order_manager.place_order.return_value = MagicMock(success=True, order=placed_order)

    event_bus = MagicMock()
    event_bus.emit = AsyncMock()
    risk_manager = MagicMock()
    risk_manager.config.time_based_exit_minutes = 5

    agent = TradingAgent(
        config=AgentConfig(),
        strategy_executor=MagicMock(),
        order_manager=order_manager,
        position_manager=position_manager,
        risk_manager=risk_manager,
        event_bus=event_bus,
        fyers_client=MagicMock(),
    )
    agent._upsert_option_exit_plan(
        symbol="CRYPTO:ADAUSDT",
        underlying_symbol="CRYPTO:ADAUSDT",
        strategy="EMA_Crossover",
        quantity=10,
        execution_timeframe="5",
        entry_price=1.0,
        stop_loss=0.9,
        target=1.1,
        signal_id="sig-1",
    )
    agent._apply_stream_mark_price("CRYPTO:ADAUSDT", 1.2)

    triggered = await agent._check_position_exit(
        "CRYPTO:ADAUSDT",
        now=datetime.now(tz=IST),
        eod_buffer_minutes=5,
        emit_position_update=False,
    )

    assert triggered is True
    assert position_manager.get_position("CRYPTO:ADAUSDT") is None
    emitted_types = [call.args[0].event_type for call in event_bus.emit.await_args_list]
    assert AgentEventType.POSITION_UPDATE not in emitted_types


@pytest.mark.asyncio
async def test_live_only_scan_suppresses_verbose_info_events() -> None:
    event_bus = MagicMock()
    event_bus.emit = AsyncMock()
    executor = MagicMock()
    executor._strategies = {"EMA_Crossover": object()}
    executor.process_data.return_value = []

    agent = TradingAgent(
        config=AgentConfig(
            strategies=["EMA_Crossover"],
            execution_timeframes=["3"],
            liberal_bootstrap_enabled=False,
        ),
        strategy_executor=executor,
        order_manager=MagicMock(),
        position_manager=MagicMock(),
        risk_manager=MagicMock(),
        event_bus=event_bus,
        fyers_client=MagicMock(),
    )
    agent._fetch_market_data = AsyncMock(return_value=_frame_with_end(datetime.now(tz=IST), minutes=3, bars=30))

    await agent._scan_symbol_unlocked("NSE:NIFTY50-INDEX", live_only=True)

    event_bus.emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_execution_core_signal_dispatches_into_process_signal_once() -> None:
    event_bus = MagicMock()
    event_bus.emit = AsyncMock()
    agent = TradingAgent(
        config=AgentConfig(
            event_driven_markets=["CRYPTO"],
            crypto_symbols=["CRYPTO:BTCUSDT"],
        ),
        strategy_executor=MagicMock(),
        order_manager=MagicMock(),
        position_manager=MagicMock(),
        risk_manager=MagicMock(),
        event_bus=event_bus,
        fyers_client=MagicMock(),
    )
    agent.state = AgentState.RUNNING
    agent._runtime_settings = SimpleNamespace(nats_enabled=True)
    agent._execution_core_backend = "rust"
    agent._execution_core_signal_subject = "test_stream.execution.signals"
    agent._reset_execution_core_signal_state()
    agent._process_signal = AsyncMock()

    payload = {
        "stream": "execution_signals",
        "event_time": datetime.now(tz=IST).isoformat(),
        "event_id": "sig-rust-1",
        "source": "execution_core",
        "event_type": "signal_candidate",
        "signal_type": "BUY",
        "symbol": "CRYPTO:BTCUSDT",
        "market": "CRYPTO",
        "timeframe": "1",
        "strategy": "Rust_EMA_Crossover",
        "price": 64000.0,
        "payload": {"ema_fast": 63990.0, "ema_slow": 63970.0},
    }

    await agent._handle_execution_core_signal(payload)
    await agent._handle_execution_core_signal(payload)

    assert agent._process_signal.await_count == 1
    dispatched_signal = agent._process_signal.await_args.args[0]
    assert dispatched_signal.symbol == "CRYPTO:BTCUSDT"
    assert dispatched_signal.signal_type == SignalType.BUY
    assert dispatched_signal.metadata["signal_source"] == "execution_core"
    assert agent._total_signals == 1
    assert agent._strategy_signal_counts["Rust_EMA_Crossover"] == 1
    assert agent._market_signal_counts["CRYPTO"] == 1
    assert agent._execution_core_signal_stats["accepted"] == 1
    assert agent._execution_core_signal_stats["rejected"] == 1


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


def test_signal_priority_score_prefers_market_specific_reward_curve() -> None:
    agent = _build_agent(AgentConfig())
    signal = Signal(
        timestamp=datetime.now(tz=IST),
        symbol="CRYPTO:BTCUSDT",
        signal_type=SignalType.BUY,
        strength=SignalStrength.MODERATE,
        price=100.0,
        strategy_name="Fractal_Profile_Breakout",
        metadata={
            "market": "CRYPTO",
            "conviction": 78.0,
            "setup_type": "acceptance_trend",
            "value_acceptance": "accepted",
        },
    )
    regime = {"regime": "trending", "trend": "bullish"}
    agent._strategy_reward_ema["Fractal_Profile_Breakout"] = 8.0
    agent._strategy_market_reward_ema["Fractal_Profile_Breakout"] = {"CRYPTO": -6.0}
    agent._strategy_perf_tracker.record_trade("Fractal_Profile_Breakout", 8.0)
    for _ in range(8):
        agent._strategy_perf_tracker.record_trade("Fractal_Profile_Breakout", -1.0, market="CRYPTO")

    score = agent._signal_priority_score("Fractal_Profile_Breakout", signal, "3", regime)

    assert score < 90.0


def test_position_size_multiplier_uses_market_reward_when_available() -> None:
    agent = _build_agent(AgentConfig(reinforcement_size_boost_pct=50.0))
    agent._strategy_reward_ema["EMA_Crossover"] = 10.0
    agent._strategy_market_reward_ema["EMA_Crossover"] = {"CRYPTO": -5.0, "US": 12.0}
    for _ in range(10):
        agent._strategy_perf_tracker.record_trade("EMA_Crossover", 1.0, market="US")
    for _ in range(10):
        agent._strategy_perf_tracker.record_trade("EMA_Crossover", -1.0, market="CRYPTO")

    us_mult = agent._position_size_multiplier("EMA_Crossover", "US")
    crypto_mult = agent._position_size_multiplier("EMA_Crossover", "CRYPTO")

    assert us_mult > crypto_mult


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
async def test_resolve_liquidity_quantity_cap_scales_us_option_contract_counts() -> None:
    agent = _build_agent(AgentConfig())

    result = await agent._resolve_liquidity_quantity_cap(
        execution_symbol="US:SPY260313C00600000",
        underlying_symbol="US:SPY",
        execution_market="US",
        execution_timeframe="15",
        side=OrderSide.BUY,
        lot_size=100,
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

    assert result["contract_liquidity"]["raw_volume"] == 1200
    assert result["contract_liquidity"]["raw_oi"] == 5000
    assert result["volume_cap"] == 6000
    assert result["oi_cap"] == 10000
    assert result["max_quantity"] == 6000


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


@pytest.mark.asyncio
async def test_close_position_queues_live_exit_submission_without_direct_place_call() -> None:
    position_manager = PositionManager()
    position_manager.open_position(
        symbol="CRYPTO:ADAUSDT",
        quantity=10,
        side=PositionSide.LONG,
        price=1.0,
        strategy_tag="EMA_Crossover",
    )

    order_manager = MagicMock()
    submitter = MagicMock(spec=OrderSubmitter)
    submitter.submit = AsyncMock(return_value=True)
    submitter.snapshot.return_value = {}

    event_bus = MagicMock()
    event_bus.emit = AsyncMock()
    risk_manager = MagicMock()

    agent = TradingAgent(
        config=AgentConfig(paper_mode=False),
        strategy_executor=MagicMock(),
        order_manager=order_manager,
        position_manager=position_manager,
        risk_manager=risk_manager,
        event_bus=event_bus,
        fyers_client=MagicMock(),
        order_submitter=submitter,
    )

    await agent._close_position(
        symbol="CRYPTO:ADAUSDT",
        short_name="ADAUSDT",
        current_price=1.2,
        reason="target",
        plan=None,
    )

    order_manager.place_order.assert_not_called()
    submitter.submit.assert_awaited_once()
    assert len(agent._pending_live_exit_submissions) == 1


@pytest.mark.asyncio
async def test_handle_entry_submit_result_promotes_submission_to_pending_live_entry() -> None:
    event_bus = MagicMock()
    event_bus.emit = AsyncMock()
    risk_manager = MagicMock()
    order_manager = OrderManager(paper_mode=False)

    order = Order(
        symbol="NSE:NIFTY26MAR22500CE",
        quantity=10,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        tag="EMA_Crossover",
    )
    order.order_id = "LIVE-ACK-1"
    order.status = OrderStatus.PLACED
    order_manager._orders[order.order_id] = order

    agent = TradingAgent(
        config=AgentConfig(paper_mode=False),
        strategy_executor=MagicMock(),
        order_manager=order_manager,
        position_manager=PositionManager(),
        risk_manager=risk_manager,
        event_bus=event_bus,
        fyers_client=MagicMock(),
    )
    agent._pending_live_entry_submissions["sub-1"] = PendingLiveEntrySubmission(
        submission_id="sub-1",
        symbol="NSE:NIFTY26MAR22500CE",
        underlying_symbol="NSE:NIFTY50-INDEX",
        short_name="NIFTY",
        execution_short_name="NIFTY26MAR22500CE",
        quantity=10,
        side=OrderSide.BUY,
        strategy="EMA_Crossover",
        market="NSE",
        execution_timeframe="5",
        entry_price_hint=100.0,
        stop_loss=95.0,
        target=110.0,
        signal_id="sig-1",
        option_contract=None,
    )

    await agent._handle_order_submit_result(
        {
            "type": "order_submission_result",
            "submission_id": "sub-1",
            "success": True,
            "message": "ok",
            "order_id": "LIVE-ACK-1",
            "status": OrderStatus.PLACED.value,
            "symbol": "NSE:NIFTY26MAR22500CE",
            "order_snapshot": {
                "symbol": "NSE:NIFTY26MAR22500CE",
                "quantity": 10,
                "side": "BUY",
                "order_type": "MARKET",
                "product_type": "INTRADAY",
                "tag": "EMA_Crossover",
                "order_id": "LIVE-ACK-1",
                "status": OrderStatus.PLACED.value,
                "fill_price": None,
                "fill_quantity": 0,
                "rejection_reason": None,
                "limit_price": None,
                "stop_price": None,
                "market_price_hint": 100.0,
                "placed_at": None,
                "filled_at": None,
            },
        }
    )

    assert "sub-1" not in agent._pending_live_entry_submissions
    assert "LIVE-ACK-1" in agent._pending_live_entries


@pytest.mark.asyncio
async def test_live_entry_position_opens_only_after_broker_fill() -> None:
    position_manager = PositionManager()
    event_bus = MagicMock()
    event_bus.emit = AsyncMock()
    risk_manager = MagicMock()

    agent = TradingAgent(
        config=AgentConfig(paper_mode=False),
        strategy_executor=MagicMock(),
        order_manager=MagicMock(),
        position_manager=position_manager,
        risk_manager=risk_manager,
        event_bus=event_bus,
        fyers_client=MagicMock(),
    )
    agent._pending_live_entries["LIVE-1"] = PendingLiveEntryOrder(
        order_id="LIVE-1",
        symbol="NSE:NIFTY26MAR22500CE",
        underlying_symbol="NSE:NIFTY50-INDEX",
        short_name="NIFTY",
        execution_short_name="NIFTY26MAR22500CE",
        quantity=10,
        side=OrderSide.BUY,
        strategy="EMA_Crossover",
        market="NSE",
        execution_timeframe="5",
        entry_price_hint=100.0,
        stop_loss=95.0,
        target=110.0,
        signal_id="sig-1",
        option_contract=OptionContract(
            underlying_symbol="NSE:NIFTY50-INDEX",
            option_symbol="NSE:NIFTY26MAR22500CE",
            option_type="CE",
            strike=22500.0,
            expiry="2026-03-26",
            ltp=100.0,
            lot_size=25,
        ),
    )

    first_order = Order(
        symbol="NSE:NIFTY26MAR22500CE",
        quantity=10,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        order_id="LIVE-1",
        status=OrderStatus.PARTIALLY_FILLED,
        fill_price=100.0,
        fill_quantity=4,
        tag="EMA_Crossover",
    )
    await agent._apply_broker_reconciliation(
        event_kind="trade",
        result=BrokerOrderUpdateResult(
            updated=True,
            order=first_order,
            message="partial fill",
            fill_delta_quantity=4,
            fill_delta_price=100.0,
            status_changed=True,
        ),
    )

    partial_position = position_manager.get_position("NSE:NIFTY26MAR22500CE")
    assert partial_position is not None
    assert partial_position.quantity == 4
    assert "LIVE-1" in agent._pending_live_entries
    assert agent._symbol_exit_plans("NSE:NIFTY26MAR22500CE")[0].quantity == 4

    second_order = Order(
        symbol="NSE:NIFTY26MAR22500CE",
        quantity=10,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        order_id="LIVE-1",
        status=OrderStatus.FILLED,
        fill_price=101.0,
        fill_quantity=10,
        tag="EMA_Crossover",
    )
    await agent._apply_broker_reconciliation(
        event_kind="trade",
        result=BrokerOrderUpdateResult(
            updated=True,
            order=second_order,
            message="filled",
            fill_delta_quantity=6,
            fill_delta_price=101.0,
            status_changed=True,
        ),
    )

    final_position = position_manager.get_position("NSE:NIFTY26MAR22500CE")
    assert final_position is not None
    assert final_position.quantity == 10
    assert "LIVE-1" not in agent._pending_live_entries
    assert agent._symbol_exit_plans("NSE:NIFTY26MAR22500CE")[0].quantity == 10


@pytest.mark.asyncio
async def test_recover_live_broker_state_rehydrates_pending_entry_and_position(tmp_path) -> None:
    order_manager = OrderManager(paper_mode=False, state_path=tmp_path / "orders.json")
    position_manager = PositionManager(state_path=tmp_path / "positions.json")
    event_bus = MagicMock()
    event_bus.emit = AsyncMock()
    risk_manager = MagicMock()

    fyers_client = MagicMock()
    fyers_client.is_authenticated = True
    fyers_client.get_orders.return_value = {
        "orderBook": [
            {
                "id": "LIVE-RECOVERY-1",
                "symbol": "NSE:NIFTY26MAR22500CE",
                "qty": 10,
                "filledQty": 4,
                "remainingQuantity": 6,
                "tradedPrice": 100.0,
                "status": 4,
                "side": 1,
                "type": 1,
                "productType": "INTRADAY",
                "orderTag": "EMA_Crossover",
            }
        ]
    }
    fyers_client.get_tradebook.return_value = {
        "tradeBook": [
            {
                "orderNumber": "LIVE-RECOVERY-1",
                "tradeNumber": "TRD-RECOVERY-1",
                "symbol": "NSE:NIFTY26MAR22500CE",
                "tradedQty": 4,
                "tradePrice": 100.0,
                "side": 1,
                "orderType": 1,
                "productType": "INTRADAY",
                "orderTag": "EMA_Crossover",
                "orderDateTime": "2026-03-14T09:20:00+05:30",
            }
        ]
    }
    fyers_client.get_positions.return_value = {
        "netPositions": [
            {
                "symbol": "NSE:NIFTY26MAR22500CE",
                "netQty": 4,
                "side": 1,
                "netAvg": 100.0,
            }
        ]
    }

    agent = TradingAgent(
        config=AgentConfig(paper_mode=False),
        strategy_executor=MagicMock(),
        order_manager=order_manager,
        position_manager=position_manager,
        risk_manager=risk_manager,
        event_bus=event_bus,
        fyers_client=fyers_client,
    )
    agent._runtime_state_path = tmp_path / "agent_live_state.json"
    agent._pending_live_entries["LIVE-RECOVERY-1"] = PendingLiveEntryOrder(
        order_id="LIVE-RECOVERY-1",
        symbol="NSE:NIFTY26MAR22500CE",
        underlying_symbol="NSE:NIFTY50-INDEX",
        short_name="NIFTY",
        execution_short_name="NSE:NIFTY26MAR22500CE",
        quantity=10,
        side=OrderSide.BUY,
        strategy="EMA_Crossover",
        market="NSE",
        execution_timeframe="5",
        entry_price_hint=100.0,
        stop_loss=95.0,
        target=110.0,
        signal_id="sig-recovery",
        option_contract=OptionContract(
            underlying_symbol="NSE:NIFTY50-INDEX",
            option_symbol="NSE:NIFTY26MAR22500CE",
            option_type="CE",
            strike=22500.0,
            expiry="2026-03-26",
            ltp=100.0,
            lot_size=25,
        ),
    )
    agent._persist_live_runtime_state()

    restarted = TradingAgent(
        config=AgentConfig(paper_mode=False),
        strategy_executor=MagicMock(),
        order_manager=OrderManager(paper_mode=False, state_path=tmp_path / "orders.json"),
        position_manager=PositionManager(state_path=tmp_path / "positions.json"),
        risk_manager=risk_manager,
        event_bus=event_bus,
        fyers_client=fyers_client,
    )
    restarted._runtime_state_path = tmp_path / "agent_live_state.json"
    restarted._load_live_runtime_state()

    await restarted._recover_live_broker_state()

    recovered_position = restarted.position_manager.get_position("NSE:NIFTY26MAR22500CE")
    assert recovered_position is not None
    assert recovered_position.quantity == 4
    assert "LIVE-RECOVERY-1" in restarted._pending_live_entries
    assert restarted._symbol_exit_plans("NSE:NIFTY26MAR22500CE")[0].quantity == 4
