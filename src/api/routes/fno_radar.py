"""FnO Radar endpoints backed by swing-research artifacts."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_trading_agent
from src.config.agent_universe import fno_root_to_spot_symbol
from src.config.fno_constants import FNO_SYMBOLS
from src.database.models import IndexOHLC
from src.research.fno_swing_live import FnOSwingLiveScorer

router = APIRouter(prefix="/fno-radar", tags=["FnO Radar"])


def _serialize_timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


@router.get("/overview")
async def get_fno_radar_overview(
    limit: int = Query(default=40, ge=1, le=200),
    min_score: float = Query(default=55.0, ge=0.0, le=100.0),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    scorer = FnOSwingLiveScorer()
    research = scorer.research_status()
    candidates = scorer.list_latest_candidates(limit=limit, min_score=min_score)

    fno_spot_symbols = [fno_root_to_spot_symbol(symbol) for symbol in FNO_SYMBOLS]
    coverage_stmt = select(
        func.count(func.distinct(IndexOHLC.symbol)),
        func.max(IndexOHLC.timestamp),
    ).where(
        IndexOHLC.timeframe == "D",
        IndexOHLC.symbol.in_(fno_spot_symbols),
    )
    coverage_result = await db.execute(coverage_stmt)
    daily_symbol_count, latest_daily_bar = coverage_result.one()

    agent = get_trading_agent()
    fno_spot_symbol_set = set(fno_spot_symbols)
    configured_fno_symbols = {
        symbol
        for symbol in agent.config.symbols
        if symbol in fno_spot_symbol_set
    }

    return {
        "research": research,
        "local_market_data": {
            "daily_symbols": int(daily_symbol_count or 0),
            "expected_symbols": len(FNO_SYMBOLS),
            "latest_daily_bar": _serialize_timestamp(latest_daily_bar),
        },
        "agent": {
            "nse_universe_size": len(agent.config.symbols),
            "configured_fno_symbols": len(configured_fno_symbols),
            "expected_fno_symbols": len(FNO_SYMBOLS),
            "strategy_enabled": "FnO_Swing_Radar" in set(agent.config.strategies),
            "active_strategies": list(agent.config.strategies),
        },
        "candidates": candidates,
    }
