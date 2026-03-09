"""Trade and order history API routes.

Fetches live order book and trade book from Fyers API.
Falls back to in-memory paper trading data when Fyers is not authenticated.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_fyers_client
from src.config.market_hours import IST
from src.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/history", tags=["history"])


# =========================================================================
# Helpers
# =========================================================================


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _now_ist_iso() -> str:
    return datetime.now(tz=IST).isoformat()


def _to_ist_iso(value: Any) -> str:
    """Best-effort normalize source timestamps into ISO8601 in IST."""
    if value in (None, ""):
        return ""

    dt: datetime | None = None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(float(value), tz=IST)
    else:
        text = str(value).strip()
        if not text:
            return ""
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            for fmt in (
                "%d-%b-%Y %H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
            ):
                try:
                    dt = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            if dt is None:
                return text

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    else:
        dt = dt.astimezone(IST)
    return dt.isoformat()


# =========================================================================
# Endpoints
# =========================================================================


@router.get("/orders")
async def get_order_history() -> dict[str, Any]:
    """Return today's complete order book from Fyers.

    Includes all orders: pending, executed, cancelled, and rejected.
    Returns an empty list with a note when Fyers is not authenticated.
    """
    logger.info("order_history_request")

    try:
        fyers = get_fyers_client()
        if not fyers.is_authenticated:
            return {
                "orders": [],
                "total": 0,
                "note": "Not authenticated with Fyers — showing empty order book",
                "timestamp": _now_ist_iso(),
            }

        raw = await asyncio.to_thread(fyers.get_orders)

        orders_raw = raw.get("orderBook") or raw.get("orders") or []
        orders: list[dict[str, Any]] = []

        for o in orders_raw:
            side_raw = o.get("side", 1)
            # Fyers: 1 = buy, -1 = sell
            side = "BUY" if side_raw == 1 else "SELL"

            status_map = {
                1: "CANCELLED",
                2: "TRADED",
                4: "TRANSIT",
                5: "REJECTED",
                6: "PENDING",
            }
            status_code = o.get("status", 0)
            status = status_map.get(status_code, f"UNKNOWN({status_code})")

            orders.append({
                "order_id": o.get("id", ""),
                "symbol": o.get("symbol", ""),
                "side": side,
                "order_type": o.get("type", ""),
                "product_type": o.get("productType", ""),
                "quantity": _safe_int(o.get("qty")),
                "filled_quantity": _safe_int(o.get("filledQty")),
                "remaining_quantity": _safe_int(o.get("remainingQuantity")),
                "limit_price": _safe_float(o.get("limitPrice")),
                "stop_price": _safe_float(o.get("stopPrice")),
                "fill_price": _safe_float(o.get("tradedPrice")),
                "status": status,
                "status_code": status_code,
                "placed_at": _to_ist_iso(o.get("orderDateTime", "")),
                "message": o.get("message", ""),
                "exchange": o.get("exchange", ""),
                "is_amo": bool(o.get("offlineOrder", False)),
                "tag": o.get("tag", ""),
            })

        # Sort by placed_at descending
        orders.sort(key=lambda x: x.get("placed_at", ""), reverse=True)

        return {
            "orders": orders,
            "total": len(orders),
            "timestamp": _now_ist_iso(),
        }

    except Exception as exc:
        logger.warning("order_history_failed", error=str(exc))
        return {
            "orders": [],
            "total": 0,
            "note": f"Failed to fetch order history: {exc}",
            "timestamp": _now_ist_iso(),
        }


@router.get("/trades")
async def get_trade_history() -> dict[str, Any]:
    """Return today's executed trade book from Fyers.

    Only includes filled (traded) orders with execution details.
    """
    logger.info("trade_history_request")

    try:
        fyers = get_fyers_client()
        if not fyers.is_authenticated:
            return {
                "trades": [],
                "total": 0,
                "total_buy_value": 0.0,
                "total_sell_value": 0.0,
                "net_value": 0.0,
                "note": "Not authenticated with Fyers — showing empty trade book",
                "timestamp": _now_ist_iso(),
            }

        raw = await asyncio.to_thread(fyers.get_tradebook)

        trades_raw = raw.get("tradeBook") or raw.get("trades") or []
        trades: list[dict[str, Any]] = []
        total_buy = 0.0
        total_sell = 0.0

        for t in trades_raw:
            side_raw = t.get("side", 1)
            side = "BUY" if side_raw == 1 else "SELL"
            qty = _safe_int(t.get("tradedQty") or t.get("qty"))
            price = _safe_float(t.get("tradedPrice") or t.get("tradePrice"))
            value = round(qty * price, 2)

            if side == "BUY":
                total_buy += value
            else:
                total_sell += value

            trades.append({
                "trade_id": t.get("tradeId", ""),
                "order_id": t.get("orderNumber", t.get("orderId", "")),
                "symbol": t.get("symbol", ""),
                "exchange": t.get("exchange", ""),
                "side": side,
                "quantity": qty,
                "price": price,
                "value": value,
                "product_type": t.get("productType", ""),
                "order_type": t.get("orderType", t.get("type", "")),
                "traded_at": _to_ist_iso(t.get("orderDateTime", t.get("tradeDate", ""))),
                "exchange_order_id": t.get("exchangeOrderNo", ""),
            })

        # Sort by traded_at descending
        trades.sort(key=lambda x: x.get("traded_at", ""), reverse=True)

        return {
            "trades": trades,
            "total": len(trades),
            "total_buy_value": round(total_buy, 2),
            "total_sell_value": round(total_sell, 2),
            "net_value": round(total_sell - total_buy, 2),
            "timestamp": _now_ist_iso(),
        }

    except Exception as exc:
        logger.warning("trade_history_failed", error=str(exc))
        return {
            "trades": [],
            "total": 0,
            "total_buy_value": 0.0,
            "total_sell_value": 0.0,
            "net_value": 0.0,
            "note": f"Failed to fetch trade history: {exc}",
            "timestamp": _now_ist_iso(),
        }


@router.get("/summary")
async def get_trading_summary() -> dict[str, Any]:
    """Return aggregated trading summary for today.

    Combines order and trade book stats into a dashboard-ready summary.
    """
    logger.info("trading_summary_request")

    try:
        fyers = get_fyers_client()
        if not fyers.is_authenticated:
            return {
                "authenticated": False,
                "note": "Login to Fyers to view live trading summary",
                "timestamp": _now_ist_iso(),
            }

        orders_raw, trades_raw = await asyncio.gather(
            asyncio.to_thread(fyers.get_orders),
            asyncio.to_thread(fyers.get_tradebook),
            return_exceptions=True,
        )

        # Process orders
        order_list = []
        if isinstance(orders_raw, dict):
            order_list = orders_raw.get("orderBook") or orders_raw.get("orders") or []

        total_orders = len(order_list)
        executed = sum(1 for o in order_list if o.get("status") == 2)
        cancelled = sum(1 for o in order_list if o.get("status") == 1)
        pending = sum(1 for o in order_list if o.get("status") in (4, 6))
        rejected = sum(1 for o in order_list if o.get("status") == 5)

        # Process trades
        trade_list = []
        if isinstance(trades_raw, dict):
            trade_list = trades_raw.get("tradeBook") or trades_raw.get("trades") or []

        total_buy = 0.0
        total_sell = 0.0
        for t in trade_list:
            side_raw = t.get("side", 1)
            qty = _safe_int(t.get("tradedQty") or t.get("qty"))
            price = _safe_float(t.get("tradedPrice") or t.get("tradePrice"))
            value = qty * price
            if side_raw == 1:
                total_buy += value
            else:
                total_sell += value

        return {
            "authenticated": True,
            "orders": {
                "total": total_orders,
                "executed": executed,
                "cancelled": cancelled,
                "pending": pending,
                "rejected": rejected,
            },
            "trades": {
                "total": len(trade_list),
                "total_buy_value": round(total_buy, 2),
                "total_sell_value": round(total_sell, 2),
                "net_value": round(total_sell - total_buy, 2),
            },
            "timestamp": _now_ist_iso(),
        }

    except Exception as exc:
        logger.warning("trading_summary_failed", error=str(exc))
        return {
            "authenticated": False,
            "error": str(exc),
            "timestamp": _now_ist_iso(),
        }
