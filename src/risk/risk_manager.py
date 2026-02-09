"""Risk manager -- enforces trading risk limits and controls.

Provides pre-trade validation, daily P&L tracking, circuit breaker
logic, and emergency stop functionality. All trades must pass through
validate_trade() before execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class RiskConfig:
    """Configuration for risk management limits.

    Attributes:
        max_daily_loss: Absolute maximum daily loss in INR.
        max_daily_loss_pct: Maximum daily loss as a fraction of capital (e.g. 0.02 = 2%).
        max_position_size: Maximum single position notional value in INR.
        max_open_positions: Maximum number of simultaneous open positions.
        max_concentration_pct: Maximum fraction of capital in a single symbol (e.g. 0.30 = 30%).
        max_risk_per_trade_pct: Maximum fraction of capital at risk per trade.
        capital: Total trading capital in INR.
        circuit_breaker_enabled: Whether to auto-trigger circuit breaker on daily loss limit.
        time_based_exit_minutes: Minutes before market close to force exit all positions.
    """

    max_daily_loss: float = 5000.0
    max_daily_loss_pct: float = 0.02
    max_position_size: float = 100000.0
    max_open_positions: int = 5
    max_concentration_pct: float = 0.30
    max_risk_per_trade_pct: float = 0.02
    capital: float = 250000.0
    circuit_breaker_enabled: bool = True
    time_based_exit_minutes: int = 30


@dataclass
class TradeValidation:
    """Result of a trade validation check.

    Attributes:
        is_valid: Whether the trade passes all risk checks.
        reason: Human-readable explanation (empty string if valid).
        risk_score: Risk score from 0 to 1 (higher = riskier).
    """

    is_valid: bool
    reason: str
    risk_score: float = 0.0


@dataclass
class DailyRiskState:
    """Tracks intraday risk metrics.

    Attributes:
        date: The trading date.
        realized_pnl: Sum of closed trade PnLs for today.
        unrealized_pnl: Current mark-to-market PnL of open positions.
        total_trades: Total trades executed today.
        winning_trades: Number of winning trades today.
        losing_trades: Number of losing trades today.
        circuit_breaker_triggered: Whether the circuit breaker has been triggered.
        open_positions: Current number of open positions.
    """

    date: date = field(default_factory=date.today)
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    circuit_breaker_triggered: bool = False
    open_positions: int = 0


class RiskManager:
    """Enforce trading risk limits and controls.

    All proposed trades should be validated via validate_trade() before
    execution. The manager tracks daily P&L and can trigger a circuit
    breaker or emergency stop.

    Args:
        config: RiskConfig with risk limits. Uses defaults if None.
    """

    def __init__(self, config: Optional[RiskConfig] = None) -> None:
        self.config = config or RiskConfig()
        self.daily_state = DailyRiskState()
        self.emergency_stop = False
        self._position_values: Dict[str, float] = {}  # symbol -> position notional value

    def validate_trade(
        self,
        symbol: str,
        side: str,
        quantity: int,
        entry_price: float,
        stop_loss: float,
    ) -> TradeValidation:
        """Validate a proposed trade against all risk limits.

        Checks (in order):
        1. Emergency stop not active.
        2. Circuit breaker not triggered.
        3. Daily loss limit not exceeded.
        4. Open position count within limit.
        5. Single position size within limit.
        6. Concentration limit for the symbol.
        7. Risk per trade within limit.

        Args:
            symbol: Trading symbol (e.g. 'NSE:NIFTY50-INDEX').
            side: Trade direction ('BUY' or 'SELL').
            quantity: Number of units.
            entry_price: Planned entry price.
            stop_loss: Stop-loss price.

        Returns:
            TradeValidation with is_valid, reason, and risk_score.
        """
        # 1. Emergency stop
        if self.emergency_stop:
            logger.warning("trade_rejected_emergency_stop", symbol=symbol)
            return TradeValidation(
                is_valid=False,
                reason="Emergency stop is active. No trades allowed.",
                risk_score=1.0,
            )

        # 2. Circuit breaker
        if self.daily_state.circuit_breaker_triggered:
            logger.warning("trade_rejected_circuit_breaker", symbol=symbol)
            return TradeValidation(
                is_valid=False,
                reason="Circuit breaker triggered. Trading halted for the day.",
                risk_score=1.0,
            )

        # 3. Daily loss limit
        total_daily_pnl = self.daily_state.realized_pnl + self.daily_state.unrealized_pnl
        max_loss_abs = self.config.max_daily_loss
        max_loss_pct_abs = self.config.capital * self.config.max_daily_loss_pct
        effective_max_loss = min(max_loss_abs, max_loss_pct_abs)

        if total_daily_pnl < 0 and abs(total_daily_pnl) >= effective_max_loss:
            logger.warning(
                "trade_rejected_daily_loss",
                symbol=symbol,
                daily_pnl=total_daily_pnl,
                limit=effective_max_loss,
            )
            return TradeValidation(
                is_valid=False,
                reason=f"Daily loss limit reached: {total_daily_pnl:.2f} "
                       f"(limit: -{effective_max_loss:.2f}).",
                risk_score=1.0,
            )

        # 4. Open positions limit
        if self.daily_state.open_positions >= self.config.max_open_positions:
            logger.warning(
                "trade_rejected_max_positions",
                symbol=symbol,
                open_positions=self.daily_state.open_positions,
                limit=self.config.max_open_positions,
            )
            return TradeValidation(
                is_valid=False,
                reason=f"Max open positions reached: "
                       f"{self.daily_state.open_positions}/{self.config.max_open_positions}.",
                risk_score=0.8,
            )

        # 5. Position size limit
        position_value = quantity * entry_price
        if position_value > self.config.max_position_size:
            logger.warning(
                "trade_rejected_position_size",
                symbol=symbol,
                position_value=position_value,
                limit=self.config.max_position_size,
            )
            return TradeValidation(
                is_valid=False,
                reason=f"Position value {position_value:.2f} exceeds limit "
                       f"{self.config.max_position_size:.2f}.",
                risk_score=0.9,
            )

        # 6. Concentration check
        existing_value = self._position_values.get(symbol, 0.0)
        total_symbol_value = existing_value + position_value
        concentration = total_symbol_value / self.config.capital if self.config.capital > 0 else 0.0

        if concentration > self.config.max_concentration_pct:
            logger.warning(
                "trade_rejected_concentration",
                symbol=symbol,
                concentration=concentration,
                limit=self.config.max_concentration_pct,
            )
            return TradeValidation(
                is_valid=False,
                reason=f"Concentration for {symbol} would be "
                       f"{concentration:.1%} (limit: {self.config.max_concentration_pct:.1%}).",
                risk_score=0.85,
            )

        # 7. Risk per trade
        risk_per_unit = abs(entry_price - stop_loss)
        trade_risk = quantity * risk_per_unit
        risk_pct = trade_risk / self.config.capital if self.config.capital > 0 else 0.0

        if risk_pct > self.config.max_risk_per_trade_pct:
            logger.warning(
                "trade_rejected_risk_per_trade",
                symbol=symbol,
                risk_pct=risk_pct,
                limit=self.config.max_risk_per_trade_pct,
            )
            return TradeValidation(
                is_valid=False,
                reason=f"Risk per trade {risk_pct:.2%} exceeds limit "
                       f"{self.config.max_risk_per_trade_pct:.2%}.",
                risk_score=0.9,
            )

        # Calculate overall risk score (0-1)
        loss_usage = (
            abs(total_daily_pnl) / effective_max_loss if effective_max_loss > 0 else 0.0
        )
        position_usage = (
            self.daily_state.open_positions / self.config.max_open_positions
            if self.config.max_open_positions > 0
            else 0.0
        )
        risk_score = max(loss_usage, position_usage, risk_pct / self.config.max_risk_per_trade_pct)
        risk_score = min(risk_score, 1.0)

        logger.info(
            "trade_validated",
            symbol=symbol,
            side=side,
            quantity=quantity,
            risk_score=round(risk_score, 3),
        )

        return TradeValidation(
            is_valid=True,
            reason="",
            risk_score=risk_score,
        )

    def update_pnl(self, pnl: float, is_realized: bool = True) -> None:
        """Update daily P&L and check circuit breaker.

        Args:
            pnl: Profit/loss amount (positive = profit, negative = loss).
            is_realized: True for closed trade PnL, False for unrealized mark-to-market.
        """
        if is_realized:
            self.daily_state.realized_pnl += pnl
        else:
            self.daily_state.unrealized_pnl = pnl  # unrealized is replaced, not accumulated

        logger.debug(
            "pnl_updated",
            pnl=pnl,
            is_realized=is_realized,
            realized_total=self.daily_state.realized_pnl,
            unrealized=self.daily_state.unrealized_pnl,
        )

        self.check_circuit_breaker()

    def check_circuit_breaker(self) -> bool:
        """Check if circuit breaker should trigger.

        Triggers when combined realized + unrealized PnL breaches the daily
        loss limit. Only triggers if circuit_breaker_enabled is True.

        Returns:
            True if the circuit breaker was triggered (or already triggered).
        """
        if self.daily_state.circuit_breaker_triggered:
            return True

        if not self.config.circuit_breaker_enabled:
            return False

        total_pnl = self.daily_state.realized_pnl + self.daily_state.unrealized_pnl
        max_loss_abs = self.config.max_daily_loss
        max_loss_pct_abs = self.config.capital * self.config.max_daily_loss_pct
        effective_max_loss = min(max_loss_abs, max_loss_pct_abs)

        if total_pnl < 0 and abs(total_pnl) >= effective_max_loss:
            self.daily_state.circuit_breaker_triggered = True
            logger.error(
                "circuit_breaker_triggered",
                total_pnl=total_pnl,
                limit=effective_max_loss,
            )
            return True

        return False

    def trigger_emergency_stop(self, reason: str) -> None:
        """Activate emergency stop -- no more trades allowed until reset.

        Args:
            reason: Human-readable reason for the emergency stop.
        """
        self.emergency_stop = True
        logger.critical("emergency_stop_activated", reason=reason)

    def reset_daily_state(self) -> None:
        """Reset daily state. Call at the start of each trading day."""
        self.daily_state = DailyRiskState()
        self._position_values.clear()
        # Note: emergency_stop is NOT reset here -- must be explicitly cleared.
        logger.info("daily_risk_state_reset")

    def get_available_risk(self) -> float:
        """Return remaining risk budget for today in INR.

        Returns:
            Remaining loss budget before circuit breaker triggers.
        """
        max_loss_abs = self.config.max_daily_loss
        max_loss_pct_abs = self.config.capital * self.config.max_daily_loss_pct
        effective_max_loss = min(max_loss_abs, max_loss_pct_abs)

        total_pnl = self.daily_state.realized_pnl + self.daily_state.unrealized_pnl
        used = abs(total_pnl) if total_pnl < 0 else 0.0

        return max(effective_max_loss - used, 0.0)

    def get_risk_summary(self) -> Dict[str, Any]:
        """Return current risk state summary.

        Returns:
            Dict with all current risk state fields.
        """
        max_loss_abs = self.config.max_daily_loss
        max_loss_pct_abs = self.config.capital * self.config.max_daily_loss_pct
        effective_max_loss = min(max_loss_abs, max_loss_pct_abs)

        return {
            "date": str(self.daily_state.date),
            "capital": self.config.capital,
            "realized_pnl": round(self.daily_state.realized_pnl, 2),
            "unrealized_pnl": round(self.daily_state.unrealized_pnl, 2),
            "total_pnl": round(
                self.daily_state.realized_pnl + self.daily_state.unrealized_pnl, 2
            ),
            "total_trades": self.daily_state.total_trades,
            "winning_trades": self.daily_state.winning_trades,
            "losing_trades": self.daily_state.losing_trades,
            "open_positions": self.daily_state.open_positions,
            "max_open_positions": self.config.max_open_positions,
            "daily_loss_limit": effective_max_loss,
            "available_risk": round(self.get_available_risk(), 2),
            "circuit_breaker_triggered": self.daily_state.circuit_breaker_triggered,
            "emergency_stop": self.emergency_stop,
            "position_values": dict(self._position_values),
        }

    def record_trade_result(self, pnl: float) -> None:
        """Record a completed trade's PnL and update counters.

        Args:
            pnl: Trade profit/loss (positive = win, negative = loss).
        """
        self.daily_state.total_trades += 1

        if pnl > 0:
            self.daily_state.winning_trades += 1
        elif pnl < 0:
            self.daily_state.losing_trades += 1

        self.update_pnl(pnl, is_realized=True)

        logger.info(
            "trade_result_recorded",
            pnl=pnl,
            total_trades=self.daily_state.total_trades,
            win_rate=(
                self.daily_state.winning_trades / self.daily_state.total_trades
                if self.daily_state.total_trades > 0
                else 0.0
            ),
        )

    def add_position(self, symbol: str, position_value: float) -> None:
        """Track an opened position for concentration checks.

        Args:
            symbol: Trading symbol.
            position_value: Notional value of the position.
        """
        self._position_values[symbol] = (
            self._position_values.get(symbol, 0.0) + position_value
        )
        self.daily_state.open_positions += 1

    def remove_position(self, symbol: str, position_value: float) -> None:
        """Remove a closed position from tracking.

        Args:
            symbol: Trading symbol.
            position_value: Notional value being removed.
        """
        current = self._position_values.get(symbol, 0.0)
        remaining = current - position_value
        if remaining <= 0:
            self._position_values.pop(symbol, None)
        else:
            self._position_values[symbol] = remaining

        self.daily_state.open_positions = max(0, self.daily_state.open_positions - 1)
