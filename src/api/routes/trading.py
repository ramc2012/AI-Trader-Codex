"""Trading API endpoints -- positions, orders, and trade history.

Provides REST access to position state, order book, and closed trade
history from the in-memory managers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from src.api.dependencies import get_order_manager, get_position_manager
from src.api.schemas import (
    ClosedTradeResponse,
    OrderResponse,
    PortfolioSummaryResponse,
    PositionResponse,
)
from src.execution.order_manager import OrderManager
from src.execution.position_manager import PositionManager

router = APIRouter(tags=["Trading"])


# =========================================================================
# Endpoints
# =========================================================================


@router.get("/positions", response_model=List[PositionResponse])
def list_positions(
    pm: PositionManager = Depends(get_position_manager),
) -> List[PositionResponse]:
    """List all open positions with real-time P&L."""
    positions = pm.get_all_positions()
    return [
        PositionResponse(
            symbol=p.symbol,
            quantity=p.quantity,
            side=p.side.value,
            avg_price=p.avg_price,
            current_price=p.current_price,
            entry_time=p.entry_time,
            strategy_tag=p.strategy_tag,
            order_ids=list(p.order_ids),
            unrealized_pnl=p.unrealized_pnl,
            unrealized_pnl_pct=p.unrealized_pnl_pct,
            market_value=p.market_value,
            is_profitable=p.is_profitable,
        )
        for p in positions
    ]


@router.get("/portfolio", response_model=PortfolioSummaryResponse)
def portfolio_summary(
    pm: PositionManager = Depends(get_position_manager),
) -> PortfolioSummaryResponse:
    """Get aggregated portfolio summary with total P&L."""
    summary = pm.get_portfolio_summary()
    return PortfolioSummaryResponse(**summary)


@router.get("/orders", response_model=List[OrderResponse])
def list_orders(
    om: OrderManager = Depends(get_order_manager),
) -> List[OrderResponse]:
    """List all orders (open and closed)."""
    orders = om.get_all_orders()
    return [_order_to_response(o) for o in orders]


@router.get("/orders/open", response_model=List[OrderResponse])
def list_open_orders(
    om: OrderManager = Depends(get_order_manager),
) -> List[OrderResponse]:
    """List only open (non-terminal) orders."""
    orders = om.get_open_orders()
    return [_order_to_response(o) for o in orders]


@router.get("/trades", response_model=List[ClosedTradeResponse])
def list_closed_trades(
    pm: PositionManager = Depends(get_position_manager),
) -> List[ClosedTradeResponse]:
    """List all closed trades with realized P&L."""
    trades = pm.get_closed_trades()
    return [
        ClosedTradeResponse(
            symbol=t["symbol"],
            side=t["side"],
            quantity=t["quantity"],
            entry_price=t["entry_price"],
            exit_price=t["exit_price"],
            pnl=t["pnl"],
            closed_at=t.get("closed_at"),
            strategy_tag=t.get("strategy_tag", ""),
        )
        for t in trades
    ]


@router.get("/portfolio/equity-curve")
def get_equity_curve(
    pm: PositionManager = Depends(get_position_manager),
) -> List[Dict[str, Any]]:
    """Get equity curve data points.

    Returns accumulated portfolio value snapshots. If no snapshots
    exist yet (no trading activity), returns initial capital as a
    baseline single data point.
    """
    # Check if PositionManager has equity snapshots
    snapshots = getattr(pm, "_equity_snapshots", [])

    if snapshots:
        return snapshots

    # No snapshots yet - return initial capital baseline
    portfolio = pm.get_portfolio_summary()
    capital = portfolio.get("total_market_value", 1000000)
    if capital == 0:
        capital = 1000000  # Default when no positions

    return [
        {
            "time": datetime.now().isoformat(),
            "value": capital,
        }
    ]


# =========================================================================
# Helpers
# =========================================================================


def _order_to_response(order: object) -> OrderResponse:
    """Convert an Order dataclass to an OrderResponse schema."""
    # Access attributes from the Order dataclass
    from src.execution.order_manager import Order

    o: Order = order  # type: ignore[assignment]
    return OrderResponse(
        symbol=o.symbol,
        quantity=o.quantity,
        side=o.side.name,
        order_type=o.order_type.name,
        product_type=o.product_type.value,
        limit_price=o.limit_price,
        stop_price=o.stop_price,
        tag=o.tag,
        order_id=o.order_id,
        status=o.status.value,
        fill_price=o.fill_price,
        fill_quantity=o.fill_quantity,
        placed_at=o.placed_at,
        filled_at=o.filled_at,
        rejection_reason=o.rejection_reason,
        is_buy=o.is_buy,
        is_complete=o.is_complete,
        value=o.value,
    )
