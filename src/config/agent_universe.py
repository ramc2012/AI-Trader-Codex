"""Shared watchlist and agent universe definitions."""

from __future__ import annotations

from typing import Iterable

NIFTY_SYMBOL = "NSE:NIFTY50-INDEX"
BANKNIFTY_SYMBOL = "NSE:NIFTYBANK-INDEX"
SENSEX_SYMBOL = "BSE:SENSEX-INDEX"
FINNIFTY_SYMBOL = "NSE:FINNIFTY-INDEX"
MIDCPNIFTY_SYMBOL = "NSE:NIFTYMIDCAP50-INDEX"

# Current Nifty 50 constituents (updated March 2026).
# Key changes applied vs original list:
#   - SHREECEM removed (exited Nifty 50 Dec 2023) → SHRIRAMFIN added
#   - BEL (Bharat Electronics) added (entered Nifty 50 2024)
NIFTY50_WATCHLIST_SYMBOLS: list[str] = [
    # Financials
    "NSE:HDFCBANK-EQ", "NSE:ICICIBANK-EQ", "NSE:KOTAKBANK-EQ",
    "NSE:AXISBANK-EQ", "NSE:SBIN-EQ", "NSE:INDUSINDBK-EQ",
    "NSE:BAJFINANCE-EQ", "NSE:BAJAJFINSV-EQ", "NSE:SHRIRAMFIN-EQ",
    "NSE:HDFCLIFE-EQ", "NSE:SBILIFE-EQ",
    # IT / Technology
    "NSE:TCS-EQ", "NSE:INFY-EQ", "NSE:HCLTECH-EQ", "NSE:WIPRO-EQ",
    "NSE:TECHM-EQ", "NSE:LTIM-EQ",
    # Energy / Oil & Gas
    "NSE:RELIANCE-EQ", "NSE:ONGC-EQ", "NSE:BPCL-EQ", "NSE:NTPC-EQ",
    "NSE:POWERGRID-EQ", "NSE:COALINDIA-EQ",
    # Consumer / FMCG
    "NSE:HINDUNILVR-EQ", "NSE:ITC-EQ", "NSE:NESTLEIND-EQ",
    "NSE:BRITANNIA-EQ", "NSE:TATACONSUM-EQ",
    # Auto
    "NSE:MARUTI-EQ", "NSE:BAJAJ-AUTO-EQ", "NSE:HEROMOTOCO-EQ",
    "NSE:EICHERMOT-EQ", "NSE:TATAMOTORS-EQ", "NSE:MM-EQ",
    # Industrials / Infra
    "NSE:LT-EQ", "NSE:ADANIPORTS-EQ", "NSE:BEL-EQ",
    # Metals / Materials
    "NSE:TATASTEEL-EQ", "NSE:JSWSTEEL-EQ", "NSE:HINDALCO-EQ",
    "NSE:GRASIM-EQ", "NSE:ULTRACEMCO-EQ",
    # Pharma / Healthcare
    "NSE:SUNPHARMA-EQ", "NSE:DRREDDY-EQ", "NSE:CIPLA-EQ",
    "NSE:DIVISLAB-EQ", "NSE:APOLLOHOSP-EQ",
    # Telecom / Media
    "NSE:BHARTIARTL-EQ",
    # Conglomerate / Other
    "NSE:ADANIENT-EQ", "NSE:ASIANPAINT-EQ", "NSE:TITAN-EQ",
]

LEGACY_AGENT_NSE_INDEX_ONLY_SYMBOLS: list[str] = [
    NIFTY_SYMBOL,
    BANKNIFTY_SYMBOL,
    FINNIFTY_SYMBOL,
    MIDCPNIFTY_SYMBOL,
    SENSEX_SYMBOL,
]

# Previous bundled default universe before the March 2026 Nifty 50 refresh.
# When this exact legacy default is supplied via env/UI, treat it as an
# outdated implicit default and upgrade it to the current universe.
LEGACY_AGENT_NSE_SYMBOLS_PRE_MARCH_2026: list[str] = [
    NIFTY_SYMBOL,
    BANKNIFTY_SYMBOL,
    FINNIFTY_SYMBOL,
    MIDCPNIFTY_SYMBOL,
    SENSEX_SYMBOL,
    "NSE:RELIANCE-EQ", "NSE:TCS-EQ", "NSE:INFY-EQ", "NSE:HDFCBANK-EQ",
    "NSE:ICICIBANK-EQ", "NSE:HINDUNILVR-EQ", "NSE:SBIN-EQ", "NSE:BHARTIARTL-EQ",
    "NSE:ITC-EQ", "NSE:KOTAKBANK-EQ", "NSE:LT-EQ", "NSE:AXISBANK-EQ",
    "NSE:ASIANPAINT-EQ", "NSE:MARUTI-EQ", "NSE:BAJFINANCE-EQ", "NSE:HCLTECH-EQ",
    "NSE:WIPRO-EQ", "NSE:TITAN-EQ", "NSE:SUNPHARMA-EQ", "NSE:ULTRACEMCO-EQ",
    "NSE:ONGC-EQ", "NSE:NTPC-EQ", "NSE:POWERGRID-EQ", "NSE:NESTLEIND-EQ",
    "NSE:TECHM-EQ", "NSE:CIPLA-EQ", "NSE:DIVISLAB-EQ", "NSE:GRASIM-EQ",
    "NSE:ADANIPORTS-EQ", "NSE:BAJAJ-AUTO-EQ", "NSE:HEROMOTOCO-EQ",
    "NSE:EICHERMOT-EQ", "NSE:APOLLOHOSP-EQ", "NSE:TATAMOTORS-EQ",
    "NSE:TATASTEEL-EQ", "NSE:JSWSTEEL-EQ", "NSE:INDUSINDBK-EQ",
    "NSE:HINDALCO-EQ", "NSE:COALINDIA-EQ", "NSE:DRREDDY-EQ", "NSE:BPCL-EQ",
    "NSE:TATACONSUM-EQ", "NSE:BRITANNIA-EQ", "NSE:BAJAJFINSV-EQ",
    "NSE:SHREECEM-EQ", "NSE:SBILIFE-EQ", "NSE:HDFCLIFE-EQ", "NSE:ADANIENT-EQ",
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


def parse_symbol_values(values: str | Iterable[str] | None) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        return unique_symbols(values.split(","))
    return unique_symbols(values)


def normalize_nse_agent_symbols(values: str | Iterable[str] | None) -> list[str]:
    parsed = parse_symbol_values(values)
    if not parsed:
        return list(DEFAULT_AGENT_NSE_SYMBOLS)
    if parsed == LEGACY_AGENT_NSE_INDEX_ONLY_SYMBOLS:
        return list(DEFAULT_AGENT_NSE_SYMBOLS)
    if parsed == LEGACY_AGENT_NSE_SYMBOLS_PRE_MARCH_2026:
        return list(DEFAULT_AGENT_NSE_SYMBOLS)
    return parsed


def to_csv(values: Iterable[str]) -> str:
    return ",".join(unique_symbols(values))
