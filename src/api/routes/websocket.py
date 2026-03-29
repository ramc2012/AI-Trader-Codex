"""WebSocket endpoints for real-time dashboard updates.

Provides streaming JSON data for the trading dashboard via
FastAPI's native WebSocket support. Includes a connection manager
for tracking active clients.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select

from src.api.dependencies import (
    get_agent_event_bus,
    get_alert_manager,
    get_order_manager,
    get_position_manager,
    get_risk_manager,
    get_runtime_manager,
    get_tick_aggregator,
    get_state_change_bus,
    get_strategy_executor,
)
from src.api.routes.trading import (
    _build_currency_aware_portfolio,
    _build_trade_pairs,
    _market_is_open,
    _order_to_response,
    _position_exit_metrics,
)
from src.config.constants import INDEX_INSTRUMENTS
from src.config.market_hours import IST
from src.config.settings import get_settings
from src.database.connection import get_session
from src.database.models import IndexOHLC, OptionChain, OptionOHLC
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["WebSocket"])


# =========================================================================
# Connection Manager
# =========================================================================


class ConnectionManager:
    """Manage active WebSocket connections.

    Tracks connected clients and provides broadcast capability.
    """

    def __init__(self) -> None:
        self._connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        self._connections.append(websocket)
        logger.info(
            "websocket_connected",
            total=len(self._connections),
        )

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection from the registry."""
        if websocket in self._connections:
            self._connections.remove(websocket)
        logger.info(
            "websocket_disconnected",
            total=len(self._connections),
        )

    async def send_json(self, websocket: WebSocket, data: Dict[str, Any]) -> None:
        """Send a JSON message to a specific WebSocket."""
        await websocket.send_json(data)

    async def broadcast(self, data: Dict[str, Any]) -> None:
        """Broadcast a JSON message to all connected clients.

        Disconnects clients that raise errors during send.
        """
        disconnected: List[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_json(data)
            except Exception:
                disconnected.append(ws)

        for ws in disconnected:
            self.disconnect(ws)

    @property
    def active_connections(self) -> int:
        """Number of currently active connections."""
        return len(self._connections)


# Shared manager instances
dashboard_manager = ConnectionManager()
tick_manager = ConnectionManager()
options_manager = ConnectionManager()
charts_manager = ConnectionManager()
agent_manager = ConnectionManager()
positions_manager = ConnectionManager()
orders_manager = ConnectionManager()
trades_manager = ConnectionManager()


# =========================================================================
# Payload Builders
# =========================================================================


# Payload builders are defined at the bottom.


# =========================================================================
# WebSocket Endpoints
# =========================================================================


@router.websocket("/ws/dashboard")
async def dashboard_ws(websocket: WebSocket) -> None:
    """Stream dashboard data on state changes."""
    bus = get_state_change_bus()
    queue = bus.subscribe()
    await dashboard_manager.connect(websocket)
    logger.info("websocket_connected", type="dashboard", client=websocket.client.host if websocket.client else "unknown")
    try:
        # Initial push
        payload = _build_dashboard_payload()
        await dashboard_manager.send_json(websocket, payload)

        while True:
            try:
                # Wait for ANY state change (portfolio, risk, alerts)
                # or timeout after 5s for a heartbeat/periodic sync
                topic = await asyncio.wait_for(queue.get(), timeout=5.0)
                if topic in ("portfolio", "risk", "alerts"):
                    payload = _build_dashboard_payload()
                    await dashboard_manager.send_json(websocket, payload)
            except asyncio.TimeoutError:
                # Periodic heartbeat/sync
                payload = _build_dashboard_payload()
                await dashboard_manager.send_json(websocket, payload)
    except WebSocketDisconnect:
        dashboard_manager.disconnect(websocket)
        logger.info("websocket_disconnected", type="dashboard")
    except Exception as e:
        logger.error("websocket_error", type="dashboard", error=str(e))
        dashboard_manager.disconnect(websocket)
    finally:
        bus.unsubscribe(queue)


@router.websocket("/ws/positions")
async def positions_ws(websocket: WebSocket) -> None:
    """Stream live position updates."""
    bus = get_state_change_bus()
    queue = bus.subscribe()
    pm = get_position_manager()
    await websocket.accept()
    try:
        # Initial push
        await websocket.send_json({
            "type": "positions_update",
            "timestamp": datetime.now(tz=IST).isoformat(),
            "positions": [p.__dict__ for p in pm.get_all_positions()],
        })

        while True:
            try:
                topic = await asyncio.wait_for(queue.get(), timeout=10.0)
                if topic == "positions":
                    await websocket.send_json({
                        "type": "positions_update",
                        "timestamp": datetime.now(tz=IST).isoformat(),
                        "positions": [p.__dict__ for p in pm.get_all_positions()],
                    })
            except asyncio.TimeoutError:
                # Heartbeat
                await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(queue)


@router.websocket("/ws/orders")
async def orders_ws(websocket: WebSocket) -> None:
    """Stream all orders on state changes."""
    bus = get_state_change_bus()
    queue = bus.subscribe()
    await orders_manager.connect(websocket)
    logger.info("websocket_connected", type="orders", client=websocket.client.host if websocket.client else "unknown")
    try:
        # Initial push
        payload = _build_orders_payload()
        await orders_manager.send_json(websocket, payload)

        while True:
            try:
                topic = await asyncio.wait_for(queue.get(), timeout=5.0)
                if topic == "orders":
                    payload = _build_orders_payload()
                    await orders_manager.send_json(websocket, payload)
            except asyncio.TimeoutError:
                # Heartbeat
                await orders_manager.send_json(websocket, {"type": "heartbeat"})
    except WebSocketDisconnect:
        orders_manager.disconnect(websocket)
        logger.info("websocket_disconnected", type="orders")
    except Exception as e:
        logger.error("websocket_error", type="orders", error=str(e))
        orders_manager.disconnect(websocket)
    finally:
        bus.unsubscribe(queue)


@router.websocket("/ws/trades")
async def trades_ws(websocket: WebSocket) -> None:
    """Stream matched trade pairs on order activity."""
    bus = get_state_change_bus()
    queue = bus.subscribe()
    await trades_manager.connect(websocket)
    logger.info("websocket_connected", type="trades", client=websocket.client.host if websocket.client else "unknown")
    try:
        # Initial push
        payload = _build_trades_payload()
        await trades_manager.send_json(websocket, payload)

        while True:
            try:
                topic = await asyncio.wait_for(queue.get(), timeout=5.0)
                if topic == "orders":  # Both use orders trigger
                    payload = _build_trades_payload()
                    await trades_manager.send_json(websocket, payload)
            except asyncio.TimeoutError:
                # Heartbeat
                await trades_manager.send_json(websocket, {"type": "heartbeat"})
    except WebSocketDisconnect:
        trades_manager.disconnect(websocket)
        logger.info("websocket_disconnected", type="trades")
    except Exception as e:
        logger.error("websocket_error", type="trades", error=str(e))
        trades_manager.disconnect(websocket)
    finally:
        bus.unsubscribe(queue)


@router.websocket("/ws/ticks/{symbol:path}")
async def tick_ws(websocket: WebSocket, symbol: str) -> None:
    """Stream live tick data for a symbol."""
    runtime = get_runtime_manager()
    if not runtime.is_running:
        await runtime.start()

    topic = symbol if symbol != "all" else "*"
    queue = runtime.broker.subscribe(topic)
    await tick_manager.connect(websocket)
    try:
        latest = runtime.broker.latest(symbol)
        if latest:
            await tick_manager.send_json(websocket, latest)
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                payload = {
                    "type": "heartbeat",
                    "symbol": symbol,
                    "timestamp": datetime.now(tz=IST).isoformat(),
                    "message": "waiting_for_tick",
                }
            await tick_manager.send_json(websocket, payload)
    except WebSocketDisconnect:
        runtime.broker.unsubscribe(topic, queue)
        tick_manager.disconnect(websocket)
    except Exception:
        runtime.broker.unsubscribe(topic, queue)
        tick_manager.disconnect(websocket)


@router.websocket("/ws/options/{underlying:path}")
async def options_chain_ws(websocket: WebSocket, underlying: str) -> None:
    """Stream incremental option-chain snapshots for one underlying."""
    await options_manager.connect(websocket)
    resolved_underlying = underlying
    key = underlying.upper()
    if ":" not in underlying and key in INDEX_INSTRUMENTS:
        resolved_underlying = INDEX_INSTRUMENTS[key].spot_symbol

    last_timestamp = None
    try:
        while True:
            async with get_session() as session:
                latest_ts_stmt = (
                    select(func.max(OptionChain.timestamp))
                    .where(OptionChain.underlying == resolved_underlying)
                )
                latest_ts = (await session.execute(latest_ts_stmt)).scalar_one_or_none()
                if latest_ts and latest_ts != last_timestamp:
                    rows_stmt = (
                        select(OptionChain)
                        .where(
                            OptionChain.underlying == resolved_underlying,
                            OptionChain.timestamp == latest_ts,
                        )
                        .order_by(OptionChain.strike, OptionChain.option_type)
                    )
                    rows = (await session.execute(rows_stmt)).scalars().all()
                    await options_manager.send_json(
                        websocket,
                        {
                            "type": "option_chain_patch",
                            "underlying": resolved_underlying,
                            "timestamp": latest_ts.isoformat(),
                            "rows": [row.to_dict() for row in rows],
                        },
                    )
                    last_timestamp = latest_ts
                else:
                    await options_manager.send_json(
                        websocket,
                        {
                            "type": "heartbeat",
                            "underlying": resolved_underlying,
                            "timestamp": datetime.now(tz=IST).isoformat(),
                        },
                    )
            await asyncio.sleep(2.0)
    except WebSocketDisconnect:
        options_manager.disconnect(websocket)
    except Exception:
        options_manager.disconnect(websocket)


@router.websocket("/ws/charts/{instrument:path}")
async def charts_ws(websocket: WebSocket, instrument: str) -> None:
    """Stream incremental latest candle updates for index/option symbols."""
    await charts_manager.connect(websocket)
    timeframe = websocket.query_params.get("timeframe", "15")
    last_ts = None
    try:
        while True:
            async with get_session() as session:
                if instrument.startswith(("NSE:", "BSE:")) and ("CE" in instrument or "PE" in instrument):
                    stmt = (
                        select(OptionOHLC)
                        .where(
                            OptionOHLC.symbol == instrument,
                            OptionOHLC.timeframe == timeframe,
                        )
                        .order_by(OptionOHLC.timestamp.desc())
                        .limit(1)
                    )
                    latest = (await session.execute(stmt)).scalars().first()
                else:
                    stmt = (
                        select(IndexOHLC)
                        .where(
                            IndexOHLC.symbol == instrument,
                            IndexOHLC.timeframe == timeframe,
                        )
                        .order_by(IndexOHLC.timestamp.desc())
                        .limit(1)
                    )
                    latest = (await session.execute(stmt)).scalars().first()

                if latest and latest.timestamp != last_ts:
                    await charts_manager.send_json(
                        websocket,
                        {
                            "type": "chart_patch",
                            "instrument": instrument,
                            "timeframe": timeframe,
                            "candle": {
                                "timestamp": latest.timestamp.isoformat(),
                                "open": float(latest.open),
                                "high": float(latest.high),
                                "low": float(latest.low),
                                "close": float(latest.close),
                                "volume": int(latest.volume),
                            },
                        },
                    )
                    last_ts = latest.timestamp
                else:
                    await charts_manager.send_json(
                        websocket,
                        {
                            "type": "heartbeat",
                            "instrument": instrument,
                            "timeframe": timeframe,
                            "timestamp": datetime.now(tz=IST).isoformat(),
                        },
                    )
            await asyncio.sleep(2.0)
    except WebSocketDisconnect:
        charts_manager.disconnect(websocket)
    except Exception:
        charts_manager.disconnect(websocket)


@router.websocket("/ws/orderflow/{symbol:path}")
async def orderflow_ws(websocket: WebSocket, symbol: str) -> None:
    """Stream real-time footprint bar updates for a symbol.

    Query params:
        bar_minutes: bar resolution in minutes (default 5)

    Each message:
        { "type": "orderflow_update", "bar": { ... FootprintBar fields ... } }
    or heartbeat if no ticks in 5s.
    """
    bar_minutes = int(websocket.query_params.get("bar_minutes", "5"))
    aggregator = get_tick_aggregator()

    # Start aggregator if not yet running
    if not aggregator._running:
        await aggregator.start()

    queue = aggregator.subscribe(symbol, bar_minutes)
    await websocket.accept()

    try:
        # Prime from latest tick so UI can render immediately after connect.
        aggregator.prime_from_latest(symbol)
        await websocket.send_json({
            "type": "orderflow_snapshot",
            "symbol": symbol,
            "bar_minutes": bar_minutes,
            "bars": aggregator.get_history(symbol, bar_minutes, count=100),
        })

        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=5.0)
                await websocket.send_json(payload)
            except asyncio.TimeoutError:
                await websocket.send_json({
                    "type": "heartbeat",
                    "symbol": symbol,
                    "timestamp": datetime.now(tz=IST).isoformat(),
                })
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        aggregator.unsubscribe(symbol, bar_minutes, queue)


