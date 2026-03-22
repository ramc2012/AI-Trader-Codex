"""Profile swing radar endpoints for classic and AI-assisted swing strategies."""

from __future__ import annotations

from fastapi import APIRouter, Query

from src.api.dependencies import get_trading_agent
from src.research.profile_swing_live import ProfileSwingLiveScorer

router = APIRouter(prefix="/profile-swing-radar", tags=["Profile Swing Radar"])

_PROFILE_STRATEGIES = ("Profile_Swing_Radar", "Profile_AI_Swing_Radar")


@router.get("/overview")
async def get_profile_swing_radar_overview(
    limit: int = Query(default=30, ge=1, le=200),
    min_score: float = Query(default=58.0, ge=0.0, le=100.0),
) -> dict[str, object]:
    scorer = ProfileSwingLiveScorer()
    research = scorer.research_status()
    classic_candidates = scorer.list_latest_candidates(limit=limit, min_score=min_score, variant="classic")
    ai_candidates = scorer.list_latest_candidates(limit=limit, min_score=min_score, variant="ai")

    agent = get_trading_agent()
    status = agent.get_status()

    return {
        "research": research,
        "agent": {
            "nse_universe_size": len(agent.config.symbols),
            "us_universe_size": len(agent.config.us_symbols),
            "strategy_enabled": {
                name: name in set(agent.config.strategies)
                for name in _PROFILE_STRATEGIES
            },
            "active_strategies": list(agent.config.strategies),
            "strategy_stats": {
                name: status.get("strategy_stats", {}).get(name, {})
                for name in _PROFILE_STRATEGIES
            },
            "strategy_market_stats": {
                name: status.get("strategy_market_stats", {}).get(name, {})
                for name in _PROFILE_STRATEGIES
            },
        },
        "classic_candidates": classic_candidates,
        "ai_candidates": ai_candidates,
    }
