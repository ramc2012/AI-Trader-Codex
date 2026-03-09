"""Trading API endpoints -- positions, orders, and trade history.

Provides REST access to position state, order book, and closed trade
history from the in-memory managers.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query

from src.agent.trading_agent import TradingAgent
from src.api.dependencies import get_order_manager, get_position_manager, get_risk_manager, get_trading_agent
from src.api.schemas import (
    ClosedTradeResponse,
    InstrumentPerformanceRowResponse,
    ModifyOrderRequest,
    OrderResponse,
    PortfolioInstrumentSummaryResponse,
    PortfolioSummaryResponse,
    PlaceOrderRequest,
    PositionResponse,
    TradePairResponse,
)
from src.config.market_hours import IST, is_market_open, is_us_market_open
from src.config.settings import get_settings
from src.execution.order_manager import (
    Order,
    OrderManager,
    OrderSide,
    OrderStatus,
    OrderType,
    ProductType,
)
from src.execution.position_manager import PositionManager, PositionSide
from src.risk.risk_manager import RiskManager
from src.utils.market_symbols import classify_market, parse_currency_context

router = APIRouter(tags=["Trading"])


# =========================================================================
# Endpoints
# =========================================================================


@router.post("/orders", response_model=OrderResponse)
def place_order(
    body: PlaceOrderRequest,
    om: OrderManager = Depends(get_order_manager),
    pm: PositionManager = Depends(get_position_manager),
    rm: RiskManager = Depends(get_risk_manager),
) -> OrderResponse:
    """Place an order and update in-memory position/risk state for filled quantities."""
    side = _parse_side(body.side)
    order_type = _parse_order_type(body.order_type)
    product_type = _parse_product_type(body.product_type)

    entry_price = (
        body.limit_price
        if body.limit_price is not None
        else body.market_price_hint
    )
    if body.validate_risk:
        if entry_price is None or entry_price <= 0:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Risk validation requires limit_price or market_price_hint "
                    "to estimate trade value."
                ),
            )
        stop_loss = (
            body.stop_loss
            if body.stop_loss is not None
            else (entry_price * 0.99 if side == OrderSide.BUY else entry_price * 1.01)
        )
        validation = rm.validate_trade(
            symbol=body.symbol,
            side=side.name,
            quantity=body.quantity,
            entry_price=float(entry_price),
            stop_loss=float(stop_loss),
        )
        if not validation.is_valid:
            raise HTTPException(status_code=400, detail=validation.reason)

    order = Order(
        symbol=body.symbol,
        quantity=body.quantity,
        side=side,
        order_type=order_type,
        product_type=product_type,
        limit_price=body.limit_price,
        stop_price=body.stop_price,
        market_price_hint=body.market_price_hint,
        tag=body.tag,
    )
    result = om.place_order(order)
    if not result.success or result.order is None:
        raise HTTPException(status_code=400, detail=result.message or "Order placement failed")

    _sync_filled_order_state(result.order, pm, rm)
    return _order_to_response(result.order)


@router.patch("/orders/{order_id}", response_model=OrderResponse)
def modify_order(
    order_id: str,
    body: ModifyOrderRequest,
    om: OrderManager = Depends(get_order_manager),
) -> OrderResponse:
    """Modify a pending/placed order."""
    result = om.modify_order(
        order_id=order_id,
        new_quantity=body.quantity,
        new_limit_price=body.limit_price,
        new_stop_price=body.stop_price,
    )
    if not result.success or result.order is None:
        status_code = 404 if "not found" in (result.message or "").lower() else 400
        raise HTTPException(status_code=status_code, detail=result.message or "Order modification failed")
    return _order_to_response(result.order)


@router.post("/orders/{order_id}/cancel", response_model=OrderResponse)
def cancel_order(
    order_id: str,
    om: OrderManager = Depends(get_order_manager),
) -> OrderResponse:
    """Cancel an order by id."""
    result = om.cancel_order(order_id)
    if not result.success or result.order is None:
        status_code = 404 if "not found" in (result.message or "").lower() else 400
        raise HTTPException(status_code=status_code, detail=result.message or "Order cancellation failed")
    return _order_to_response(result.order)


@router.post("/orders/{order_id}/simulate-fill", response_model=OrderResponse)
def simulate_fill(
    order_id: str,
    fill_price: float,
    fill_quantity: int | None = None,
    om: OrderManager = Depends(get_order_manager),
    pm: PositionManager = Depends(get_position_manager),
    rm: RiskManager = Depends(get_risk_manager),
) -> OrderResponse:
    """Simulate fill in paper mode and sync position/risk state."""
    before = om.get_order(order_id)
    if before is None:
        raise HTTPException(status_code=404, detail=f"Order '{order_id}' not found.")
    prev_filled = before.fill_quantity

    result = om.simulate_fill(order_id, fill_price, fill_quantity=fill_quantity)
    if not result.success or result.order is None:
        raise HTTPException(status_code=400, detail=result.message or "Simulated fill failed")

    newly_filled = max(result.order.fill_quantity - prev_filled, 0)
    _sync_filled_order_state(result.order, pm, rm, fill_quantity_override=newly_filled)
    return _order_to_response(result.order)


@router.get("/positions", response_model=List[PositionResponse])
async def list_positions(
    pm: PositionManager = Depends(get_position_manager),
    trading_agent: TradingAgent = Depends(get_trading_agent),
) -> List[PositionResponse]:
    """List all open positions with real-time P&L."""
    settings = get_settings()
    usd_inr_rate = float(settings.usd_inr_reference_rate)
    now = datetime.now(tz=IST)
    positions = pm.get_all_positions()
    if positions:
        # Keep marks fresh for UI polling instead of waiting for the next agent cycle.
        try:
            await trading_agent.refresh_position_marks([p.symbol for p in positions])
            positions = pm.get_all_positions()
        except Exception:
            pass

    out: List[PositionResponse] = []
    for position in positions:
        currency, currency_symbol, fx_to_inr = parse_currency_context(
            position.symbol,
            usd_inr_rate,
        )
        market = classify_market(position.symbol)
        plan = trading_agent._option_exit_plans.get(position.symbol)
        exit_metrics = _position_exit_metrics(position, plan, now)
        out.append(
            PositionResponse(
                symbol=position.symbol,
                market=market,
                market_open=_market_is_open(market, now),
                quantity=position.quantity,
                side=position.side.value,
                avg_price=position.avg_price,
                current_price=position.current_price,
                entry_time=position.entry_time,
                strategy_tag=position.strategy_tag,
                order_ids=list(position.order_ids),
                unrealized_pnl=position.unrealized_pnl,
                unrealized_pnl_pct=position.unrealized_pnl_pct,
                market_value=position.market_value,
                is_profitable=position.is_profitable,
                currency=currency,
                currency_symbol=currency_symbol,
                fx_to_inr=fx_to_inr,
                unrealized_pnl_inr=position.unrealized_pnl * fx_to_inr,
                market_value_inr=position.market_value * fx_to_inr,
                stop_loss=exit_metrics["stop_loss"],
                target=exit_metrics["target"],
                time_exit_at=exit_metrics["time_exit_at"],
                time_left_seconds=exit_metrics["time_left_seconds"],
                distance_to_stop_pct=exit_metrics["distance_to_stop_pct"],
                distance_to_target_pct=exit_metrics["distance_to_target_pct"],
                progress_to_target_pct=exit_metrics["progress_to_target_pct"],
            )
        )
    return out


@router.get("/portfolio", response_model=PortfolioSummaryResponse)
def portfolio_summary(
    pm: PositionManager = Depends(get_position_manager),
) -> PortfolioSummaryResponse:
    """Get aggregated portfolio summary with total P&L."""
    settings = get_settings()
    summary = _build_currency_aware_portfolio(
        pm=pm,
        usd_inr_rate=float(settings.usd_inr_reference_rate),
    )
    return PortfolioSummaryResponse(**summary)


@router.get("/portfolio/instruments", response_model=PortfolioInstrumentSummaryResponse)
def portfolio_by_instrument(
    period: str = Query(
        default="daily",
        description="One of: daily, week, month, year",
    ),
    om: OrderManager = Depends(get_order_manager),
    pm: PositionManager = Depends(get_position_manager),
) -> PortfolioInstrumentSummaryResponse:
    """Return period-filtered performance summary grouped by instrument."""
    settings = get_settings()
    usd_inr_rate = float(settings.usd_inr_reference_rate)
    from_time, to_time, normalized_period = _period_bounds(period)

    rows: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "symbol": "",
            "currency": "INR",
            "currency_symbol": "₹",
            "fx_to_inr": 1.0,
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "buy_notional": 0.0,
            "sell_notional": 0.0,
            "realized_pnl": 0.0,
            "realized_pnl_inr": 0.0,
            "unrealized_pnl": 0.0,
            "unrealized_pnl_inr": 0.0,
            "net_pnl_inr": 0.0,
            "avg_hold_minutes": 0.0,
            "last_trade_time": None,
            "open_quantity": 0,
            "open_market_value": 0.0,
            "open_market_value_inr": 0.0,
            "_hold_samples": [],
        }
    )

    pairs = _build_trade_pairs(
        orders=om.get_all_orders(),
        usd_inr_rate=usd_inr_rate,
    )
    for pair in pairs:
        if pair.exit_time is None:
            continue
        exit_time_ist = _to_ist_dt(pair.exit_time)
        if exit_time_ist < from_time or exit_time_ist > to_time:
            continue

        symbol = pair.symbol
        row = rows[symbol]
        row["symbol"] = symbol
        row["currency"] = pair.currency
        row["currency_symbol"] = pair.currency_symbol
        row["fx_to_inr"] = float(pair.fx_to_inr)
        row["trades"] += 1
        if pair.pnl >= 0:
            row["wins"] += 1
        else:
            row["losses"] += 1
        row["realized_pnl"] += float(pair.pnl)
        row["realized_pnl_inr"] += float(pair.pnl_inr)

        entry_notional = float(pair.entry_price) * int(pair.quantity)
        exit_notional = float(pair.exit_price) * int(pair.quantity)
        if pair.side == "LONG":
            row["buy_notional"] += entry_notional
            row["sell_notional"] += exit_notional
        else:
            row["sell_notional"] += entry_notional
            row["buy_notional"] += exit_notional

        if pair.entry_time is not None:
            entry_time_ist = _to_ist_dt(pair.entry_time)
            hold_minutes = max((exit_time_ist - entry_time_ist).total_seconds() / 60.0, 0.0)
            row["_hold_samples"].append(hold_minutes)

        prev_last = row["last_trade_time"]
        if prev_last is None or exit_time_ist > prev_last:
            row["last_trade_time"] = exit_time_ist

    for position in pm.get_all_positions():
        currency, currency_symbol, fx_to_inr = parse_currency_context(
            position.symbol,
            usd_inr_rate=usd_inr_rate,
        )
        row = rows[position.symbol]
        row["symbol"] = position.symbol
        row["currency"] = currency
        row["currency_symbol"] = currency_symbol
        row["fx_to_inr"] = fx_to_inr
        row["open_quantity"] += int(position.quantity)
        row["open_market_value"] += float(position.market_value)
        row["open_market_value_inr"] += float(position.market_value) * fx_to_inr
        row["unrealized_pnl"] += float(position.unrealized_pnl)
        row["unrealized_pnl_inr"] += float(position.unrealized_pnl) * fx_to_inr

    payload_rows: List[InstrumentPerformanceRowResponse] = []
    for symbol, row in rows.items():
        hold_samples = row.pop("_hold_samples", [])
        avg_hold = (sum(hold_samples) / len(hold_samples)) if hold_samples else 0.0
        row["avg_hold_minutes"] = round(float(avg_hold), 2)
        row["net_pnl_inr"] = round(
            float(row["realized_pnl_inr"]) + float(row["unrealized_pnl_inr"]),
            2,
        )
        row["realized_pnl"] = round(float(row["realized_pnl"]), 2)
        row["realized_pnl_inr"] = round(float(row["realized_pnl_inr"]), 2)
        row["unrealized_pnl"] = round(float(row["unrealized_pnl"]), 2)
        row["unrealized_pnl_inr"] = round(float(row["unrealized_pnl_inr"]), 2)
        row["buy_notional"] = round(float(row["buy_notional"]), 2)
        row["sell_notional"] = round(float(row["sell_notional"]), 2)
        row["open_market_value"] = round(float(row["open_market_value"]), 2)
        row["open_market_value_inr"] = round(float(row["open_market_value_inr"]), 2)
        payload_rows.append(InstrumentPerformanceRowResponse(**row))

    payload_rows.sort(key=lambda item: item.net_pnl_inr, reverse=True)

    total_realized_inr = round(sum(r.realized_pnl_inr for r in payload_rows), 2)
    total_unrealized_inr = round(sum(r.unrealized_pnl_inr for r in payload_rows), 2)
    total_net_inr = round(total_realized_inr + total_unrealized_inr, 2)
    total_trades = sum(r.trades for r in payload_rows)

    return PortfolioInstrumentSummaryResponse(
        period=normalized_period,
        from_time=from_time,
        to_time=to_time,
        total_instruments=len(payload_rows),
        total_trades=total_trades,
        total_realized_pnl_inr=total_realized_inr,
        total_unrealized_pnl_inr=total_unrealized_inr,
        total_net_pnl_inr=total_net_inr,
        rows=payload_rows,
    )


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


@router.get("/orders/pairs", response_model=List[TradePairResponse])
def list_order_pairs(
    om: OrderManager = Depends(get_order_manager),
) -> List[TradePairResponse]:
    """List FIFO-matched entry/exit trade pairs from filled order history."""
    settings = get_settings()
    return _build_trade_pairs(
        orders=om.get_all_orders(),
        usd_inr_rate=float(settings.usd_inr_reference_rate),
    )


@router.get("/orders/{order_id}", response_model=OrderResponse)
def get_order(
    order_id: str,
    om: OrderManager = Depends(get_order_manager),
) -> OrderResponse:
    """Fetch one order by id."""
    order = om.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail=f"Order '{order_id}' not found.")
    return _order_to_response(order)


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
    settings = get_settings()
    portfolio = _build_currency_aware_portfolio(
        pm=pm,
        usd_inr_rate=float(settings.usd_inr_reference_rate),
    )
    capital = portfolio.get("total_market_value_inr", 1000000)
    if capital == 0:
        capital = 1000000  # Default when no positions

    return [
        {
            "time": datetime.now(tz=IST).isoformat(),
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


def _period_bounds(period: str) -> tuple[datetime, datetime, str]:
    """Resolve period string into [from_time, to_time] in IST."""
    now_ist = datetime.now(tz=IST)
    key = str(period or "daily").strip().lower()

    if key in {"daily", "day", "d"}:
        start = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now_ist, "daily"

    if key in {"weekly", "week", "w"}:
        start = now_ist.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now_ist.weekday())
        return start, now_ist, "week"

    if key in {"monthly", "month", "m"}:
        start = now_ist.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, now_ist, "month"

    if key in {"yearly", "year", "y"}:
        start = now_ist.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, now_ist, "year"

    raise HTTPException(status_code=400, detail="period must be one of: daily, week, month, year")


def _market_is_open(market: str, now: datetime) -> bool:
    token = str(market or "").upper()
    if token == "US":
        return bool(is_us_market_open(now))
    if token == "CRYPTO":
        return True
    return bool(is_market_open(now))


def _position_exit_metrics(position: Any, plan: Any, now: datetime) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "stop_loss": None,
        "target": None,
        "time_exit_at": None,
        "time_left_seconds": None,
        "distance_to_stop_pct": None,
        "distance_to_target_pct": None,
        "progress_to_target_pct": None,
    }
    if plan is None:
        return payload

    stop_loss = float(getattr(plan, "stop_loss", 0.0) or 0.0)
    target = float(getattr(plan, "target", 0.0) or 0.0)
    time_exit_at = getattr(plan, "time_exit_at", None)
    current_price = float(getattr(position, "current_price", 0.0) or 0.0)
    side = str(getattr(getattr(position, "side", None), "value", getattr(position, "side", ""))).lower()

    payload["stop_loss"] = stop_loss or None
    payload["target"] = target or None
    payload["time_exit_at"] = time_exit_at
    if time_exit_at is not None:
        payload["time_left_seconds"] = max(int((time_exit_at - now).total_seconds()), 0)

    if current_price <= 0 or stop_loss <= 0 or target <= 0:
        return payload

    is_long = side in {"long", "buy"}
    if is_long:
        distance_to_stop = ((current_price - stop_loss) / current_price) * 100.0
        distance_to_target = ((target - current_price) / current_price) * 100.0
        span = target - stop_loss
        progress = ((current_price - stop_loss) / span * 100.0) if span > 0 else None
    else:
        distance_to_stop = ((stop_loss - current_price) / current_price) * 100.0
        distance_to_target = ((current_price - target) / current_price) * 100.0
        span = stop_loss - target
        progress = ((stop_loss - current_price) / span * 100.0) if span > 0 else None

    payload["distance_to_stop_pct"] = round(distance_to_stop, 2)
    payload["distance_to_target_pct"] = round(distance_to_target, 2)
    if progress is not None:
        payload["progress_to_target_pct"] = round(min(max(progress, 0.0), 100.0), 2)
    return payload


def _build_currency_aware_portfolio(
    pm: PositionManager,
    usd_inr_rate: float,
) -> Dict[str, Any]:
    summary = pm.get_portfolio_summary()
    positions = pm.get_all_positions()
    closed_trades = pm.get_closed_trades()

    breakdown: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "market_value": 0.0,
            "unrealized_pnl": 0.0,
            "realized_pnl": 0.0,
            "market_value_inr": 0.0,
            "unrealized_pnl_inr": 0.0,
            "realized_pnl_inr": 0.0,
            "currency_symbol": "₹",
            "fx_to_inr": 1.0,
        }
    )
    market_breakdown: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "open_positions": 0,
            "closed_trades": 0,
            "market_value_inr": 0.0,
            "unrealized_pnl_inr": 0.0,
            "realized_pnl_inr": 0.0,
            "net_pnl_inr": 0.0,
        }
    )

    for position in positions:
        currency, currency_symbol, fx_to_inr = parse_currency_context(
            position.symbol,
            usd_inr_rate=usd_inr_rate,
        )
        row = breakdown[currency]
        row["currency_symbol"] = currency_symbol
        row["fx_to_inr"] = fx_to_inr
        row["market_value"] += float(position.market_value)
        row["unrealized_pnl"] += float(position.unrealized_pnl)
        row["market_value_inr"] += float(position.market_value) * fx_to_inr
        row["unrealized_pnl_inr"] += float(position.unrealized_pnl) * fx_to_inr

        market = classify_market(position.symbol)
        market_row = market_breakdown[market]
        market_row["open_positions"] += 1
        market_row["market_value_inr"] += float(position.market_value) * fx_to_inr
        market_row["unrealized_pnl_inr"] += float(position.unrealized_pnl) * fx_to_inr

    for trade in closed_trades:
        symbol = str(trade.get("symbol", ""))
        pnl = float(trade.get("pnl", 0.0) or 0.0)
        currency, currency_symbol, fx_to_inr = parse_currency_context(
            symbol,
            usd_inr_rate=usd_inr_rate,
        )
        row = breakdown[currency]
        row["currency_symbol"] = currency_symbol
        row["fx_to_inr"] = fx_to_inr
        row["realized_pnl"] += pnl
        row["realized_pnl_inr"] += pnl * fx_to_inr

        market = classify_market(symbol)
        market_row = market_breakdown[market]
        market_row["closed_trades"] += 1
        market_row["realized_pnl_inr"] += pnl * fx_to_inr

    positions_map = summary.get("positions", {})
    for symbol, row in positions_map.items():
        currency, currency_symbol, fx_to_inr = parse_currency_context(
            symbol,
            usd_inr_rate=usd_inr_rate,
        )
        row["currency"] = currency
        row["currency_symbol"] = currency_symbol
        row["fx_to_inr"] = fx_to_inr
        row["market_value_inr"] = (
            float(row.get("current_price", 0.0))
            * float(row.get("quantity", row.get("qty", 0)))
            * fx_to_inr
        )
        row["unrealized_pnl_inr"] = float(row.get("unrealized_pnl", row.get("pnl", 0.0))) * fx_to_inr

    total_market_value_inr = sum(float(v["market_value_inr"]) for v in breakdown.values())
    total_unrealized_pnl_inr = sum(float(v["unrealized_pnl_inr"]) for v in breakdown.values())
    total_realized_pnl_inr = sum(float(v["realized_pnl_inr"]) for v in breakdown.values())

    summary["currency_breakdown"] = {
        key: {
            k: round(float(value), 2) if isinstance(value, (float, int)) else value
            for k, value in bucket.items()
        }
        for key, bucket in breakdown.items()
    }
    summary["total_market_value_inr"] = round(total_market_value_inr, 2)
    summary["total_unrealized_pnl_inr"] = round(total_unrealized_pnl_inr, 2)
    summary["total_realized_pnl_inr"] = round(total_realized_pnl_inr, 2)
    summary["total_pnl_inr"] = round(total_realized_pnl_inr + total_unrealized_pnl_inr, 2)
    summary["market_breakdown"] = {}
    for base_market in ("NSE", "US", "CRYPTO"):
        market_breakdown[base_market]
    for market, bucket in market_breakdown.items():
        row = dict(bucket)
        row["net_pnl_inr"] = float(row.get("realized_pnl_inr", 0.0)) + float(
            row.get("unrealized_pnl_inr", 0.0)
        )
        summary["market_breakdown"][market] = {
            key: round(float(value), 2) if isinstance(value, (float, int)) else value
            for key, value in row.items()
        }
    summary["base_currency"] = "INR"
    summary["usd_inr_rate"] = float(usd_inr_rate)
    return summary


def _build_trade_pairs(
    orders: List[Order],
    usd_inr_rate: float,
) -> List[TradePairResponse]:
    """Build FIFO-matched trade pairs from filled order flow.

    Unmatched filled entry lots are preserved as open history rows with
    blank exit fields so the UI can show one-way trades immediately.
    """
    ordered = sorted(
        orders,
        key=lambda o: (
            _to_ist_dt(o.filled_at or o.placed_at),
            o.order_id or "",
        ),
    )
    open_lots: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    pairs: List[TradePairResponse] = []
    pair_idx = 1

    for order in ordered:
        fill_qty = int(order.fill_quantity or 0)
        fill_price = float(order.fill_price or order.limit_price or order.market_price_hint or 0.0)
        if fill_qty <= 0 or fill_price <= 0:
            continue

        side = order.side.name
        symbol = order.symbol
        fill_time = _to_ist_dt(order.filled_at or order.placed_at)
        lots = open_lots[symbol]
        remaining = fill_qty

        while remaining > 0 and lots and lots[0]["side"] != side:
            entry_lot = lots[0]
            matched = min(remaining, int(entry_lot["quantity"]))
            remaining -= matched
            entry_lot["quantity"] -= matched

            entry_side = str(entry_lot["side"])
            entry_price = float(entry_lot["price"])
            if entry_side == "BUY":
                pnl = (fill_price - entry_price) * matched
                direction = "LONG"
            else:
                pnl = (entry_price - fill_price) * matched
                direction = "SHORT"

            notional = entry_price * matched
            pnl_pct = (pnl / notional) * 100.0 if notional > 0 else 0.0
            currency, currency_symbol, fx_to_inr = parse_currency_context(
                symbol,
                usd_inr_rate=usd_inr_rate,
            )

            pairs.append(
                TradePairResponse(
                    pair_id=f"pair-{pair_idx:06d}",
                    symbol=symbol,
                    side=direction,
                    quantity=matched,
                    entry_price=entry_price,
                    exit_price=fill_price,
                    pnl=round(pnl, 2),
                    pnl_pct=round(pnl_pct, 2),
                    currency=currency,
                    currency_symbol=currency_symbol,
                    fx_to_inr=fx_to_inr,
                    pnl_inr=round(pnl * fx_to_inr, 2),
                    entry_time=_to_ist_dt(entry_lot.get("time")),
                    exit_time=fill_time,
                    entry_order_id=entry_lot.get("order_id"),
                    exit_order_id=order.order_id,
                    strategy_tag=str(entry_lot.get("tag") or order.tag or ""),
                )
            )
            pair_idx += 1

            if entry_lot["quantity"] <= 0:
                lots.pop(0)

        if remaining > 0:
            lots.append(
                {
                    "side": side,
                    "quantity": remaining,
                    "price": fill_price,
                    "time": fill_time,
                    "order_id": order.order_id,
                    "tag": order.tag,
                }
            )

    for symbol, lots in open_lots.items():
        currency, currency_symbol, fx_to_inr = parse_currency_context(
            symbol,
            usd_inr_rate=usd_inr_rate,
        )
        for lot in lots:
            entry_side = str(lot["side"])
            direction = "LONG" if entry_side == "BUY" else "SHORT"
            pairs.append(
                TradePairResponse(
                    pair_id=f"pair-{pair_idx:06d}",
                    symbol=symbol,
                    side=direction,
                    quantity=int(lot["quantity"]),
                    entry_price=float(lot["price"]),
                    exit_price=None,
                    pnl=0.0,
                    pnl_pct=0.0,
                    currency=currency,
                    currency_symbol=currency_symbol,
                    fx_to_inr=fx_to_inr,
                    pnl_inr=0.0,
                    entry_time=_to_ist_dt(lot.get("time")),
                    exit_time=None,
                    entry_order_id=lot.get("order_id"),
                    exit_order_id=None,
                    strategy_tag=str(lot.get("tag") or ""),
                )
            )
            pair_idx += 1

    return sorted(
        pairs,
        key=lambda p: _to_ist_dt(p.exit_time or p.entry_time),
        reverse=True,
    )


def _to_ist_dt(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=IST)
    if value.tzinfo is None:
        return value.replace(tzinfo=IST)
    return value.astimezone(IST)


def _parse_side(raw: str) -> OrderSide:
    value = raw.strip().upper()
    if value == "BUY":
        return OrderSide.BUY
    if value == "SELL":
        return OrderSide.SELL
    raise HTTPException(status_code=400, detail="side must be BUY or SELL")


def _parse_order_type(raw: str) -> OrderType:
    value = raw.strip().upper().replace("-", "_")
    mapping = {
        "MARKET": OrderType.MARKET,
        "LIMIT": OrderType.LIMIT,
        "STOP": OrderType.STOP,
        "STOP_LIMIT": OrderType.STOP_LIMIT,
        "SL": OrderType.STOP,
        "SL_M": OrderType.STOP,
    }
    if value not in mapping:
        raise HTTPException(
            status_code=400,
            detail="order_type must be one of MARKET, LIMIT, STOP, STOP_LIMIT",
        )
    return mapping[value]


def _parse_product_type(raw: str) -> ProductType:
    value = raw.strip().upper()
    mapping = {
        "INTRADAY": ProductType.INTRADAY,
        "CNC": ProductType.CNC,
        "MARGIN": ProductType.MARGIN,
    }
    if value not in mapping:
        raise HTTPException(status_code=400, detail="product_type must be INTRADAY, CNC, or MARGIN")
    return mapping[value]


def _sync_filled_order_state(
    order: Order,
    pm: PositionManager,
    rm: RiskManager,
    fill_quantity_override: int | None = None,
) -> None:
    """Apply a filled order to position manager + risk manager."""
    if order.status not in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
        return
    if order.fill_price is None:
        return

    fill_qty = fill_quantity_override if fill_quantity_override is not None else order.fill_quantity
    if fill_qty <= 0:
        return

    pos_side = PositionSide.LONG if order.side == OrderSide.BUY else PositionSide.SHORT
    realized_before = pm.total_realized_pnl
    pm.open_position(
        symbol=order.symbol,
        quantity=fill_qty,
        side=pos_side,
        price=float(order.fill_price),
        strategy_tag=order.tag,
        order_id=order.order_id or "",
    )
    realized_delta = pm.total_realized_pnl - realized_before
    if abs(realized_delta) > 1e-9:
        rm.record_trade_result(realized_delta)

    pos = pm.get_position(order.symbol)
    if pos is None:
        rm.sync_position_value(order.symbol, 0.0)
    else:
        rm.sync_position_value(order.symbol, pos.quantity * max(pos.current_price, float(order.fill_price)))