@router.websocket("/ws/agent")
async def agent_ws(websocket: WebSocket) -> None:
    """Stream real-time AI agent events.

    Subscribes to the AgentEventBus and forwards all events to
    connected WebSocket clients as they occur.
    """
    event_bus = get_agent_event_bus()
    queue = event_bus.subscribe()
    await agent_manager.connect(websocket)
    logger.info("websocket_connected", type="agent", client=websocket.client.host if websocket.client else "unknown")
    try:
        # Initial push (no specific initial state, just heartbeat to confirm)
        await agent_manager.send_json(websocket, {
            "type": "heartbeat",
            "timestamp": datetime.now(tz=IST).isoformat(),
            "message": "Agent event stream connected"
        })

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=5.0)
                await agent_manager.send_json(websocket, event.to_ws_payload())
            except asyncio.TimeoutError:
                # Send heartbeat to keep connection alive
                await agent_manager.send_json(websocket, {
                    "type": "heartbeat",
                    "timestamp": datetime.now(tz=IST).isoformat(),
                })
    except WebSocketDisconnect:
        event_bus.unsubscribe(queue)
        agent_manager.disconnect(websocket)
        logger.info("websocket_disconnected", type="agent")
    except Exception as e:
        logger.error("websocket_error", type="agent", error=str(e))
        event_bus.unsubscribe(queue)
        agent_manager.disconnect(websocket)


