"""Shared watchlist and agent universe definitions."""

from __future__ import annotations

from typing import Iterable

NIFTY_SYMBOL = "NSE:NIFTY50-INDEX"
BANKNIFTY_SYMBOL = "NSE:NIFTYBANK-INDEX"
SENSEX_SYMBOL = "BSE:SENSEX-INDEX"
FINNIFTY_SYMBOL = "NSE:FINNIFTY-INDEX"
MIDCPNIFTY_SYMBOL = "NSE:NIFTYMIDCAP50-INDEX"

NIFTY50_WATCHLIST_SYMBOLS: list[str] = [
    "NSE:RELIANCE-EQ", "NSE:TCS-EQ", "NSE:INFY-EQ", "NSE:HDFCBANK-EQ",
    "NSE:ICICIBANK-EQ", "NSE:HINDUNILVR-EQ", "NSE:SBIN-EQ", "NSE:BHARTIARTL-EQ",
    "NSE:ITC-EQ", "NSE:KOTAKBANK-EQ", "NSE:LT-EQ", "NSE:AXISBANK-EQ",
    "NSE:ASIANPAINT-EQ", "NSE:MARUTI-EQ", "NSE:BAJFINANCE-EQ",
    "NSE:HCLTECH-EQ", "NSE:WIPRO-EQ", "NSE:TITAN-EQ", "NSE:SUNPHARMA-EQ",
    "NSE:ULTRACEMCO-EQ", "NSE:ONGC-EQ", "NSE:NTPC-EQ", "NSE:POWERGRID-EQ",
    "NSE:NESTLEIND-EQ", "NSE:TECHM-EQ", "NSE:CIPLA-EQ", "NSE:DIVISLAB-EQ",
    "NSE:GRASIM-EQ", "NSE:ADANIPORTS-EQ", "NSE:BAJAJ-AUTO-EQ",
    "NSE:HEROMOTOCO-EQ", "NSE:EICHERMOT-EQ", "NSE:APOLLOHOSP-EQ",
    "NSE:TATAMOTORS-EQ", "NSE:TATASTEEL-EQ", "NSE:JSWSTEEL-EQ",
    "NSE:INDUSINDBK-EQ", "NSE:HINDALCO-EQ", "NSE:COALINDIA-EQ",
    "NSE:DRREDDY-EQ", "NSE:BPCL-EQ", "NSE:TATACONSUM-EQ",
    "NSE:BRITANNIA-EQ", "NSE:BAJAJFINSV-EQ", "NSE:SHREECEM-EQ",
    "NSE:SBILIFE-EQ", "NSE:HDFCLIFE-EQ", "NSE:ADANIENT-EQ",
    "NSE:LTIM-EQ", "NSE:MM-EQ",
]

DEFAULT_AGENT_NSE_SYMBOLS: list[str] = [
    NIFTY_SYMBOL,
    BANKNIFTY_SYMBOL,
    FINNIFTY_SYMBOL,
    MIDCPNIFTY_SYMBOL,
    SENSEX_SYMBOL,
    *NIFTY50_WATCHLIST_SYMBOLS,
]

DEFAULT_AGENT_US_SYMBOLS: list[str] = [
    "US:SPY",
    "US:QQQ",
    "US:DIA",
    "US:IWM",
    "US:AAPL",
    "US:AMZN",
    "US:JPM",
    "US:XOM",
    "US:UNH",
    "US:CAT",
]

DEFAULT_AGENT_CRYPTO_SYMBOLS: list[str] = [
    "CRYPTO:BTCUSDT",
    "CRYPTO:ETHUSDT",
    "CRYPTO:BNBUSDT",
    "CRYPTO:SOLUSDT",
    "CRYPTO:XRPUSDT",
    "CRYPTO:ADAUSDT",
    "CRYPTO:DOGEUSDT",
    "CRYPTO:AVAXUSDT",
    "CRYPTO:DOTUSDT",
    "CRYPTO:LINKUSDT",
]


def unique_symbols(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    for raw in values:
        symbol = str(raw or "").strip()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        items.append(symbol)
    return items


def to_csv(values: Iterable[str]) -> str:
    return ",".join(unique_symbols(values))
