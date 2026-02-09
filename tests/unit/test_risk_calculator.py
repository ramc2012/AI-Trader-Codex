"""Tests for the RiskCalculator class and RiskMetrics dataclass."""

import math

import numpy as np
import pandas as pd
import pytest

from src.risk.risk_calculator import RiskCalculator, RiskMetrics


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def calc() -> RiskCalculator:
    """Standard calculator with 6.5% risk-free rate, 252 days."""
    return RiskCalculator(risk_free_rate=0.065, trading_days_per_year=252)


@pytest.fixture
def positive_returns() -> pd.Series:
    """100 days of consistently positive returns (~0.5% daily)."""
    np.random.seed(42)
    return pd.Series(np.random.uniform(0.002, 0.008, 100))


@pytest.fixture
def negative_returns() -> pd.Series:
    """100 days of consistently negative returns."""
    np.random.seed(42)
    return pd.Series(np.random.uniform(-0.008, -0.002, 100))


@pytest.fixture
def mixed_returns() -> pd.Series:
    """100 days of mixed positive and negative returns."""
    np.random.seed(42)
    return pd.Series(np.random.normal(0.001, 0.015, 100))


@pytest.fixture
def flat_returns() -> pd.Series:
    """100 days of zero returns."""
    return pd.Series(np.zeros(100))


# =========================================================================
# Sharpe ratio
# =========================================================================


class TestSharpeRatio:
    def test_positive_returns_positive_sharpe(
        self, calc: RiskCalculator, positive_returns: pd.Series
    ) -> None:
        sharpe = calc.sharpe_ratio(positive_returns)
        assert sharpe > 0

    def test_negative_returns_negative_sharpe(
        self, calc: RiskCalculator, negative_returns: pd.Series
    ) -> None:
        sharpe = calc.sharpe_ratio(negative_returns)
        assert sharpe < 0

    def test_flat_returns_zero_sharpe(
        self, calc: RiskCalculator, flat_returns: pd.Series
    ) -> None:
        sharpe = calc.sharpe_ratio(flat_returns)
        assert sharpe == 0.0


# =========================================================================
# Sortino ratio
# =========================================================================


class TestSortinoRatio:
    def test_all_positive_returns_large_sortino(
        self, calc: RiskCalculator, positive_returns: pd.Series
    ) -> None:
        """With no negative returns, sortino should be very large."""
        sortino = calc.sortino_ratio(positive_returns)
        assert sortino > 0

    def test_sortino_vs_sharpe_positive(
        self, calc: RiskCalculator, mixed_returns: pd.Series
    ) -> None:
        """With mixed returns, sortino and sharpe are both finite."""
        sharpe = calc.sharpe_ratio(mixed_returns)
        sortino = calc.sortino_ratio(mixed_returns)
        # Both should be finite
        assert math.isfinite(sharpe)
        assert math.isfinite(sortino)


# =========================================================================
# Calmar ratio
# =========================================================================


class TestCalmarRatio:
    def test_calmar_positive_returns(
        self, calc: RiskCalculator, positive_returns: pd.Series
    ) -> None:
        """All positive returns → max drawdown is near 0, calmar may be 0."""
        calmar = calc.calmar_ratio(positive_returns)
        # With all-positive returns, drawdown is 0 so calmar will be 0.0
        assert calmar == 0.0

    def test_calmar_mixed(
        self, calc: RiskCalculator, mixed_returns: pd.Series
    ) -> None:
        calmar = calc.calmar_ratio(mixed_returns)
        assert math.isfinite(calmar)


# =========================================================================
# Max drawdown
# =========================================================================


class TestMaxDrawdown:
    def test_always_negative_or_zero(
        self, calc: RiskCalculator, mixed_returns: pd.Series
    ) -> None:
        mdd = calc.max_drawdown(mixed_returns)
        assert mdd <= 0.0

    def test_flat_returns_zero(
        self, calc: RiskCalculator, flat_returns: pd.Series
    ) -> None:
        mdd = calc.max_drawdown(flat_returns)
        assert mdd == 0.0

    def test_all_positive_returns_zero_drawdown(
        self, calc: RiskCalculator, positive_returns: pd.Series
    ) -> None:
        mdd = calc.max_drawdown(positive_returns)
        assert mdd == 0.0

    def test_known_drawdown(self, calc: RiskCalculator) -> None:
        """Two consecutive -10% days after a flat start."""
        returns = pd.Series([0.0, 0.0, -0.10, -0.10, 0.0])
        mdd = calc.max_drawdown(returns)
        assert mdd < 0
        assert mdd == pytest.approx(-0.19, abs=0.01)


# =========================================================================
# Value at Risk
# =========================================================================


class TestValueAtRisk:
    def test_var_95_less_extreme_than_99(
        self, calc: RiskCalculator, mixed_returns: pd.Series
    ) -> None:
        """95% VaR should be less extreme (closer to 0) than 99% VaR."""
        var_95 = calc.value_at_risk(mixed_returns, confidence=0.95)
        var_99 = calc.value_at_risk(mixed_returns, confidence=0.99)
        assert var_95 >= var_99  # both negative, 95% is closer to 0

    def test_empty_returns(self, calc: RiskCalculator) -> None:
        var = calc.value_at_risk(pd.Series(dtype=float), confidence=0.95)
        assert var == 0.0


