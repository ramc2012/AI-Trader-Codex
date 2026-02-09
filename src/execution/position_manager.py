"""Position management - track open positions and P&L.

Manages the lifecycle of trading positions including opening, closing,
averaging, flipping, and real-time P&L tracking. Supports both long
and short positions with partial close and position flip semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


class PositionSide(Enum):
    """Side of a position."""

    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


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

    def __init__(self) -> None:
        self._positions: Dict[str, Position] = {}
        self._closed_positions: List[Dict[str, Any]] = []
        self._total_realized_pnl: float = 0.0
        logger.info("position_manager_initialized")

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

            if existing.side == side:
                # Average up/down
                total_qty = existing.quantity + quantity
                new_avg = (
                    existing.avg_price * existing.quantity + price * quantity
                ) / total_qty
                existing.avg_price = new_avg
                existing.quantity = total_qty
                if order_id:
                    existing.order_ids.append(order_id)
                logger.info(
                    "position_averaged",
                    symbol=symbol,
                    side=side.value,
                    new_qty=total_qty,
                    new_avg=new_avg,
                )
                return existing
            else:
                # Opposite direction: reduce or flip
                if quantity < existing.quantity:
                    # Partial close
                    pnl = self._calc_pnl(
                        existing.side, existing.avg_price, price, quantity
                    )
                    self._total_realized_pnl += pnl
                    existing.quantity -= quantity
                    self._closed_positions.append(
                        {
                            "symbol": symbol,
                            "side": existing.side.value,
                            "quantity": quantity,
                            "entry_price": existing.avg_price,
                            "exit_price": price,
                            "pnl": pnl,
                            "closed_at": datetime.now(),
                            "strategy_tag": existing.strategy_tag,
                        }
                    )
                    logger.info(
                        "position_partially_closed",
                        symbol=symbol,
                        closed_qty=quantity,
                        remaining_qty=existing.quantity,
                        pnl=pnl,
                    )
                    return existing
                elif quantity == existing.quantity:
                    # Full close
                    pnl = self._calc_pnl(
                        existing.side, existing.avg_price, price, quantity
                    )
                    self._total_realized_pnl += pnl
                    self._closed_positions.append(
                        {
                            "symbol": symbol,
                            "side": existing.side.value,
                            "quantity": quantity,
                            "entry_price": existing.avg_price,
                            "exit_price": price,
                            "pnl": pnl,
                            "closed_at": datetime.now(),
                            "strategy_tag": existing.strategy_tag,
                        }
                    )
                    del self._positions[symbol]
                    logger.info(
                        "position_closed",
                        symbol=symbol,
                        pnl=pnl,
                    )
                    return Position(
                        symbol=symbol,
                        quantity=0,
                        side=PositionSide.FLAT,
                        avg_price=0.0,
                        current_price=price,
                    )
                else:
                    # Flip: close existing and open new in opposite direction
                    close_pnl = self._calc_pnl(
                        existing.side,
                        existing.avg_price,
                        price,
                        existing.quantity,
                    )
                    self._total_realized_pnl += close_pnl
                    self._closed_positions.append(
                        {
                            "symbol": symbol,
                            "side": existing.side.value,
                            "quantity": existing.quantity,
                            "entry_price": existing.avg_price,
                            "exit_price": price,
                            "pnl": close_pnl,
                            "closed_at": datetime.now(),
                            "strategy_tag": existing.strategy_tag,
                        }
                    )
                    remaining_qty = quantity - existing.quantity
                    new_pos = Position(
                        symbol=symbol,
                        quantity=remaining_qty,
                        side=side,
                        avg_price=price,
                        current_price=price,
                        entry_time=datetime.now(),
                        strategy_tag=strategy_tag,
                        order_ids=[order_id] if order_id else [],
                    )
                    self._positions[symbol] = new_pos
                    logger.info(
                        "position_flipped",
                        symbol=symbol,
                        new_side=side.value,
                        new_qty=remaining_qty,
                        close_pnl=close_pnl,
                    )
                    return new_pos
        else:
            # New position
            pos = Position(
                symbol=symbol,
                quantity=quantity,
                side=side,
                avg_price=price,
                current_price=price,
                entry_time=datetime.now(),
                strategy_tag=strategy_tag,
                order_ids=[order_id] if order_id else [],
            )
            self._positions[symbol] = pos
            logger.info(
                "position_opened",
                symbol=symbol,
                side=side.value,
                quantity=quantity,
                price=price,
            )
            return pos

    def close_position(
        self, symbol: str, price: float, quantity: Optional[int] = None
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
        close_qty = quantity if quantity is not None else pos.quantity

        if close_qty > pos.quantity:
            raise ValueError(
                f"Cannot close {close_qty} units; only {pos.quantity} held"
            )

        pnl = self._calc_pnl(pos.side, pos.avg_price, price, close_qty)
        self._total_realized_pnl += pnl
        self._closed_positions.append(
            {
                "symbol": symbol,
                "side": pos.side.value,
                "quantity": close_qty,
                "entry_price": pos.avg_price,
                "exit_price": price,
                "pnl": pnl,
                "closed_at": datetime.now(),
                "strategy_tag": pos.strategy_tag,
            }
        )

        if close_qty == pos.quantity:
            del self._positions[symbol]
            logger.info(
                "position_closed",
                symbol=symbol,
                pnl=pnl,
            )
        else:
            pos.quantity -= close_qty
            logger.info(
                "position_partially_closed",
                symbol=symbol,
                closed_qty=close_qty,
                remaining_qty=pos.quantity,
                pnl=pnl,
            )

        return pnl

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
        return [p for p in self._positions.values() if p.strategy_tag == tag]

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
                    "qty": p.quantity,
                    "side": p.side.value,
                    "avg": p.avg_price,
                    "current": p.current_price,
                    "pnl": p.unrealized_pnl,
                }
                for s, p in self._positions.items()
            },
        }

    def get_closed_trades(self) -> List[Dict[str, Any]]:
        """Get history of all closed trades.

        Returns:
            List of dictionaries with closed trade details.
        """
        return list(self._closed_positions)

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
