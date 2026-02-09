"""Risk management API endpoints.

Provides REST access to the current risk state summary and
comprehensive portfolio risk metrics.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.dependencies import (
    get_position_manager,
    get_risk_calculator,
    get_risk_manager,
)
from src.api.schemas import RiskMetricsResponse, RiskSummaryResponse
from src.execution.position_manager import PositionManager
from src.risk.risk_calculator import RiskCalculator
from src.risk.risk_manager import RiskManager

router = APIRouter(tags=["Risk"])


# =========================================================================
# Endpoints
# =========================================================================


@router.get("/risk/summary", response_model=RiskSummaryResponse)
def risk_summary(
    rm: RiskManager = Depends(get_risk_manager),
) -> RiskSummaryResponse:
    """Get current daily risk state summary.

    Includes realized/unrealized P&L, circuit breaker status,
    position counts, and available risk budget.
    """
    summary = rm.get_risk_summary()
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

    return RiskMetricsResponse(
        sharpe_ratio=metrics.sharpe_ratio,
        sortino_ratio=metrics.sortino_ratio,
        calmar_ratio=metrics.calmar_ratio,
        max_drawdown=metrics.max_drawdown,
        max_drawdown_duration=metrics.max_drawdown_duration,
        var_95=metrics.var_95,
        var_99=metrics.var_99,
        cvar_95=metrics.cvar_95,
        volatility=metrics.volatility,
        downside_volatility=metrics.downside_volatility,
        profit_factor=metrics.profit_factor,
        win_rate=metrics.win_rate,
        avg_win=metrics.avg_win,
        avg_loss=metrics.avg_loss,
        expectancy=metrics.expectancy,
        total_return=metrics.total_return,
        annualized_return=metrics.annualized_return,
    )
