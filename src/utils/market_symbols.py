"""Helpers for market-symbol classification and currency handling."""

from __future__ import annotations

from typing import Tuple


def infer_currency(symbol: str) -> str:
    """Infer trading currency from canonical symbol prefix."""
    token = (symbol or "").upper()
    if token.startswith("US:"):
        return "USD"
    if token.startswith("CRYPTO:"):
        # Current crypto universe uses USDT quote pairs.
        return "USD"
    return "INR"


def infer_currency_symbol(symbol: str) -> str:
    """Return currency symbol for a trading symbol."""
    code = infer_currency(symbol)
    if code == "USD":
        return "$"
    return "₹"


def infer_fx_to_inr(symbol: str, usd_inr_rate: float = 83.0) -> float:
    """Return FX multiplier for converting symbol-currency amounts to INR."""
    return float(usd_inr_rate) if infer_currency(symbol) == "USD" else 1.0


def classify_market(symbol: str) -> str:
    """Return market bucket for routing or labels."""
    token = (symbol or "").upper()
    if token.startswith("US:"):
        return "US"
    if token.startswith("CRYPTO:"):
        return "CRYPTO"
    if token.startswith("BSE:"):
        return "BSE"
    return "NSE"


def normalize_symbol_label(symbol: str) -> str:
    """Compact symbol for UI labels."""
    token = (symbol or "").strip()
    return token.split(":")[-1]


def parse_currency_context(symbol: str, usd_inr_rate: float = 83.0) -> Tuple[str, str, float]:
    """Return (currency, symbol, fx_to_inr) tuple."""
    return (
        infer_currency(symbol),
        infer_currency_symbol(symbol),
        infer_fx_to_inr(symbol, usd_inr_rate=usd_inr_rate),
    )
