"""Risk management API endpoints.

Provides REST access to the current risk state summary and
comprehensive portfolio risk metrics.
"""

from __future__ import annotations

import math

from fastapi import APIRouter, Depends, Query

from src.api.dependencies import (
    get_position_manager,
    get_risk_calculator,
    get_risk_manager,
    get_trading_agent,
)
from src.api.schemas import RiskMetricsResponse, RiskSummaryResponse
from src.execution.position_manager import PositionManager
from src.risk.risk_calculator import RiskCalculator
from src.risk.risk_manager import RiskManager
from src.agent.trading_agent import TradingAgent

router = APIRouter(tags=["Risk"])


# =========================================================================
# Endpoints
# =========================================================================


@router.get("/risk/summary", response_model=RiskSummaryResponse)
def risk_summary(
    rm: RiskManager = Depends(get_risk_manager),
    trading_agent: TradingAgent = Depends(get_trading_agent),
) -> RiskSummaryResponse:
    """Get current daily risk state summary.

    Includes realized/unrealized P&L, circuit breaker status,
    position counts, and available risk budget.
    """
    summary = rm.get_risk_summary()
    capital_allocations = trading_agent.get_capital_allocations()
    total_allocated_capital_inr = trading_agent.total_allocated_capital_inr()
    total_pnl = float(summary.get("total_pnl", 0.0) or 0.0)
    summary["capital"] = total_allocated_capital_inr
    summary["total_allocated_capital_inr"] = total_allocated_capital_inr
    summary["total_pnl_pct_on_allocated"] = round(
        (total_pnl / total_allocated_capital_inr) * 100.0,
        2,
    ) if total_allocated_capital_inr > 0 else 0.0
    summary["market_allocations"] = capital_allocations
    return RiskSummaryResponse(**summary)


@router.get("/risk/metrics", response_model=RiskMetricsResponse)
def risk_metrics(
    rc: RiskCalculator = Depends(get_risk_calculator),
    pm: PositionManager = Depends(get_position_manager),
) -> RiskMetricsResponse:
    """Compute comprehensive risk metrics from closed trades.

    Uses the RiskCalculator to derive Sharpe, Sortino, VaR, drawdown,
    and other metrics from the trade PnL series. Returns zeros if
    there are no closed trades.
    """
    trades = pm.get_closed_trades()
    metrics = rc.calculate_from_trades(trades)

    def safe(value: object) -> float:
        try:
            parsed = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0
        return parsed if math.isfinite(parsed) else 0.0

    return RiskMetricsResponse(
        sharpe_ratio=safe(metrics.sharpe_ratio),
        sortino_ratio=safe(metrics.sortino_ratio),
        calmar_ratio=safe(metrics.calmar_ratio),
        max_drawdown=safe(metrics.max_drawdown),
        max_drawdown_duration=metrics.max_drawdown_duration,
        var_95=safe(metrics.var_95),
        var_99=safe(metrics.var_99),
        cvar_95=safe(metrics.cvar_95),
        volatility=safe(metrics.volatility),
        downside_volatility=safe(metrics.downside_volatility),
        profit_factor=safe(metrics.profit_factor),
        win_rate=safe(metrics.win_rate),
        avg_win=safe(metrics.avg_win),
        avg_loss=safe(metrics.avg_loss),
        expectancy=safe(metrics.expectancy),
        total_return=safe(metrics.total_return),
        annualized_return=safe(metrics.annualized_return),
    )


@router.post("/risk/reset", response_model=RiskSummaryResponse)
def reset_risk_state(
    clear_emergency_stop: bool = Query(
        default=False,
        description="Also clear the emergency stop flag when true.",
    ),
    rm: RiskManager = Depends(get_risk_manager),
) -> RiskSummaryResponse:
    """Reset today's risk counters and optionally clear the kill switch."""
    rm.reset_daily_state()
    if clear_emergency_stop and rm.emergency_stop:
        rm.clear_emergency_stop("manual_risk_reset")
    summary = rm.get_risk_summary()
    return RiskSummaryResponse(**summary)
