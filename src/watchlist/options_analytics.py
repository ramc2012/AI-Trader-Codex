"""
Advanced Options Analytics - Bloomberg Terminal Grade
Options chain, Greeks, IV surface, skew analysis, and term structure
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.stats import norm

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class OptionGreeks:
    """Option Greeks and risk metrics."""

    # First-order Greeks
    delta: float  # Rate of change of option price with respect to underlying
    gamma: float  # Rate of change of delta
    theta: float  # Time decay
    vega: float  # Sensitivity to volatility
    rho: float  # Sensitivity to interest rate

    # Second-order Greeks
    vanna: Optional[float] = None  # dDelta/dVol
    charm: Optional[float] = None  # dDelta/dTime
    vomma: Optional[float] = None  # dVega/dVol
    vera: Optional[float] = None  # dRho/dVol

    # Risk metrics
    delta_dollars: Optional[float] = None
    gamma_dollars: Optional[float] = None
    theta_dollars: Optional[float] = None


@dataclass
class OptionContract:
    """Individual option contract data."""

    symbol: str
    strike: float
    expiry: datetime
    option_type: str  # CE or PE
    underlying: str

    # Market data
    ltp: float
    bid: float
    ask: float
    iv: float  # Implied Volatility
    volume: int
    oi: int  # Open Interest
    oi_change: Optional[int] = None

    # Greeks
    greeks: Optional[OptionGreeks] = None

    # Theoretical pricing
    theoretical_price: Optional[float] = None
    edge: Optional[float] = None  # LTP - theoretical


@dataclass
class OptionChain:
    """Complete options chain for an expiry."""

    underlying_symbol: str
    underlying_price: float
    expiry: datetime
    timestamp: datetime

    # Calls and Puts
    calls: Dict[float, OptionContract]  # strike -> contract
    puts: Dict[float, OptionContract]

    # Chain-level metrics
    atm_strike: float
    atm_iv: float
    pcr_volume: float  # Put-Call Ratio by volume
    pcr_oi: float  # Put-Call Ratio by OI
    max_pain: Optional[float] = None  # Strike with max pain

    # IV Skew
    iv_skew: Optional[Dict[float, float]] = None  # strike -> IV
    skew_slope: Optional[float] = None


@dataclass
class IVSurface:
    """Implied Volatility Surface across strikes and expiries."""

    underlying_symbol: str
    timestamp: datetime

    # Surface data: (strike, expiry) -> IV
    surface: Dict[Tuple[float, datetime], float]

    # Strike dimension (moneyness)
    moneyness_range: List[float]  # e.g., [0.8, 0.9, 1.0, 1.1, 1.2]

    # Term structure (time to expiry in days)
    term_structure: List[int]  # e.g., [7, 14, 30, 60, 90]

    # ATM IV term structure
    atm_term_structure: Dict[int, float]  # days -> ATM IV


@dataclass
class OptionAnalytics:
    """Advanced options analytics output."""

    underlying_symbol: str
    underlying_price: float
    timestamp: datetime

    # Options chains by expiry
    chains: Dict[datetime, OptionChain]

    # IV Surface
    iv_surface: Optional[IVSurface] = None

    # Aggregate metrics
    total_call_oi: int = 0
    total_put_oi: int = 0
    total_call_volume: int = 0
    total_put_volume: int = 0

    # Support/Resistance from OI
    max_call_oi_strike: Optional[float] = None
    max_put_oi_strike: Optional[float] = None

    # Volatility metrics
    current_hv: Optional[float] = None  # Historical Volatility
    iv_rank: Optional[float] = None  # IV percentile
    iv_percentile: Optional[float] = None


class BlackScholes:
    """Black-Scholes option pricing model."""

    @staticmethod
    def calculate_greeks(
        spot: float,
        strike: float,
        time_to_expiry: float,  # in years
        volatility: float,  # annualized
        rate: float = 0.07,  # risk-free rate
        option_type: str = "CE",
    ) -> OptionGreeks:
        """
        Calculate option Greeks using Black-Scholes model.

        Args:
            spot: Current underlying price
            strike: Strike price
            time_to_expiry: Time to expiry in years
            volatility: Implied volatility (annualized)
            rate: Risk-free rate
            option_type: CE (call) or PE (put)

        Returns:
            OptionGreeks object
        """
        if time_to_expiry <= 0:
            # At expiry
            if option_type == "CE":
                delta = 1.0 if spot > strike else 0.0
            else:
                delta = -1.0 if spot < strike else 0.0
            return OptionGreeks(
                delta=delta,
                gamma=0.0,
                theta=0.0,
                vega=0.0,
                rho=0.0,
            )

        # Calculate d1 and d2
        d1 = (
            np.log(spot / strike) + (rate + 0.5 * volatility**2) * time_to_expiry
        ) / (volatility * np.sqrt(time_to_expiry))
        d2 = d1 - volatility * np.sqrt(time_to_expiry)

        # Calculate Greeks
        if option_type == "CE":
            delta = norm.cdf(d1)
            theta = -(
                spot * norm.pdf(d1) * volatility / (2 * np.sqrt(time_to_expiry))
                + rate * strike * np.exp(-rate * time_to_expiry) * norm.cdf(d2)
            ) / 365  # Daily theta
            rho = (
                strike
                * time_to_expiry
                * np.exp(-rate * time_to_expiry)
                * norm.cdf(d2)
                / 100
            )  # Per 1% change
        else:  # PE
            delta = norm.cdf(d1) - 1
            theta = -(
                spot * norm.pdf(d1) * volatility / (2 * np.sqrt(time_to_expiry))
                - rate * strike * np.exp(-rate * time_to_expiry) * norm.cdf(-d2)
            ) / 365
            rho = (
                -strike
                * time_to_expiry
                * np.exp(-rate * time_to_expiry)
                * norm.cdf(-d2)
                / 100
            )

        # Greeks common to both calls and puts
        gamma = norm.pdf(d1) / (spot * volatility * np.sqrt(time_to_expiry))
        vega = spot * norm.pdf(d1) * np.sqrt(time_to_expiry) / 100  # Per 1% change in vol

        # Second-order Greeks
        vanna = -norm.pdf(d1) * d2 / volatility
        charm = -norm.pdf(d1) * (
            rate / (volatility * np.sqrt(time_to_expiry)) - d2 / (2 * time_to_expiry)
        ) / 365
        vomma = vega * d1 * d2 / volatility

        return OptionGreeks(
            delta=delta,
            gamma=gamma,
            theta=theta,
            vega=vega,
            rho=rho,
            vanna=vanna,
            charm=charm,
            vomma=vomma,
        )

    @staticmethod
    def calculate_iv(
        spot: float,
        strike: float,
        time_to_expiry: float,
        premium: float,
        option_type: str = "CE",
        rate: float = 0.07,
    ) -> Optional[float]:
        """
        Calculate implied volatility using Newton-Raphson method.

        Returns:
            Implied volatility (annualized) or None if failed
        """
        try:
            # Initial guess
            iv = 0.3

            for _ in range(100):  # Max iterations
                # Calculate price and vega
                d1 = (
                    np.log(spot / strike) + (rate + 0.5 * iv**2) * time_to_expiry
                ) / (iv * np.sqrt(time_to_expiry))
                d2 = d1 - iv * np.sqrt(time_to_expiry)

                if option_type == "CE":
                    price = spot * norm.cdf(d1) - strike * np.exp(
                        -rate * time_to_expiry
                    ) * norm.cdf(d2)
                else:
                    price = strike * np.exp(-rate * time_to_expiry) * norm.cdf(
                        -d2
                    ) - spot * norm.cdf(-d1)

                vega = spot * norm.pdf(d1) * np.sqrt(time_to_expiry)

                # Newton-Raphson update
                diff = price - premium
                if abs(diff) < 0.01:  # Converged
                    return iv

                if vega > 0:
                    iv = iv - diff / vega
                else:
                    break

                # Bounds check
                if iv < 0.01:
                    iv = 0.01
                elif iv > 5.0:
                    iv = 5.0

            return iv if iv > 0 else None

        except Exception:
            return None


class OptionsAnalyzer:
    """
    Advanced options analytics engine.
    Calculates Greeks, IV surface, skew, and generates insights.
    """

    def __init__(self):
        logger.info("options_analyzer_initialized")

    def calculate_max_pain(self, chain: OptionChain) -> float:
        """
        Calculate max pain strike - the strike where option sellers
        would lose the least money at expiry.

        Args:
            chain: OptionChain object

        Returns:
            Max pain strike price
        """
        pain_by_strike = {}

        # Get all strikes
        all_strikes = sorted(set(list(chain.calls.keys()) + list(chain.puts.keys())))

        for strike in all_strikes:
            total_pain = 0.0

            # Calculate pain for all calls
            for call_strike, call in chain.calls.items():
                if strike > call_strike:
                    # ITM call - seller pays
                    total_pain += (strike - call_strike) * call.oi

            # Calculate pain for all puts
            for put_strike, put in chain.puts.items():
                if strike < put_strike:
                    # ITM put - seller pays
                    total_pain += (put_strike - strike) * put.oi

            pain_by_strike[strike] = total_pain

        # Find strike with minimum pain
        if pain_by_strike:
            max_pain_strike = min(pain_by_strike, key=pain_by_strike.get)
            logger.debug("max_pain_calculated", strike=max_pain_strike)
            return max_pain_strike

        return chain.atm_strike

    def calculate_iv_skew(self, chain: OptionChain) -> Dict[float, float]:
        """
        Calculate IV skew across strikes.

        Args:
            chain: OptionChain object

        Returns:
            Dictionary mapping strike to IV
        """
        skew = {}

        for strike, contract in chain.calls.items():
            if contract.iv:
                skew[strike] = contract.iv

        logger.debug("iv_skew_calculated", strikes=len(skew))
        return skew

    def build_iv_surface(
        self, analytics: OptionAnalytics
    ) -> Optional[IVSurface]:
        """
        Build 3D implied volatility surface across strikes and time.

        Args:
            analytics: OptionAnalytics with multiple expiries

        Returns:
            IVSurface object or None
        """
        try:
            surface = {}
            atm_term_structure = {}

            underlying_price = analytics.underlying_price

            for expiry, chain in analytics.chains.items():
                days_to_expiry = (expiry - datetime.now()).days

                # Add ATM IV to term structure
                atm_term_structure[days_to_expiry] = chain.atm_iv

                # Add all strikes to surface
                for strike, call in chain.calls.items():
                    if call.iv:
                        surface[(strike, expiry)] = call.iv

            if not surface:
                return None

            # Calculate moneyness range
            moneyness_range = sorted(
                set(strike / underlying_price for strike, _ in surface.keys())
            )

            # Get term structure days
            term_structure = sorted(set(atm_term_structure.keys()))

            iv_surface = IVSurface(
                underlying_symbol=analytics.underlying_symbol,
                timestamp=datetime.now(),
                surface=surface,
                moneyness_range=moneyness_range,
                term_structure=term_structure,
                atm_term_structure=atm_term_structure,
            )

            logger.info(
                "iv_surface_built",
                points=len(surface),
                expiries=len(analytics.chains),
            )

            return iv_surface

        except Exception as exc:
            logger.error("build_iv_surface_failed", error=str(exc))
            return None