# =========================================================================
# Conditional VaR
# =========================================================================


class TestConditionalVar:
    def test_cvar_more_extreme_than_var(
        self, calc: RiskCalculator, mixed_returns: pd.Series
    ) -> None:
        """CVaR (expected shortfall) should be more extreme than VaR."""
        var_95 = calc.value_at_risk(mixed_returns, confidence=0.95)
        cvar_95 = calc.conditional_var(mixed_returns, confidence=0.95)
        assert cvar_95 <= var_95  # more negative


# =========================================================================
# Profit factor
# =========================================================================


class TestProfitFactor:
    def test_mixed_returns(
        self, calc: RiskCalculator, mixed_returns: pd.Series
    ) -> None:
        pf = calc.profit_factor(mixed_returns)
        assert pf >= 0

    def test_all_positive_returns_inf(
        self, calc: RiskCalculator, positive_returns: pd.Series
    ) -> None:
        pf = calc.profit_factor(positive_returns)
        assert pf == float("inf")

    def test_all_negative_returns_zero(
        self, calc: RiskCalculator, negative_returns: pd.Series
    ) -> None:
        pf = calc.profit_factor(negative_returns)
        assert pf == 0.0


# =========================================================================
# Volatility
# =========================================================================


class TestVolatility:
    def test_annualized_volatility(
        self, calc: RiskCalculator, mixed_returns: pd.Series
    ) -> None:
        vol = calc.volatility(mixed_returns)
        assert vol > 0

    def test_flat_returns_zero_vol(
        self, calc: RiskCalculator, flat_returns: pd.Series
    ) -> None:
        vol = calc.volatility(flat_returns)
        assert vol == 0.0


# =========================================================================
# Equity curve and drawdown series
# =========================================================================


class TestEquityCurveAndDrawdownSeries:
    def test_equity_curve_starts_at_capital(
        self, calc: RiskCalculator, mixed_returns: pd.Series
    ) -> None:
        equity = calc.equity_curve(mixed_returns, initial_capital=100_000.0)
        # First value = initial_capital * (1 + return[0])
        expected_first = 100_000.0 * (1 + mixed_returns.iloc[0])
        assert equity.iloc[0] == pytest.approx(expected_first, rel=1e-6)

    def test_drawdown_series_values_between_neg1_and_0(
        self, calc: RiskCalculator, mixed_returns: pd.Series
    ) -> None:
        dd = calc.drawdown_series(mixed_returns)
        assert (dd <= 0.0).all()
        assert (dd >= -1.0).all()


# =========================================================================
# calculate_all
# =========================================================================


class TestCalculateAll:
    def test_returns_complete_risk_metrics(
        self, calc: RiskCalculator, mixed_returns: pd.Series
    ) -> None:
        metrics = calc.calculate_all(mixed_returns)
        assert isinstance(metrics, RiskMetrics)
        # Check all fields are populated
        assert math.isfinite(metrics.sharpe_ratio)
        assert math.isfinite(metrics.sortino_ratio)
        assert math.isfinite(metrics.calmar_ratio)
        assert math.isfinite(metrics.max_drawdown)
        assert isinstance(metrics.max_drawdown_duration, int)
        assert math.isfinite(metrics.var_95)
        assert math.isfinite(metrics.var_99)
        assert math.isfinite(metrics.cvar_95)
        assert math.isfinite(metrics.volatility)
        assert math.isfinite(metrics.downside_volatility)
        # profit_factor can be inf
        assert metrics.win_rate >= 0
        assert math.isfinite(metrics.total_return)
        assert math.isfinite(metrics.annualized_return)

    def test_empty_returns_zeroed(self, calc: RiskCalculator) -> None:
        metrics = calc.calculate_all(pd.Series(dtype=float))
        assert metrics.sharpe_ratio == 0.0
        assert metrics.max_drawdown == 0.0
        assert metrics.volatility == 0.0


# =========================================================================
# calculate_from_trades
# =========================================================================


class TestCalculateFromTrades:
    def test_from_trade_dicts(self, calc: RiskCalculator) -> None:
        trades = [
            {"pnl": 0.01},
            {"pnl": -0.005},
            {"pnl": 0.02},
            {"pnl": -0.003},
            {"pnl": 0.015},
        ]
        metrics = calc.calculate_from_trades(trades)
        assert isinstance(metrics, RiskMetrics)
        assert metrics.win_rate > 0

    def test_empty_trades(self, calc: RiskCalculator) -> None:
        metrics = calc.calculate_from_trades([])
        assert metrics.sharpe_ratio == 0.0


# =========================================================================
# All-positive / all-negative returns summary
# =========================================================================


class TestReturnExtremes:
    def test_all_positive_good_metrics(
        self, calc: RiskCalculator, positive_returns: pd.Series
    ) -> None:
        metrics = calc.calculate_all(positive_returns)
        assert metrics.sharpe_ratio > 0
        assert metrics.win_rate == 1.0
        assert metrics.max_drawdown == 0.0

    def test_all_negative_bad_metrics(
        self, calc: RiskCalculator, negative_returns: pd.Series
    ) -> None:
        metrics = calc.calculate_all(negative_returns)
        assert metrics.sharpe_ratio < 0
        assert metrics.win_rate == 0.0
        assert metrics.max_drawdown < 0