# =========================================================================
# Payload Builder
# =========================================================================


def _build_dashboard_payload() -> Dict[str, Any]:
    """Build the dashboard WebSocket payload from current manager state.

    Returns:
        Dictionary with portfolio, risk, and alert data.
    """
    try:
        pm = get_position_manager()
        settings = get_settings()
        portfolio = _build_currency_aware_portfolio(
            pm=pm,
            usd_inr_rate=float(settings.usd_inr_reference_rate),
        )
    except Exception:
        portfolio = {
            "position_count": 0,
            "total_market_value": 0.0,
            "total_unrealized_pnl": 0.0,
            "total_realized_pnl": 0.0,
            "total_pnl": 0.0,
            "total_market_value_inr": 0.0,
            "total_unrealized_pnl_inr": 0.0,
            "total_realized_pnl_inr": 0.0,
            "total_pnl_inr": 0.0,
            "base_currency": "INR",
            "usd_inr_rate": 0.0,
            "currency_breakdown": {},
            "market_breakdown": {},
            "positions": {},
        }

    try:
        rm = get_risk_manager()
        risk = rm.get_risk_summary()
    except Exception:
        risk = {
            "circuit_breaker_triggered": False,
            "emergency_stop": False,
            "available_risk": 0.0,
        }

    try:
        am = get_alert_manager()
        alert_counts = am.get_alert_counts()
    except Exception:
        alert_counts = {
            "info": 0,
            "warning": 0,
            "critical": 0,
            "emergency": 0,
        }

    try:
        se = get_strategy_executor()
        strategies = se.get_executor_summary()
    except Exception:
        strategies = {
            "enabled_count": 0,
            "total_signals": 0,
            "total_trades": 0,
            "active_strategies": [],
        }

    return {
        "type": "dashboard_update",
        "timestamp": datetime.now(tz=IST).isoformat(),
        "portfolio": portfolio,
        "risk": risk,
        "alerts": alert_counts,
        "strategies": strategies,
        "equity_snapshot": {
            "time": datetime.now(tz=IST).isoformat(),
            "value": portfolio.get("total_market_value_inr", portfolio.get("total_market_value", 0))
            if isinstance(portfolio, dict)
            else 0,
        },
        "ws_connections": dashboard_manager.active_connections,
    }
