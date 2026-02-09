"""Position sizing algorithms for risk-controlled trading.

Provides multiple position sizing methods including fixed fractional,
Kelly criterion, volatility-adjusted, and fixed lot sizing. All methods
ensure positions are expressed in whole lots and never return negative sizes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

import numpy as np

from src.utils.logger import get_logger

logger = get_logger(__name__)


class SizingMethod(str, Enum):
    """Available position sizing methods."""

    FIXED_FRACTIONAL = "fixed_fractional"
    KELLY = "kelly"
    VOLATILITY_ADJUSTED = "volatility_adjusted"
    FIXED_LOT = "fixed_lot"


@dataclass
class PositionSize:
    """Result of a position sizing calculation.

    Attributes:
        lots: Number of lots (always >= 0, whole number).
        quantity: Total quantity (lots * lot_size).
        risk_amount: Absolute amount of capital at risk in INR.
        position_value: Total notional value of the position.
        risk_percent: Percentage of capital at risk.
        method: The sizing method that produced this result.
    """

    lots: int
    quantity: int
    risk_amount: float
    position_value: float
    risk_percent: float
    method: SizingMethod


class PositionSizer:
    """Calculate position sizes using various risk-based methods.

    All methods guarantee:
    - Lots are always >= 0 (never negative).
    - Lots are whole numbers (rounded down).
    - Risk percent never exceeds max_risk_per_trade.

    Args:
        capital: Total trading capital in INR.
        method: Default sizing method to use.
        max_risk_per_trade: Maximum fraction of capital to risk per trade (e.g. 0.02 = 2%).
        lot_size: Number of units per lot (Nifty default = 50).
    """

    def __init__(
        self,
        capital: float,
        method: SizingMethod = SizingMethod.FIXED_FRACTIONAL,
        max_risk_per_trade: float = 0.02,
        lot_size: int = 50,
    ) -> None:
        if capital <= 0:
            raise ValueError("capital must be > 0")
        if max_risk_per_trade <= 0 or max_risk_per_trade > 1.0:
            raise ValueError("max_risk_per_trade must be between 0 (exclusive) and 1.0 (inclusive)")
        if lot_size <= 0:
            raise ValueError("lot_size must be > 0")

        self.capital = capital
        self.method = method
        self.max_risk_per_trade = max_risk_per_trade
        self.lot_size = lot_size

    def calculate(
        self,
        entry_price: float,
        stop_loss: float,
        strategy_stats: Optional[Dict[str, Any]] = None,
        current_volatility: Optional[float] = None,
    ) -> PositionSize:
        """Calculate position size based on the configured default method.

        Dispatches to the appropriate sizing method. For Kelly criterion,
        strategy_stats must contain 'win_rate', 'avg_win', and 'avg_loss'.
        For volatility-adjusted, current_volatility must be provided.

        Args:
            entry_price: Planned entry price.
            stop_loss: Stop-loss price level.
            strategy_stats: Dict with keys 'win_rate', 'avg_win', 'avg_loss'
                (required for Kelly method).
            current_volatility: Current annualized volatility as a fraction
                (required for volatility-adjusted method).

        Returns:
            PositionSize with the calculated sizing.
        """
        if self.method == SizingMethod.FIXED_FRACTIONAL:
            return self.fixed_fractional(entry_price, stop_loss)

        elif self.method == SizingMethod.KELLY:
            stats = strategy_stats or {}
            win_rate = stats.get("win_rate", 0.5)
            avg_win = stats.get("avg_win", 1.0)
            avg_loss = stats.get("avg_loss", 1.0)
            return self.kelly_criterion(entry_price, stop_loss, win_rate, avg_win, avg_loss)

        elif self.method == SizingMethod.VOLATILITY_ADJUSTED:
            vol = current_volatility if current_volatility is not None else 0.15
            return self.volatility_adjusted(entry_price, stop_loss, vol)

        elif self.method == SizingMethod.FIXED_LOT:
            return self.fixed_lot(entry_price, stop_loss)

        else:
            raise ValueError(f"Unknown sizing method: {self.method}")

    def fixed_fractional(self, entry_price: float, stop_loss: float) -> PositionSize:
        """Risk a fixed percentage of capital per trade.

        Formula:
            risk_amount = capital * max_risk_per_trade
            risk_per_unit = |entry_price - stop_loss|
            risk_per_lot = risk_per_unit * lot_size
            lots = floor(risk_amount / risk_per_lot)

        Args:
            entry_price: Planned entry price.
            stop_loss: Stop-loss price level.

        Returns:
            PositionSize with fixed-fractional sizing.
        """
        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit == 0:
            logger.warning("entry_price equals stop_loss, returning 0 lots")
            return self._build_position(0, entry_price, stop_loss, SizingMethod.FIXED_FRACTIONAL)

        risk_amount = self.capital * self.max_risk_per_trade
        risk_per_lot = risk_per_unit * self.lot_size
        lots = int(risk_amount / risk_per_lot)
        lots = self._clamp_lots(lots, entry_price, stop_loss)

        return self._build_position(lots, entry_price, stop_loss, SizingMethod.FIXED_FRACTIONAL)

    def kelly_criterion(
        self,
        entry_price: float,
        stop_loss: float,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
    ) -> PositionSize:
        """Kelly criterion with half-Kelly for safety.

        Formula:
            b = avg_win / avg_loss  (reward-to-risk ratio)
            f = (p * b - q) / b     where p = win_rate, q = 1 - p
            half_kelly = f / 2
            Clamp to [0, max_risk_per_trade].

        Edge cases:
            - win_rate <= 0: returns 0 lots (no edge).
            - avg_loss <= 0: returns 0 lots (undefined ratio).
            - Negative Kelly: returns 0 lots (negative expectancy).

        Args:
            entry_price: Planned entry price.
            stop_loss: Stop-loss price level.
            win_rate: Historical win rate as a fraction (0..1).
            avg_win: Average winning trade amount (positive).
            avg_loss: Average losing trade amount (positive, absolute value).

        Returns:
            PositionSize with Kelly-based sizing.
        """
        if win_rate <= 0 or avg_loss <= 0 or avg_win <= 0:
            logger.info(
                "kelly_no_edge",
                win_rate=win_rate,
                avg_win=avg_win,
                avg_loss=avg_loss,
            )
            return self._build_position(0, entry_price, stop_loss, SizingMethod.KELLY)

        b = avg_win / avg_loss  # reward-to-risk ratio
        p = min(win_rate, 1.0)
        q = 1.0 - p

        kelly_fraction = (p * b - q) / b

        if kelly_fraction <= 0:
            logger.info("kelly_negative_expectancy", kelly_f=kelly_fraction)
            return self._build_position(0, entry_price, stop_loss, SizingMethod.KELLY)

        # Half-Kelly for safety
        half_kelly = kelly_fraction / 2.0
        # Clamp to max risk
        risk_fraction = min(half_kelly, self.max_risk_per_trade)

        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit == 0:
            return self._build_position(0, entry_price, stop_loss, SizingMethod.KELLY)

        risk_amount = self.capital * risk_fraction
        risk_per_lot = risk_per_unit * self.lot_size
        lots = int(risk_amount / risk_per_lot)
        lots = self._clamp_lots(lots, entry_price, stop_loss)

        return self._build_position(lots, entry_price, stop_loss, SizingMethod.KELLY)

    def volatility_adjusted(
        self,
        entry_price: float,
        stop_loss: float,
        current_volatility: float,
        target_volatility: float = 0.15,
    ) -> PositionSize:
        """Adjust position size based on current vs target volatility.

        When current volatility is high relative to target, reduce size.
        When current volatility is low, increase size (up to max risk).

        Formula:
            vol_scalar = target_volatility / current_volatility
            adjusted_risk = max_risk_per_trade * vol_scalar
            Clamp adjusted_risk to [0, max_risk_per_trade].

        Args:
            entry_price: Planned entry price.
            stop_loss: Stop-loss price level.
            current_volatility: Current annualized volatility (fraction).
            target_volatility: Target annualized volatility (fraction, default 0.15).

        Returns:
            PositionSize with volatility-adjusted sizing.
        """
        if current_volatility <= 0:
            logger.warning("current_volatility <= 0, returning 0 lots")
            return self._build_position(
                0, entry_price, stop_loss, SizingMethod.VOLATILITY_ADJUSTED
            )

        vol_scalar = target_volatility / current_volatility
        adjusted_risk = self.max_risk_per_trade * vol_scalar
        # Clamp: never exceed max risk per trade
        adjusted_risk = min(adjusted_risk, self.max_risk_per_trade)
        adjusted_risk = max(adjusted_risk, 0.0)

        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit == 0:
            return self._build_position(
                0, entry_price, stop_loss, SizingMethod.VOLATILITY_ADJUSTED
            )

        risk_amount = self.capital * adjusted_risk
        risk_per_lot = risk_per_unit * self.lot_size
        lots = int(risk_amount / risk_per_lot)
        lots = self._clamp_lots(lots, entry_price, stop_loss)

        return self._build_position(lots, entry_price, stop_loss, SizingMethod.VOLATILITY_ADJUSTED)

    def fixed_lot(
        self, entry_price: float, stop_loss: float, lots: int = 1
    ) -> PositionSize:
        """Use a fixed number of lots regardless of volatility.

        Args:
            entry_price: Planned entry price.
            stop_loss: Stop-loss price level.
            lots: Number of lots (default 1).

        Returns:
            PositionSize with fixed lot sizing.
        """
        lots = max(lots, 0)
        lots = self._clamp_lots(lots, entry_price, stop_loss)
        return self._build_position(lots, entry_price, stop_loss, SizingMethod.FIXED_LOT)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _clamp_lots(self, lots: int, entry_price: float, stop_loss: float) -> int:
        """Ensure lots are non-negative and risk does not exceed max_risk_per_trade.

        Args:
            lots: Proposed number of lots.
            entry_price: Planned entry price.
            stop_loss: Stop-loss price level.

        Returns:
            Clamped lot count (>= 0).
        """
        lots = max(lots, 0)

        # Verify the resulting risk percent does not exceed the limit
        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit > 0 and lots > 0:
            actual_risk = lots * self.lot_size * risk_per_unit
            max_allowed = self.capital * self.max_risk_per_trade
            while actual_risk > max_allowed and lots > 0:
                lots -= 1
                actual_risk = lots * self.lot_size * risk_per_unit

        return lots

    def _build_position(
        self,
        lots: int,
        entry_price: float,
        stop_loss: float,
        method: SizingMethod,
    ) -> PositionSize:
        """Construct a PositionSize dataclass from lots and prices.

        Args:
            lots: Number of lots.
            entry_price: Planned entry price.
            stop_loss: Stop-loss price level.
            method: Sizing method used.

        Returns:
            Fully populated PositionSize.
        """
        quantity = lots * self.lot_size
        risk_per_unit = abs(entry_price - stop_loss)
        risk_amount = quantity * risk_per_unit
        position_value = quantity * entry_price
        risk_percent = risk_amount / self.capital if self.capital > 0 else 0.0

        logger.debug(
            "position_sized",
            method=method.value,
            lots=lots,
            quantity=quantity,
            risk_amount=round(risk_amount, 2),
            position_value=round(position_value, 2),
            risk_percent=round(risk_percent, 4),
        )

        return PositionSize(
            lots=lots,
            quantity=quantity,
            risk_amount=risk_amount,
            position_value=position_value,
            risk_percent=risk_percent,
            method=method,
        )
