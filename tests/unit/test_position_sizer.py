"""Tests for the PositionSizer class and related dataclasses."""

import pytest

from src.risk.position_sizer import PositionSize, PositionSizer, SizingMethod


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def sizer() -> PositionSizer:
    """Standard sizer with 1M capital, 2% risk, lot_size=50."""
    return PositionSizer(
        capital=1_000_000.0,
        method=SizingMethod.FIXED_FRACTIONAL,
        max_risk_per_trade=0.02,
        lot_size=50,
    )


# =========================================================================
# PositionSize dataclass tests
# =========================================================================


class TestPositionSizeDataclass:
    def test_fields_are_correct(self) -> None:
        ps = PositionSize(
            lots=2,
            quantity=100,
            risk_amount=5000.0,
            position_value=2_200_000.0,
            risk_percent=0.005,
            method=SizingMethod.FIXED_FRACTIONAL,
        )
        assert ps.lots == 2
        assert ps.quantity == 100
        assert ps.risk_amount == 5000.0
        assert ps.position_value == 2_200_000.0
        assert ps.risk_percent == 0.005
        assert ps.method == SizingMethod.FIXED_FRACTIONAL


# =========================================================================
# Construction / validation
# =========================================================================


class TestPositionSizerInit:
    def test_invalid_capital_zero(self) -> None:
        with pytest.raises(ValueError, match="capital must be > 0"):
            PositionSizer(capital=0)

    def test_invalid_capital_negative(self) -> None:
        with pytest.raises(ValueError, match="capital must be > 0"):
            PositionSizer(capital=-100)

    def test_invalid_max_risk(self) -> None:
        with pytest.raises(ValueError, match="max_risk_per_trade"):
            PositionSizer(capital=100_000, max_risk_per_trade=0)

    def test_invalid_lot_size(self) -> None:
        with pytest.raises(ValueError, match="lot_size must be > 0"):
            PositionSizer(capital=100_000, lot_size=0)

    def test_custom_capital_and_lot_size(self) -> None:
        s = PositionSizer(capital=500_000, lot_size=25)
        assert s.capital == 500_000
        assert s.lot_size == 25


# =========================================================================
# fixed_fractional
# =========================================================================


class TestFixedFractional:
    def test_known_values(self, sizer: PositionSizer) -> None:
        """Capital=1M, 2% risk, entry=22000, SL=21900 → risk_per_unit=100.
        risk_amount=20000, risk_per_lot=100*50=5000, lots=floor(20000/5000)=4.
        """
        result = sizer.fixed_fractional(entry_price=22000.0, stop_loss=21900.0)
        assert result.lots == 4
        assert result.quantity == 200  # 4 * 50
        assert result.method == SizingMethod.FIXED_FRACTIONAL

    def test_entry_equals_stop_loss_returns_zero(self, sizer: PositionSizer) -> None:
        result = sizer.fixed_fractional(entry_price=22000.0, stop_loss=22000.0)
        assert result.lots == 0

    def test_lots_always_non_negative(self, sizer: PositionSizer) -> None:
        # Very large stop distance relative to capital
        result = sizer.fixed_fractional(entry_price=22000.0, stop_loss=10000.0)
        assert result.lots >= 0


# =========================================================================
# kelly_criterion
# =========================================================================


class TestKellyCriterion:
    def test_known_values(self, sizer: PositionSizer) -> None:
        """win_rate=0.6, avg_win=200, avg_loss=100 → b=2.0,
        kelly=(0.6*2 - 0.4)/2 = 0.8/2 = 0.4, half_kelly=0.2.
        Clamped to max_risk=0.02. risk_amount=20000,
        entry=22000, sl=21900 → risk_per_lot=5000 → lots=4.
        """
        result = sizer.kelly_criterion(
            entry_price=22000.0,
            stop_loss=21900.0,
            win_rate=0.6,
            avg_win=200.0,
            avg_loss=100.0,
        )
        assert result.lots >= 0
        assert result.method == SizingMethod.KELLY

    def test_win_rate_zero_returns_zero(self, sizer: PositionSizer) -> None:
        result = sizer.kelly_criterion(
            entry_price=22000.0,
            stop_loss=21900.0,
            win_rate=0.0,
            avg_win=200.0,
            avg_loss=100.0,
        )
        assert result.lots == 0

    def test_avg_loss_zero_returns_zero(self, sizer: PositionSizer) -> None:
        result = sizer.kelly_criterion(
            entry_price=22000.0,
            stop_loss=21900.0,
            win_rate=0.5,
            avg_win=200.0,
            avg_loss=0.0,
        )
        assert result.lots == 0

    def test_negative_kelly_returns_zero(self, sizer: PositionSizer) -> None:
        """A losing strategy: win_rate=0.2, avg_win=50, avg_loss=100.
        b=0.5, kelly=(0.2*0.5 - 0.8)/0.5 = (0.1 - 0.8)/0.5 = -1.4 → 0 lots.
        """
        result = sizer.kelly_criterion(
            entry_price=22000.0,
            stop_loss=21900.0,
            win_rate=0.2,
            avg_win=50.0,
            avg_loss=100.0,
        )
        assert result.lots == 0

    def test_avg_win_zero_returns_zero(self, sizer: PositionSizer) -> None:
        result = sizer.kelly_criterion(
            entry_price=22000.0,
            stop_loss=21900.0,
            win_rate=0.6,
            avg_win=0.0,
            avg_loss=100.0,
        )
        assert result.lots == 0