def _build_positions_payload() -> Dict[str, Any]:
    """Build the positions WebSocket payload from current state."""
    try:
        pm = get_position_manager()
        se = get_strategy_executor()
        settings = get_settings()
        usd_inr_rate = float(settings.usd_inr_reference_rate)
        now = datetime.now(tz=IST)
        
        positions = pm.get_all_positions()
        out_positions = []
        
        for position in positions:
            currency, currency_symbol, fx_to_inr = _parse_currency_info(position.symbol, usd_inr_rate)
            market = _classify_market_info(position.symbol)
            # In a real app we'd get the plan from the agent, but for now we'll try to find it
            # if we can't we'll just send empty metrics. 
            # Actually, let's just use empty metrics if we can't easily get the plan here
            # to avoid circular dependencies with the agent.
            exit_metrics = {
                "stop_loss": None, "target": None, "time_exit_at": None,
                "time_left_seconds": None, "distance_to_stop_pct": None,
                "distance_to_target_pct": None, "progress_to_target_pct": None
            }
            
            out_positions.append({
                "symbol": position.symbol,
                "market": market,
                "market_open": _market_is_open(market, now),
                "quantity": position.quantity,
                "side": position.side.value,
                "avg_price": position.avg_price,
                "current_price": position.current_price,
                "entry_time": position.entry_time.isoformat() if position.entry_time else None,
                "strategy_tag": position.strategy_tag,
                "order_ids": list(position.order_ids),
                "unrealized_pnl": position.unrealized_pnl,
                "unrealized_pnl_pct": position.unrealized_pnl_pct,
                "market_value": position.market_value,
                "is_profitable": position.is_profitable,
                "currency": currency,
                "currency_symbol": currency_symbol,
                "fx_to_inr": fx_to_inr,
                "unrealized_pnl_inr": position.unrealized_pnl * fx_to_inr,
                "market_value_inr": position.market_value * fx_to_inr,
                **exit_metrics
            })
            
        return {
            "type": "positions_update",
            "timestamp": now.isoformat(),
            "positions": out_positions
        }
    except Exception as e:
        logger.error("error_building_positions_payload", error=str(e))
        return {
            "type": "positions_update",
            "timestamp": datetime.now(tz=IST).isoformat(),
            "positions": []
        }

