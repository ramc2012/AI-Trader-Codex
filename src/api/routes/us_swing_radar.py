"""US swing radar endpoints backed by swing-research artifacts."""

from __future__ import annotations

from fastapi import APIRouter, Query

from src.api.dependencies import get_trading_agent
from src.config.us_swing_universe import US_SWING_BENCHMARK_SYMBOL, US_SWING_SYMBOLS
from src.research.us_swing_live import USSwingLiveScorer

router = APIRouter(prefix="/us-swing-radar", tags=["US Swing Radar"])


@router.get("/overview")
async def get_us_swing_radar_overview(
    limit: int = Query(default=40, ge=1, le=200),
    min_score: float = Query(default=60.0, ge=0.0, le=100.0),
) -> dict[str, object]:
    scorer = USSwingLiveScorer()
    research = scorer.research_status()
    candidates = scorer.list_latest_candidates(limit=limit, min_score=min_score)

    agent = get_trading_agent()
    us_symbol_set = set(US_SWING_SYMBOLS)
    configured_us_symbols = {
        symbol
        for symbol in agent.config.us_symbols
        if symbol in us_symbol_set
    }

    return {
        "research": research,
        "agent": {
            "us_universe_size": len(agent.config.us_symbols),
            "configured_us_symbols": len(configured_us_symbols),
            "expected_us_symbols": len(US_SWING_SYMBOLS),
            "benchmark_symbol": US_SWING_BENCHMARK_SYMBOL,
            "strategy_enabled": "US_Swing_Radar" in set(agent.config.strategies),
            "active_strategies": list(agent.config.strategies),
        },
        "candidates": candidates,
    }