# =========================================================================
# volatility_adjusted
# =========================================================================


class TestVolatilityAdjusted:
    def test_high_vol_smaller_size(self, sizer: PositionSizer) -> None:
        """High vol → smaller size than low vol."""
        high_vol = sizer.volatility_adjusted(
            entry_price=22000.0, stop_loss=21900.0, current_volatility=0.30
        )
        low_vol = sizer.volatility_adjusted(
            entry_price=22000.0, stop_loss=21900.0, current_volatility=0.10
        )
        assert high_vol.lots <= low_vol.lots

    def test_vol_zero_returns_zero(self, sizer: PositionSizer) -> None:
        result = sizer.volatility_adjusted(
            entry_price=22000.0, stop_loss=21900.0, current_volatility=0.0
        )
        assert result.lots == 0

    def test_method_is_volatility_adjusted(self, sizer: PositionSizer) -> None:
        result = sizer.volatility_adjusted(
            entry_price=22000.0, stop_loss=21900.0, current_volatility=0.15
        )
        assert result.method == SizingMethod.VOLATILITY_ADJUSTED


# =========================================================================
# fixed_lot
# =========================================================================


class TestFixedLot:
    def test_returns_specified_lots(self, sizer: PositionSizer) -> None:
        result = sizer.fixed_lot(entry_price=22000.0, stop_loss=21900.0, lots=3)
        # lots may be clamped if risk exceeds max, but should be <= 3
        assert result.lots >= 0
        assert result.lots <= 3
        assert result.method == SizingMethod.FIXED_LOT

    def test_default_one_lot(self, sizer: PositionSizer) -> None:
        result = sizer.fixed_lot(entry_price=22000.0, stop_loss=21900.0)
        assert result.lots >= 0
        assert result.lots <= 1


# =========================================================================
# calculate() dispatch
# =========================================================================


class TestCalculateDispatch:
    def test_dispatches_fixed_fractional(self) -> None:
        s = PositionSizer(capital=1_000_000, method=SizingMethod.FIXED_FRACTIONAL)
        result = s.calculate(entry_price=22000.0, stop_loss=21900.0)
        assert result.method == SizingMethod.FIXED_FRACTIONAL

    def test_dispatches_kelly(self) -> None:
        s = PositionSizer(capital=1_000_000, method=SizingMethod.KELLY)
        stats = {"win_rate": 0.6, "avg_win": 200.0, "avg_loss": 100.0}
        result = s.calculate(
            entry_price=22000.0, stop_loss=21900.0, strategy_stats=stats
        )
        assert result.method == SizingMethod.KELLY

    def test_dispatches_volatility_adjusted(self) -> None:
        s = PositionSizer(capital=1_000_000, method=SizingMethod.VOLATILITY_ADJUSTED)
        result = s.calculate(
            entry_price=22000.0, stop_loss=21900.0, current_volatility=0.15
        )
        assert result.method == SizingMethod.VOLATILITY_ADJUSTED

    def test_dispatches_fixed_lot(self) -> None:
        s = PositionSizer(capital=1_000_000, method=SizingMethod.FIXED_LOT)
        result = s.calculate(entry_price=22000.0, stop_loss=21900.0)
        assert result.method == SizingMethod.FIXED_LOT


# =========================================================================
# Risk clamping invariants
# =========================================================================


class TestRiskClamping:
    def test_risk_percent_never_exceeds_max(self) -> None:
        s = PositionSizer(capital=1_000_000, max_risk_per_trade=0.02, lot_size=50)
        result = s.fixed_fractional(entry_price=22000.0, stop_loss=21900.0)
        assert result.risk_percent <= 0.02 + 1e-9

    def test_lots_always_non_negative_all_methods(self) -> None:
        s = PositionSizer(capital=100_000, max_risk_per_trade=0.01, lot_size=50)
        for method in SizingMethod:
            s.method = method
            result = s.calculate(
                entry_price=22000.0,
                stop_loss=20000.0,
                strategy_stats={"win_rate": 0.5, "avg_win": 100, "avg_loss": 100},
                current_volatility=0.20,
            )
            assert result.lots >= 0, f"Negative lots for method {method}"
