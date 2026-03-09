"""Black-Scholes option pricing and Greeks calculation.

Provides functions for:
- Black-Scholes call/put pricing
- Implied Volatility via Brent's method
- Greeks: delta, gamma, theta, vega, rho
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Constants
TRADING_DAYS_PER_YEAR = 252
RISK_FREE_RATE = 0.07  # 7% (India)


def _norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    """Standard normal probability density function."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _d1(s: float, k: float, t: float, r: float, sigma: float) -> float:
    """Calculate d1 in Black-Scholes formula."""
    if t <= 0 or sigma <= 0:
        return 0.0
    return (math.log(s / k) + (r + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))


def _d2(s: float, k: float, t: float, r: float, sigma: float) -> float:
    """Calculate d2 in Black-Scholes formula."""
    return _d1(s, k, t, r, sigma) - sigma * math.sqrt(t)


def black_scholes_price(
    spot: float,
    strike: float,
    time_to_expiry: float,
    risk_free_rate: float,
    sigma: float,
    option_type: Literal["CE", "PE"] = "CE",
) -> float:
    """Calculate Black-Scholes option price.

    Args:
        spot: Current underlying price.
        strike: Option strike price.
        time_to_expiry: Time to expiry in years.
        risk_free_rate: Risk-free interest rate (annualised).
        sigma: Implied volatility (annualised).
        option_type: 'CE' for call, 'PE' for put.

    Returns:
        Theoretical option price.
    """
    if time_to_expiry <= 0:
        # At or past expiry — intrinsic value only
        if option_type == "CE":
            return max(spot - strike, 0.0)
        return max(strike - spot, 0.0)

    d1 = _d1(spot, strike, time_to_expiry, risk_free_rate, sigma)
    d2 = d1 - sigma * math.sqrt(time_to_expiry)
    discount = math.exp(-risk_free_rate * time_to_expiry)

    if option_type == "CE":
        return spot * _norm_cdf(d1) - strike * discount * _norm_cdf(d2)
    return strike * discount * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


@dataclass(frozen=True)
class Greeks:
    """Container for all option Greeks."""

    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float


def calculate_greeks(
    spot: float,
    strike: float,
    time_to_expiry: float,
    risk_free_rate: float,
    sigma: float,
    option_type: Literal["CE", "PE"] = "CE",
) -> Greeks:
    """Calculate all option Greeks.

    Args:
        spot: Current underlying price.
        strike: Option strike price.
        time_to_expiry: Time to expiry in years.
        risk_free_rate: Risk-free interest rate.
        sigma: Implied volatility.
        option_type: 'CE' or 'PE'.

    Returns:
        Greeks dataclass with delta, gamma, theta, vega, rho.
    """
    if time_to_expiry <= 0 or sigma <= 0:
        intrinsic_ce = 1.0 if spot > strike else 0.0
        intrinsic_pe = -1.0 if spot < strike else 0.0
        return Greeks(
            delta=intrinsic_ce if option_type == "CE" else intrinsic_pe,
            gamma=0.0,
            theta=0.0,
            vega=0.0,
            rho=0.0,
        )

    t = time_to_expiry
    sqrt_t = math.sqrt(t)
    d1 = _d1(spot, strike, t, risk_free_rate, sigma)
    d2 = d1 - sigma * sqrt_t
    discount = math.exp(-risk_free_rate * t)
    pdf_d1 = _norm_pdf(d1)

    # Gamma (same for call and put)
    gamma = pdf_d1 / (spot * sigma * sqrt_t)

    # Vega (same for call and put) — per 1% move in vol
    vega = spot * pdf_d1 * sqrt_t / 100.0

    if option_type == "CE":
        delta = _norm_cdf(d1)
        theta = (
            -(spot * pdf_d1 * sigma) / (2 * sqrt_t)
            - risk_free_rate * strike * discount * _norm_cdf(d2)
        ) / TRADING_DAYS_PER_YEAR
        rho = strike * t * discount * _norm_cdf(d2) / 100.0
    else:
        delta = _norm_cdf(d1) - 1.0
        theta = (
            -(spot * pdf_d1 * sigma) / (2 * sqrt_t)
            + risk_free_rate * strike * discount * _norm_cdf(-d2)
        ) / TRADING_DAYS_PER_YEAR
        rho = -strike * t * discount * _norm_cdf(-d2) / 100.0

    return Greeks(delta=delta, gamma=gamma, theta=theta, vega=vega, rho=rho)


def calculate_iv(
    market_price: float,
    spot: float,
    strike: float,
    time_to_expiry: float,
    risk_free_rate: float = RISK_FREE_RATE,
    option_type: Literal["CE", "PE"] = "CE",
    tol: float = 1e-6,
    max_iter: int = 100,
) -> float | None:
    """Calculate Implied Volatility using Brent's method (bisection fallback).

    Args:
        market_price: Observed option market price.
        spot: Current underlying price.
        strike: Option strike price.
        time_to_expiry: Time to expiry in years.
        risk_free_rate: Risk-free rate.
        option_type: 'CE' or 'PE'.
        tol: Convergence tolerance.
        max_iter: Maximum iterations.

    Returns:
        Annualised implied volatility, or None if it cannot converge.
    """
    if market_price <= 0 or time_to_expiry <= 0:
        return None

    # Intrinsic value check
    if option_type == "CE":
        intrinsic = max(spot - strike, 0.0)
    else:
        intrinsic = max(strike - spot, 0.0)

    if market_price < intrinsic - tol:
        return None

    # Bisection method (robust)
    low, high = 0.001, 5.0

    for _ in range(max_iter):
        mid = (low + high) / 2.0
        price = black_scholes_price(spot, strike, time_to_expiry, risk_free_rate, mid, option_type)
        diff = price - market_price

        if abs(diff) < tol:
            return mid

        if diff > 0:
            high = mid
        else:
            low = mid

        if high - low < tol:
            return mid

    return (low + high) / 2.0


def time_to_expiry_years(days_to_expiry: int) -> float:
    """Convert days to expiry into years (based on trading days)."""
    return max(days_to_expiry, 0) / TRADING_DAYS_PER_YEAR


def greeks_to_dict(g: Greeks) -> dict[str, float]:
    """Convert Greeks dataclass to dictionary."""
    return {
        "delta": round(g.delta, 6),
        "gamma": round(g.gamma, 8),
        "theta": round(g.theta, 4),
        "vega": round(g.vega, 4),
        "rho": round(g.rho, 4),
    }