def _parse_currency_info(symbol: str, usd_inr_rate: float):
    from src.utils.market_symbols import parse_currency_context
    return parse_currency_context(symbol, usd_inr_rate)

def _build_orders_payload() -> Dict[str, Any]:
    """Build the orders WebSocket payload."""
    try:
        om = get_order_manager()
        orders = om.get_all_orders()
        return {
            "type": "orders_update",
            "timestamp": datetime.now(tz=IST).isoformat(),
            "orders": [_order_to_response(o).dict() for o in orders]
        }
    except Exception as e:
        logger.error("error_building_orders_payload", error=str(e))
        return {"type": "orders_update", "orders": []}

def _build_trades_payload() -> Dict[str, Any]:
    """Build the trades ( FIFO matched pairs) WebSocket payload."""
    try:
        om = get_order_manager()
        settings = get_settings()
        usd_inr_rate = float(settings.usd_inr_reference_rate)
        pairs = _build_trade_pairs(
            orders=om.get_all_orders(),
            usd_inr_rate=usd_inr_rate,
        )
        return {
            "type": "trades_update",
            "timestamp": datetime.now(tz=IST).isoformat(),
            "trades": [p.dict() for p in pairs]
        }
    except Exception as e:
        logger.error("error_building_trades_payload", error=str(e))
        return {"type": "trades_update", "trades": []}
