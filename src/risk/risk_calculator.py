"""Risk metrics calculator for portfolio and strategy analysis.

Computes comprehensive risk and performance metrics from return series
or trade lists. Includes Sharpe, Sortino, Calmar ratios, drawdown
analysis, VaR, CVaR, and trade-level statistics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class RiskMetrics:
    """Comprehensive risk and performance metrics.

    Attributes:
        sharpe_ratio: Annualized Sharpe ratio.
        sortino_ratio: Annualized Sortino ratio (downside deviation).
        calmar_ratio: Annualized return / max drawdown.
        max_drawdown: Maximum peak-to-trough drawdown (as a negative fraction).
        max_drawdown_duration: Longest drawdown period in trading days.
        var_95: Value at Risk at the 95% confidence level.
        var_99: Value at Risk at the 99% confidence level.
        cvar_95: Conditional VaR (Expected Shortfall) at 95%.
        volatility: Annualized volatility of returns.
        downside_volatility: Annualized downside deviation.
        profit_factor: Gross profits / gross losses.
        win_rate: Fraction of positive returns (0..1).
        avg_win: Average positive return.
        avg_loss: Average negative return (negative value).
        expectancy: avg_win * win_rate + avg_loss * (1 - win_rate).
        total_return: Cumulative return over the period.
        annualized_return: Annualized total return.
    """

    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown: float
    max_drawdown_duration: int
    var_95: float
    var_99: float
    cvar_95: float
    volatility: float
    downside_volatility: float
    profit_factor: float
    win_rate: float
    avg_win: float
    avg_loss: float
    expectancy: float
    total_return: float
    annualized_return: float


class RiskCalculator:
    """Calculate comprehensive risk metrics from return series or trade lists.

    Args:
        risk_free_rate: Annual risk-free rate (default 6.5% for India/RBI repo rate).
        trading_days_per_year: Number of trading days in a year (default 252).
    """

    def __init__(
        self,
        risk_free_rate: float = 0.065,
        trading_days_per_year: int = 252,
    ) -> None:
        self.risk_free_rate = risk_free_rate
        self.trading_days_per_year = trading_days_per_year

    def calculate_all(self, returns: pd.Series) -> RiskMetrics:
        """Calculate all risk metrics from a daily returns series.

        Args:
            returns: pd.Series of periodic (typically daily) returns as fractions
                (e.g. 0.01 = 1%).

        Returns:
            RiskMetrics with all fields populated.
        """
        returns = returns.dropna()

        if len(returns) == 0:
            return self._empty_metrics()

        return RiskMetrics(
            sharpe_ratio=self.sharpe_ratio(returns),
            sortino_ratio=self.sortino_ratio(returns),
            calmar_ratio=self.calmar_ratio(returns),
            max_drawdown=self.max_drawdown(returns),
            max_drawdown_duration=self.max_drawdown_duration(returns),
            var_95=self.value_at_risk(returns, confidence=0.95),
            var_99=self.value_at_risk(returns, confidence=0.99),
            cvar_95=self.conditional_var(returns, confidence=0.95),
            volatility=self.volatility(returns),
            downside_volatility=self.downside_volatility(returns),
            profit_factor=self.profit_factor(returns),
            win_rate=self._win_rate(returns),
            avg_win=self._avg_win(returns),
            avg_loss=self._avg_loss(returns),
            expectancy=self.expectancy(returns),
            total_return=self._total_return(returns),
            annualized_return=self._annualized_return(returns),
        )

    def calculate_from_trades(self, trades: List[dict]) -> RiskMetrics:
        """Calculate risk metrics from a list of trade dictionaries.

        Each dict must contain a 'pnl' key with the trade's profit/loss value.

        Args:
            trades: List of dicts, each with at least a 'pnl' key.

        Returns:
            RiskMetrics computed from the trade PnL series.
        """
        if not trades:
            return self._empty_metrics()

        pnl_values = [t["pnl"] for t in trades]
        returns = pd.Series(pnl_values, dtype=float)
        return self.calculate_all(returns)

    # ------------------------------------------------------------------
    # Individual metric methods
    # ------------------------------------------------------------------

    def sharpe_ratio(self, returns: pd.Series) -> float:
        """Annualized Sharpe ratio.

        Formula: (mean_return - rf_daily) / std * sqrt(trading_days)

        Args:
            returns: Series of periodic returns.

        Returns:
            Annualized Sharpe ratio. Returns 0.0 if std is zero.
        """
        if len(returns) < 2:
            return 0.0

        daily_rf = self.risk_free_rate / self.trading_days_per_year
        excess_returns = returns - daily_rf
        std = excess_returns.std(ddof=1)

        if std == 0 or np.isnan(std):
            return 0.0

        return float(
            (excess_returns.mean() / std) * np.sqrt(self.trading_days_per_year)
        )

    def sortino_ratio(self, returns: pd.Series) -> float:
        """Annualized Sortino ratio using downside deviation.

        Args:
            returns: Series of periodic returns.

        Returns:
            Annualized Sortino ratio. Returns 0.0 if downside std is zero.
        """
        if len(returns) < 2:
            return 0.0

        daily_rf = self.risk_free_rate / self.trading_days_per_year
        excess_returns = returns - daily_rf
        downside = excess_returns[excess_returns < 0]

        if len(downside) == 0:
            # No negative returns -- infinite Sortino, cap at 0.0 to indicate no downside
            return float(
                (excess_returns.mean() / 1e-10) * np.sqrt(self.trading_days_per_year)
            ) if excess_returns.mean() > 0 else 0.0

        downside_std = np.sqrt((downside ** 2).mean())
        if downside_std == 0 or np.isnan(downside_std):
            return 0.0

        return float(
            (excess_returns.mean() / downside_std) * np.sqrt(self.trading_days_per_year)
        )

    def calmar_ratio(self, returns: pd.Series) -> float:
        """Calmar ratio: annualized return / |max drawdown|.

        Args:
            returns: Series of periodic returns.

        Returns:
            Calmar ratio. Returns 0.0 if max drawdown is zero.
        """
        ann_ret = self._annualized_return(returns)
        mdd = self.max_drawdown(returns)

        if mdd == 0:
            return 0.0

        return float(ann_ret / abs(mdd))

    def max_drawdown(self, returns: pd.Series) -> float:
        """Maximum drawdown as a negative fraction (e.g. -0.15 = -15%).

        Args:
            returns: Series of periodic returns.

        Returns:
            Max drawdown (always <= 0).
        """
        if len(returns) == 0:
            return 0.0

        cumulative = (1 + returns).cumprod()
        running_max = cumulative.cummax()
        drawdowns = (cumulative - running_max) / running_max
        mdd = drawdowns.min()
        return float(mdd) if not np.isnan(mdd) else 0.0

    def max_drawdown_duration(self, returns: pd.Series) -> int:
        """Duration of the longest drawdown in periods.

        Args:
            returns: Series of periodic returns.

        Returns:
            Number of periods in the longest drawdown.
        """
        if len(returns) == 0:
            return 0

        cumulative = (1 + returns).cumprod()
        running_max = cumulative.cummax()

        in_drawdown = cumulative < running_max
        max_duration = 0
        current_duration = 0

        for is_dd in in_drawdown:
            if is_dd:
                current_duration += 1
                max_duration = max(max_duration, current_duration)
            else:
                current_duration = 0

        return max_duration

    def value_at_risk(
        self, returns: pd.Series, confidence: float = 0.95
    ) -> float:
        """Historical Value at Risk.

        The VaR at a given confidence level is the quantile of the return
        distribution at (1 - confidence). It represents the worst expected
        loss at the given confidence level.

        Args:
            returns: Series of periodic returns.
            confidence: Confidence level (e.g. 0.95 for 95%).

        Returns:
            VaR as a negative number (loss). Returns 0.0 if series is empty.
        """
        if len(returns) == 0:
            return 0.0

        var = float(np.percentile(returns, (1 - confidence) * 100))
        return var

    def conditional_var(
        self, returns: pd.Series, confidence: float = 0.95
    ) -> float:
        """Conditional VaR (Expected Shortfall) -- mean of returns below VaR.

        Args:
            returns: Series of periodic returns.
            confidence: Confidence level.

        Returns:
            CVaR as a negative number. Returns 0.0 if no returns below VaR.
        """
        if len(returns) == 0:
            return 0.0

        var = self.value_at_risk(returns, confidence)
        tail = returns[returns <= var]

        if len(tail) == 0:
            return var

        return float(tail.mean())

    def volatility(self, returns: pd.Series) -> float:
        """Annualized volatility of returns.

        Args:
            returns: Series of periodic returns.

        Returns:
            Annualized standard deviation.
        """
        if len(returns) < 2:
            return 0.0

        return float(returns.std(ddof=1) * np.sqrt(self.trading_days_per_year))

    def downside_volatility(self, returns: pd.Series) -> float:
        """Annualized downside deviation (volatility of negative returns).

        Uses the semi-deviation approach: sqrt(mean(min(r, 0)^2)) * sqrt(N).

        Args:
            returns: Series of periodic returns.

        Returns:
            Annualized downside deviation.
        """
        if len(returns) < 2:
            return 0.0

        daily_rf = self.risk_free_rate / self.trading_days_per_year
        excess = returns - daily_rf
        downside = np.minimum(excess, 0.0)
        dsd = float(np.sqrt((downside ** 2).mean()))
        return dsd * np.sqrt(self.trading_days_per_year)

    def profit_factor(self, returns: pd.Series) -> float:
        """Ratio of gross profits to gross losses.

        Args:
            returns: Series of periodic returns (or PnL values).

        Returns:
            Profit factor (>= 0). Returns inf if no losses, 0.0 if no profits.
        """
        gross_profit = float(returns[returns > 0].sum())
        gross_loss = float(abs(returns[returns < 0].sum()))

        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0

        return gross_profit / gross_loss

    def expectancy(self, returns: pd.Series) -> float:
        """Expected value per trade: avg_win * win_rate + avg_loss * loss_rate.

        Args:
            returns: Series of periodic returns (or trade PnLs).

        Returns:
            Expectancy value.
        """
        if len(returns) == 0:
            return 0.0

        wr = self._win_rate(returns)
        aw = self._avg_win(returns)
        al = self._avg_loss(returns)

        return aw * wr + al * (1.0 - wr)

    # ------------------------------------------------------------------
    # Drawdown / equity helpers
    # ------------------------------------------------------------------

    def drawdown_series(self, returns: pd.Series) -> pd.Series:
        """Compute the drawdown series from returns.

        Args:
            returns: Series of periodic returns.

        Returns:
            pd.Series of drawdown values (all <= 0).
        """
        if len(returns) == 0:
            return pd.Series(dtype=float)

        cumulative = (1 + returns).cumprod()
        running_max = cumulative.cummax()
        return (cumulative - running_max) / running_max

    def equity_curve(
        self, returns: pd.Series, initial_capital: float = 100000.0
    ) -> pd.Series:
        """Generate an equity curve from returns and initial capital.

        Args:
            returns: Series of periodic returns.
            initial_capital: Starting capital value (default 100000).

        Returns:
            pd.Series of equity values starting at initial_capital.
        """
        if len(returns) == 0:
            return pd.Series([initial_capital], dtype=float)

        cumulative = (1 + returns).cumprod()
        return initial_capital * cumulative

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _win_rate(self, returns: pd.Series) -> float:
        """Fraction of positive returns."""
        if len(returns) == 0:
            return 0.0
        return float((returns > 0).sum() / len(returns))

    def _avg_win(self, returns: pd.Series) -> float:
        """Average of positive returns."""
        wins = returns[returns > 0]
        if len(wins) == 0:
            return 0.0
        return float(wins.mean())

    def _avg_loss(self, returns: pd.Series) -> float:
        """Average of negative returns (returns a negative value)."""
        losses = returns[returns < 0]
        if len(losses) == 0:
            return 0.0
        return float(losses.mean())

    def _total_return(self, returns: pd.Series) -> float:
        """Cumulative total return."""
        if len(returns) == 0:
            return 0.0
        return float((1 + returns).prod() - 1)

    def _annualized_return(self, returns: pd.Series) -> float:
        """Annualized return using compound growth.

        Formula: (1 + total_return) ^ (trading_days / n_periods) - 1
        """
        if len(returns) == 0:
            return 0.0

        total = self._total_return(returns)
        n_periods = len(returns)

        if n_periods == 0:
            return 0.0

        # Guard against negative total return that would break the power computation
        base = 1 + total
        if base <= 0:
            return -1.0

        exponent = self.trading_days_per_year / n_periods
        return float(base ** exponent - 1)

    def _empty_metrics(self) -> RiskMetrics:
        """Return zeroed-out metrics for empty inputs."""
        return RiskMetrics(
            sharpe_ratio=0.0,
            sortino_ratio=0.0,
            calmar_ratio=0.0,
            max_drawdown=0.0,
            max_drawdown_duration=0,
            var_95=0.0,
            var_99=0.0,
            cvar_95=0.0,
            volatility=0.0,
            downside_volatility=0.0,
            profit_factor=0.0,
            win_rate=0.0,
            avg_win=0.0,
            avg_loss=0.0,
            expectancy=0.0,
            total_return=0.0,
            annualized_return=0.0,
        )
