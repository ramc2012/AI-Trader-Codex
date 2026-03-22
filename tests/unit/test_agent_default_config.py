"""Default agent configuration sourced from settings/env."""

from __future__ import annotations

from src.api.schemas import AgentConfigRequest
from src.api.dependencies import get_trading_agent, reset_managers
from src.config.agent_universe import (
    DEFAULT_AGENT_NSE_SYMBOLS,
    DEFAULT_WATCHLIST_NSE_SYMBOLS,
    LEGACY_AGENT_NSE_INDEX_ONLY_SYMBOLS,
    LEGACY_AGENT_NSE_SYMBOLS_PRE_MARCH_2026,
)
from src.config.settings import get_settings


def test_default_trading_agent_uses_agent_capital_settings(
    monkeypatch,
    tmp_path,
) -> None:
    reset_managers()
    get_settings.cache_clear()

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("USD_INR_REFERENCE_RATE", "83")
    monkeypatch.setenv("AGENT_INDIA_CAPITAL", "600000")
    monkeypatch.setenv("AGENT_US_CAPITAL", "5000")
    monkeypatch.setenv("AGENT_CRYPTO_CAPITAL", "2500")
    monkeypatch.setenv("AGENT_INDIA_MAX_INSTRUMENT_PCT", "40")
    monkeypatch.setenv("AGENT_US_MAX_INSTRUMENT_PCT", "15")
    monkeypatch.setenv("AGENT_CRYPTO_MAX_INSTRUMENT_PCT", "10")
    monkeypatch.setenv("AGENT_STRATEGY_CAPITAL_BUCKET_ENABLED", "false")
    monkeypatch.setenv("AGENT_STRATEGY_MAX_CONCURRENT_POSITIONS", "2")

    try:
        agent = get_trading_agent()

        assert agent.config.india_capital == 600000.0
        assert agent.config.us_capital == 5000.0
        assert agent.config.crypto_capital == 2500.0
        assert agent.config.india_max_instrument_pct == 40.0
        assert agent.config.strategy_capital_bucket_enabled is False
        assert agent.config.strategy_max_concurrent_positions == 2

        allocations = agent.get_capital_allocations()
        assert allocations["NSE"]["max_instrument_capital"] == 240000.0
        assert allocations["US"]["max_instrument_capital"] == 750.0
        assert allocations["CRYPTO"]["max_instrument_capital"] == 250.0

        assert agent.risk_manager.config.capital == 1222500.0
        assert agent.risk_manager.config.max_position_size == 240000.0
    finally:
        reset_managers()
        get_settings.cache_clear()


def test_agent_start_request_expands_legacy_index_only_nse_universe() -> None:
    request = AgentConfigRequest(symbols=list(LEGACY_AGENT_NSE_INDEX_ONLY_SYMBOLS))

    assert request.symbols == list(DEFAULT_AGENT_NSE_SYMBOLS)


def test_agent_start_request_upgrades_legacy_full_nse_universe() -> None:
    request = AgentConfigRequest(symbols=list(LEGACY_AGENT_NSE_SYMBOLS_PRE_MARCH_2026))

    assert request.symbols == list(DEFAULT_AGENT_NSE_SYMBOLS)


def test_agent_start_request_upgrades_previous_watchlist_nse_universe() -> None:
    request = AgentConfigRequest(symbols=list(DEFAULT_WATCHLIST_NSE_SYMBOLS))

    assert request.symbols == list(DEFAULT_AGENT_NSE_SYMBOLS)


def test_agent_start_request_defaults_include_crypto_swing_controls() -> None:
    request = AgentConfigRequest()

    assert "Crypto_Swing_Radar" in request.strategies
    assert "Profile_Swing_Radar" in request.strategies
    assert "Profile_AI_Swing_Radar" in request.strategies
    assert request.disabled_strategies_by_market["CRYPTO"] == ["Bootstrap_Explorer", "EMA_Crossover"]
    assert request.strategy_budget_weights_by_market["CRYPTO"]["MP_OrderFlow_Breakout"] == 1.8
    assert request.strategy_budget_weights_by_market["CRYPTO"]["Fractal_Profile_Breakout"] == 1.8
    assert request.strategy_budget_weights_by_market["CRYPTO"]["Profile_Swing_Radar"] == 1.2
    assert request.strategy_budget_weights_by_market["CRYPTO"]["Profile_AI_Swing_Radar"] == 1.25
