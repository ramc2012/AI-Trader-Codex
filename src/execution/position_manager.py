"""Position management - track open positions and P&L.

Manages the lifecycle of trading positions including opening, closing,
averaging, flipping, and real-time P&L tracking. Supports both long
and short positions with partial close and position flip semantics.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.config.settings import get_settings
from src.config.market_hours import IST
from src.utils.logger import get_logger

logger = get_logger(__name__)
MULTI_STRATEGY_TAG = "MULTI"


class PositionSide(Enum):
    """Side of a position."""

    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


@dataclass
class PositionLot:
    """One strategy-owned slice inside a consolidated symbol position."""

    quantity: int
    entry_price: float
    entry_time: Optional[datetime] = None
    strategy_tag: str = ""
    order_ids: List[str] = field(default_factory=list)


@dataclass
class Position:
    """Represents an open position.

    Attributes:
        symbol: Trading symbol (e.g., 'NSE:NIFTY50-INDEX').
        quantity: Number of units held.
        side: Long, short, or flat.
        avg_price: Volume-weighted average entry price.
        current_price: Latest market price for P&L calculation.
        entry_time: Timestamp when the position was first opened.
        strategy_tag: Strategy that originated this position.
        order_ids: List of order IDs that contributed to this position.
    """

    symbol: str
    quantity: int
    side: PositionSide
    avg_price: float
    current_price: float = 0.0
    entry_time: Optional[datetime] = None
    strategy_tag: str = ""
    order_ids: List[str] = field(default_factory=list)
    lots: List[PositionLot] = field(default_factory=list)

    @property
    def unrealized_pnl(self) -> float:
        """Calculate unrealized P&L based on current price."""
        if self.side == PositionSide.LONG:
            return (self.current_price - self.avg_price) * self.quantity
        elif self.side == PositionSide.SHORT:
            return (self.avg_price - self.current_price) * self.quantity
        return 0.0

    @property
    def unrealized_pnl_pct(self) -> float:
        """Calculate unrealized P&L as a percentage of entry value."""
        if self.avg_price == 0 or self.quantity == 0:
            return 0.0
        return (self.unrealized_pnl / (self.avg_price * self.quantity)) * 100

    @property
    def market_value(self) -> float:
        """Current market value of the position."""
        return self.current_price * self.quantity

    @property
    def is_profitable(self) -> bool:
        """Whether the position is currently in profit."""
        return self.unrealized_pnl > 0


class PositionManager:
    """Track and manage open positions.

    Handles position lifecycle including opening, closing, averaging,
    and flipping. Tracks both realized and unrealized P&L.
    """

    def __init__(self, state_path: Path | str | None = None) -> None:
        self._positions: Dict[str, Position] = {}
        self._closed_positions: List[Dict[str, Any]] = []
        self._total_realized_pnl: float = 0.0
        if state_path is not None:
            self._state_path: Path | None = Path(state_path)
        elif os.environ.get("PYTEST_CURRENT_TEST"):
            self._state_path = None
        else:
            self._state_path = get_settings().data_path / "position_manager_state.json"
        self._load_state()
        logger.info("position_manager_initialized")

    @staticmethod
    def _lot_order_key(lot: PositionLot) -> datetime:
        if lot.entry_time is None:
            return datetime.min.replace(tzinfo=IST)
        if lot.entry_time.tzinfo is None:
            return lot.entry_time.replace(tzinfo=IST)
        return lot.entry_time.astimezone(IST)

    @classmethod
    def _normalized_lots(cls, position: Position) -> List[PositionLot]:
        if position.lots:
            lots = [lot for lot in position.lots if int(lot.quantity) > 0]
            return sorted(lots, key=cls._lot_order_key)
        if position.quantity <= 0:
            return []
        return [
            PositionLot(
                quantity=int(position.quantity),
                entry_price=float(position.avg_price),
                entry_time=position.entry_time,
                strategy_tag=str(position.strategy_tag or ""),
                order_ids=list(position.order_ids),
            )
        ]

    @staticmethod
    def _collapse_strategy_tag(lots: List[PositionLot]) -> str:
        tags = {str(lot.strategy_tag or "").strip() for lot in lots if int(lot.quantity) > 0}
        tags.discard("")
        if not tags:
            return ""
        if len(tags) == 1:
            return next(iter(tags))
        return MULTI_STRATEGY_TAG

    @staticmethod
    def _merge_order_ids(lots: List[PositionLot]) -> List[str]:
        merged: List[str] = []
        seen: set[str] = set()
        for lot in lots:
            for order_id in lot.order_ids:
                token = str(order_id or "").strip()
                if not token or token in seen:
                    continue
                seen.add(token)
                merged.append(token)
        return merged

    @classmethod
    def _recalculate_position(cls, position: Position) -> None:
        lots = cls._normalized_lots(position)
        position.lots = lots
        if not lots:
            position.quantity = 0
            position.avg_price = 0.0
            position.entry_time = None
            position.strategy_tag = ""
            position.order_ids = []
            return

        total_qty = sum(int(lot.quantity) for lot in lots)
        weighted_cost = sum(float(lot.entry_price) * int(lot.quantity) for lot in lots)
        position.quantity = int(total_qty)
        position.avg_price = weighted_cost / max(total_qty, 1)
        entry_times = [cls._lot_order_key(lot) for lot in lots]
        position.entry_time = min(entry_times) if entry_times else None
        position.strategy_tag = cls._collapse_strategy_tag(lots)
        position.order_ids = cls._merge_order_ids(lots)

    @classmethod
    def _build_position_view(
        cls,
        symbol: str,
        side: PositionSide,
        current_price: float,
        lots: List[PositionLot],
    ) -> Position:
        view = Position(
            symbol=symbol,
            quantity=0,
            side=side,
            avg_price=0.0,
            current_price=current_price,
            lots=[
                PositionLot(
                    quantity=int(lot.quantity),
                    entry_price=float(lot.entry_price),
                    entry_time=lot.entry_time,
                    strategy_tag=str(lot.strategy_tag or ""),
                    order_ids=list(lot.order_ids),
                )
                for lot in lots
            ],
        )
        cls._recalculate_position(view)
        return view

    def open_position(
        self,
        symbol: str,
        quantity: int,
        side: PositionSide,
        price: float,
        strategy_tag: str = "",
        order_id: str = "",
    ) -> Position:
        """Open or add to a position.

        If same direction as existing position, averages the entry price.
        If opposite direction, reduces, closes, or flips the position.

        Args:
            symbol: Trading symbol.
            quantity: Number of units.
            side: Long or short.
            price: Entry price.
            strategy_tag: Strategy identifier.
            order_id: Associated order ID.

        Returns:
            The resulting Position object.
        """
        if symbol in self._positions:
            existing = self._positions[symbol]
            existing.lots = self._normalized_lots(existing)

            if existing.side == side:
                existing.lots.append(
                    PositionLot(
                        quantity=int(quantity),
                        entry_price=float(price),
                        entry_time=datetime.now(tz=IST),
                        strategy_tag=str(strategy_tag or ""),
                        order_ids=[order_id] if order_id else [],
                    )
                )
                existing.current_price = price
                self._recalculate_position(existing)
                logger.info(
                    "position_averaged",
                    symbol=symbol,
                    side=side.value,
                    new_qty=existing.quantity,
                    new_avg=existing.avg_price,
                )
                self._persist_state()
                return existing
            else:
                if quantity < existing.quantity:
                    self.close_position(symbol, price, quantity=quantity)
                    remaining = self.get_position(symbol)
                    if remaining is not None:
                        return remaining
                    return Position(symbol=symbol, quantity=0, side=PositionSide.FLAT, avg_price=0.0, current_price=price)
                elif quantity == existing.quantity:
                    self.close_position(symbol, price, quantity=quantity)
                    return Position(
                        symbol=symbol,
                        quantity=0,
                        side=PositionSide.FLAT,
                        avg_price=0.0,
                        current_price=price,
                    )
                else:
                    existing_qty = int(existing.quantity)
                    close_pnl = self.close_position(symbol, price, quantity=existing_qty)
                    remaining_qty = quantity - existing_qty
                    new_pos = Position(
                        symbol=symbol,
                        quantity=remaining_qty,
                        side=side,
                        avg_price=price,
                        current_price=price,
                        entry_time=datetime.now(tz=IST),
                        strategy_tag=strategy_tag,
                        order_ids=[order_id] if order_id else [],
                        lots=[
                            PositionLot(
                                quantity=int(remaining_qty),
                                entry_price=float(price),
                                entry_time=datetime.now(tz=IST),
                                strategy_tag=str(strategy_tag or ""),
                                order_ids=[order_id] if order_id else [],
                            )
                        ],
                    )
                    self._recalculate_position(new_pos)
                    self._positions[symbol] = new_pos
                    logger.info(
                        "position_flipped",
                        symbol=symbol,
                        new_side=side.value,
                        new_qty=remaining_qty,
                        close_pnl=close_pnl,
                    )
                    self._persist_state()
                    return new_pos
        else:
            # New position
            pos = Position(
                symbol=symbol,
                quantity=quantity,
                side=side,
                avg_price=price,
                current_price=price,
                entry_time=datetime.now(tz=IST),
                strategy_tag=strategy_tag,
                order_ids=[order_id] if order_id else [],
                lots=[
                    PositionLot(
                        quantity=int(quantity),
                        entry_price=float(price),
                        entry_time=datetime.now(tz=IST),
                        strategy_tag=str(strategy_tag or ""),
                        order_ids=[order_id] if order_id else [],
                    )
                ],
            )
            self._recalculate_position(pos)
            self._positions[symbol] = pos
            logger.info(
                "position_opened",
                symbol=symbol,
                side=side.value,
                quantity=quantity,
                price=price,
            )
            self._persist_state()
            return pos

    def close_position(
        self,
        symbol: str,
        price: float,
        quantity: Optional[int] = None,
        strategy_tag: Optional[str] = None,
    ) -> float:
        """Close a position (fully or partially).

        Args:
            symbol: Trading symbol to close.
            price: Exit price.
            quantity: Number of units to close. Defaults to full position.

        Returns:
            Realized P&L from the close.

        Raises:
            ValueError: If no position exists or quantity exceeds held units.
        """
        if symbol not in self._positions:
            raise ValueError(f"No position found for {symbol}")

        pos = self._positions[symbol]
        pos.lots = self._normalized_lots(pos)

        eligible_qty = sum(
            int(lot.quantity)
            for lot in pos.lots
            if strategy_tag is None or lot.strategy_tag == strategy_tag
        )
        close_qty = quantity if quantity is not None else eligible_qty

        if eligible_qty <= 0 or close_qty <= 0:
            raise ValueError(f"No position quantity found for {symbol}")

        if close_qty > eligible_qty:
            raise ValueError(
                f"Cannot close {close_qty} units; only {eligible_qty} held"
            )

        realized = 0.0
        remaining = int(close_qty)
        kept_lots: List[PositionLot] = []
        closed_at = datetime.now(tz=IST)
        for lot in pos.lots:
            if remaining <= 0 or (strategy_tag is not None and lot.strategy_tag != strategy_tag):
                kept_lots.append(lot)
                continue

            matched = min(int(lot.quantity), remaining)
            if matched > 0:
                pnl = self._calc_pnl(pos.side, float(lot.entry_price), price, matched)
                realized += pnl
                self._closed_positions.append(
                    {
                        "symbol": symbol,
                        "side": pos.side.value,
                        "quantity": matched,
                        "entry_price": float(lot.entry_price),
                        "exit_price": price,
                        "pnl": pnl,
                        "closed_at": closed_at,
                        "strategy_tag": str(lot.strategy_tag or ""),
                    }
                )
                lot.quantity -= matched
                remaining -= matched

            if int(lot.quantity) > 0:
                kept_lots.append(lot)

        self._total_realized_pnl += realized
        pos.lots = kept_lots
        if not kept_lots:
            pos.quantity = 0
            pos.avg_price = 0.0
            pos.entry_time = None
            pos.strategy_tag = ""
            pos.order_ids = []
        self._recalculate_position(pos)

        if pos.quantity <= 0:
            del self._positions[symbol]
            logger.info(
                "position_closed",
                symbol=symbol,
                pnl=realized,
            )
        else:
            logger.info(
                "position_partially_closed",
                symbol=symbol,
                closed_qty=close_qty,
                remaining_qty=pos.quantity,
                pnl=realized,
            )
        self._persist_state()

        return realized

    def update_price(self, symbol: str, price: float) -> Optional[Position]:
        """Update the current market price for a position.

        Args:
            symbol: Trading symbol.
            price: Latest market price.

        Returns:
            The updated Position, or None if no position exists.
        """
        if symbol in self._positions:
            self._positions[symbol].current_price = price
            self._persist_state()
            return self._positions[symbol]
        return None

    def update_prices(self, prices: Dict[str, float]) -> None:
        """Bulk update prices for multiple symbols.

        Args:
            prices: Mapping of symbol to latest price.
        """
        for symbol, price in prices.items():
            self.update_price(symbol, price)

    def get_position(self, symbol: str) -> Optional[Position]:
        """Get a position by symbol.

        Args:
            symbol: Trading symbol.

        Returns:
            The Position if found, otherwise None.
        """
        return self._positions.get(symbol)

    def get_all_positions(self) -> List[Position]:
        """Get all open positions.

        Returns:
            List of all open Position objects.
        """
        return list(self._positions.values())

    def get_positions_by_tag(self, tag: str) -> List[Position]:
        """Get positions filtered by strategy tag.

        Args:
            tag: Strategy tag to filter by.

        Returns:
            List of positions matching the tag.
        """
        return self.get_position_views(strategy_tag=tag)

    def get_position_views(
        self,
        *,
        symbol: Optional[str] = None,
        strategy_tag: Optional[str] = None,
    ) -> List[Position]:
        """Return strategy-scoped views derived from consolidated symbol positions."""
        views: List[Position] = []
        for pos in self._positions.values():
            if symbol is not None and pos.symbol != symbol:
                continue
            lots = self._normalized_lots(pos)
            grouped: Dict[str, List[PositionLot]] = {}
            for lot in lots:
                tag = str(lot.strategy_tag or "")
                if strategy_tag is not None and tag != strategy_tag:
                    continue
                grouped.setdefault(tag, []).append(lot)
            for group_lots in grouped.values():
                views.append(self._build_position_view(pos.symbol, pos.side, pos.current_price, group_lots))
        return views

    @property
    def total_unrealized_pnl(self) -> float:
        """Sum of unrealized P&L across all open positions."""
        return sum(p.unrealized_pnl for p in self._positions.values())

    @property
    def total_realized_pnl(self) -> float:
        """Total realized P&L from all closed trades."""
        return self._total_realized_pnl

    @property
    def total_pnl(self) -> float:
        """Total P&L (realized + unrealized)."""
        return self.total_realized_pnl + self.total_unrealized_pnl

    @property
    def total_market_value(self) -> float:
        """Total market value of all open positions."""
        return sum(p.market_value for p in self._positions.values())

    @property
    def position_count(self) -> int:
        """Number of open positions."""
        return len(self._positions)

    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Get a summary of all positions and P&L.

        Returns:
            Dictionary with portfolio metrics and per-position details.
        """
        return {
            "position_count": self.position_count,
            "total_market_value": self.total_market_value,
            "total_unrealized_pnl": self.total_unrealized_pnl,
            "total_realized_pnl": self.total_realized_pnl,
            "total_pnl": self.total_pnl,
            "positions": {
                s: {
                    # Canonical keys used by API/agent.
                    "quantity": p.quantity,
                    "avg_price": p.avg_price,
                    "current_price": p.current_price,
                    "unrealized_pnl": p.unrealized_pnl,
                    "unrealized_pnl_pct": p.unrealized_pnl_pct,
                    # Backward-compatible aliases retained for existing callers.
                    "qty": p.quantity,
                    "side": p.side.value,
                    "avg": p.avg_price,
                    "current": p.current_price,
                    "pnl": p.unrealized_pnl,
                }
                for s, p in self._positions.items()
            },
        }

    def format_position_summary(self, max_items: int = 5) -> str:
        """Return a compact multi-line summary for Telegram/status views."""
        positions = sorted(
            self._positions.values(),
            key=lambda position: (abs(position.unrealized_pnl), position.symbol),
            reverse=True,
        )
        if not positions:
            return "• None"

        capped = max(int(max_items), 1)
        lines: list[str] = []
        for position in positions[:capped]:
            symbol = position.symbol.split(":")[-1].split("-")[0]
            lines.append(
                f"• {symbol} {position.side.value.upper()} x{position.quantity} "
                f"avg {position.avg_price:,.2f} P&L {position.unrealized_pnl:+,.2f}"
            )

        remaining = len(positions) - capped
        if remaining > 0:
            lines.append(f"• +{remaining} more position(s)")
        return "\n".join(lines)

    def get_closed_trades(self) -> List[Dict[str, Any]]:
        """Get history of all closed trades.

        Returns:
            List of dictionaries with closed trade details.
        """
        return list(self._closed_positions)

    def replace_positions(
        self,
        positions: List[Position],
        *,
        total_realized_pnl: Optional[float] = None,
        persist: bool = True,
    ) -> None:
        """Replace the current open-position book with a recovered snapshot."""
        self._positions = {}
        for position in positions:
            if int(position.quantity) <= 0:
                continue
            normalized = Position(
                symbol=str(position.symbol),
                quantity=int(position.quantity),
                side=position.side,
                avg_price=float(position.avg_price),
                current_price=float(position.current_price),
                entry_time=position.entry_time,
                strategy_tag=str(position.strategy_tag or ""),
                order_ids=list(position.order_ids),
                lots=[
                    PositionLot(
                        quantity=int(lot.quantity),
                        entry_price=float(lot.entry_price),
                        entry_time=lot.entry_time,
                        strategy_tag=str(lot.strategy_tag or ""),
                        order_ids=list(lot.order_ids),
                    )
                    for lot in self._normalized_lots(position)
                ],
            )
            self._recalculate_position(normalized)
            self._positions[normalized.symbol] = normalized
        if total_realized_pnl is not None:
            self._total_realized_pnl = float(total_realized_pnl)
        if persist:
            self._persist_state()

    @staticmethod
    def _calc_pnl(
        side: PositionSide, entry: float, exit_price: float, qty: int
    ) -> float:
        """Calculate P&L for a trade.

        Args:
            side: Position side (long or short).
            entry: Entry price.
            exit_price: Exit price.
            qty: Number of units.

        Returns:
            Realized P&L amount.
        """
        if side == PositionSide.LONG:
            return (exit_price - entry) * qty
        elif side == PositionSide.SHORT:
            return (entry - exit_price) * qty
        return 0.0

    def _persist_state(self) -> None:
        if self._state_path is None:
            return
        try:
            payload = {
                "total_realized_pnl": float(self._total_realized_pnl),
                "positions": [self._serialize_position(pos) for pos in self.get_all_positions()],
                "closed_positions": [self._serialize_closed_trade(trade) for trade in self._closed_positions],
            }
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._state_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
            tmp_path.replace(self._state_path)
        except Exception as exc:
            logger.warning("position_manager_persist_failed", error=str(exc))

    def _load_state(self) -> None:
        if self._state_path is None or not self._state_path.exists():
            return
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
            self._total_realized_pnl = float(payload.get("total_realized_pnl", 0.0) or 0.0)
            self._positions = {}
            for raw in payload.get("positions", []):
                position = self._deserialize_position(raw)
                self._recalculate_position(position)
                self._positions[position.symbol] = position
            self._closed_positions = [
                self._deserialize_closed_trade(raw)
                for raw in payload.get("closed_positions", [])
            ]
            logger.info(
                "position_manager_state_loaded",
                positions=len(self._positions),
                closed=len(self._closed_positions),
            )
        except Exception as exc:
            logger.warning("position_manager_state_load_failed", error=str(exc))

    @staticmethod
    def _serialize_position(position: Position) -> dict[str, Any]:
        return {
            "symbol": position.symbol,
            "quantity": int(position.quantity),
            "side": position.side.value,
            "avg_price": float(position.avg_price),
            "current_price": float(position.current_price),
            "entry_time": position.entry_time.isoformat() if position.entry_time else None,
            "strategy_tag": position.strategy_tag,
            "order_ids": list(position.order_ids),
            "lots": [
                {
                    "quantity": int(lot.quantity),
                    "entry_price": float(lot.entry_price),
                    "entry_time": lot.entry_time.isoformat() if lot.entry_time else None,
                    "strategy_tag": str(lot.strategy_tag or ""),
                    "order_ids": list(lot.order_ids),
                }
                for lot in PositionManager._normalized_lots(position)
            ],
        }

    @staticmethod
    def _deserialize_position(payload: dict[str, Any]) -> Position:
        lots_payload = payload.get("lots") or []
        position = Position(
            symbol=str(payload.get("symbol") or ""),
            quantity=int(payload.get("quantity") or 0),
            side=PositionSide(str(payload.get("side") or PositionSide.FLAT.value)),
            avg_price=float(payload.get("avg_price") or 0.0),
            current_price=float(payload.get("current_price") or 0.0),
            entry_time=(
                datetime.fromisoformat(str(payload["entry_time"]))
                if payload.get("entry_time")
                else None
            ),
            strategy_tag=str(payload.get("strategy_tag") or ""),
            order_ids=[str(order_id) for order_id in payload.get("order_ids", [])],
            lots=[
                PositionLot(
                    quantity=int(raw.get("quantity") or 0),
                    entry_price=float(raw.get("entry_price") or 0.0),
                    entry_time=(
                        datetime.fromisoformat(str(raw["entry_time"]))
                        if raw.get("entry_time")
                        else None
                    ),
                    strategy_tag=str(raw.get("strategy_tag") or ""),
                    order_ids=[str(order_id) for order_id in raw.get("order_ids", [])],
                )
                for raw in lots_payload
            ],
        )
        PositionManager._recalculate_position(position)
        return position

    @staticmethod
    def _serialize_closed_trade(payload: dict[str, Any]) -> dict[str, Any]:
        closed_at = payload.get("closed_at")
        return {
            **payload,
            "closed_at": closed_at.isoformat() if isinstance(closed_at, datetime) else closed_at,
        }

    @staticmethod
    def _deserialize_closed_trade(payload: dict[str, Any]) -> dict[str, Any]:
        restored = dict(payload)
        if restored.get("closed_at"):
            restored["closed_at"] = datetime.fromisoformat(str(restored["closed_at"]))
        return restored
