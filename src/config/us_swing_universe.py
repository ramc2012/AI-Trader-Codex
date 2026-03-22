"""Curated US swing-trading universe used for research and live scanning."""

from __future__ import annotations

from typing import Iterable

US_SWING_BENCHMARK_SYMBOL = "US:SPY"
US_SWING_BENCHMARK_TICKER = "SPY"

US_SWING_SECTOR_TICKERS: dict[str, list[str]] = {
    "Technology": [
        "AAPL", "MSFT", "ORCL", "CRM", "ADBE", "NOW", "INTU", "IBM", "ACN", "SNOW",
        "PANW", "CRWD", "FTNT", "SNPS", "ANSS", "CDNS", "PLTR", "DDOG", "TEAM", "ADSK",
    ],
    "Semiconductors": [
        "NVDA", "AMD", "AVGO", "QCOM", "TXN", "MU", "AMAT", "LRCX", "KLAC", "INTC",
        "ADI", "MCHP", "NXPI", "MRVL", "ON", "MPWR", "TER", "SWKS",
    ],
    "Communication Media": [
        "GOOGL", "META", "NFLX", "DIS", "TMUS", "VZ", "T", "CMCSA", "CHTR", "EA",
        "TTWO", "WBD", "FOXA", "PARA", "RBLX", "ROKU", "SNAP",
    ],
    "Consumer Discretionary": [
        "AMZN", "TSLA", "HD", "LOW", "MCD", "SBUX", "NKE", "BKNG", "TJX", "ROST",
        "MAR", "HLT", "CMG", "DRI", "YUM", "ORLY", "AZO", "EBAY", "LULU", "RCL",
    ],
    "Consumer Staples": [
        "COST", "WMT", "PG", "KO", "PEP", "MDLZ", "CL", "KMB", "GIS", "KHC",
        "KR", "SYY", "HSY", "MNST", "KDP", "PM", "MO", "EL",
    ],
    "Financials": [
        "JPM", "BAC", "WFC", "C", "GS", "MS", "BLK", "SCHW", "PNC", "USB",
        "BK", "AXP", "COF", "SPGI", "CME", "ICE", "CB", "MMC", "TRV", "AJG",
        "MCO", "AIG",
    ],
    "Healthcare": [
        "UNH", "JNJ", "LLY", "ABBV", "MRK", "PFE", "BMY", "AMGN", "GILD", "REGN",
        "VRTX", "ISRG", "BSX", "MDT", "SYK", "DHR", "TMO", "ABT", "ZTS", "HUM",
        "HCA",
    ],
    "Industrials": [
        "CAT", "DE", "GE", "HON", "RTX", "LMT", "NOC", "ETN", "PH", "EMR",
        "UPS", "FDX", "WM", "CARR", "TT", "PWR", "URI", "GD", "NSC", "UNP",
        "RSG",
    ],
    "Energy Utilities": [
        "XOM", "CVX", "COP", "SLB", "EOG", "OXY", "MPC", "VLO", "PSX", "HAL",
        "DVN", "FANG", "NEE", "SO", "DUK", "AEP", "EXC", "SRE", "XEL", "PEG",
    ],
    "Materials Real Estate": [
        "LIN", "APD", "SHW", "ECL", "DD", "FCX", "NEM", "NUE", "STLD", "DOW",
        "LYB", "MLM", "AMT", "PLD", "EQIX", "CCI", "O", "SPG", "WELL", "PSA",
        "VICI", "CBRE", "VMC",
    ],
}


def build_us_symbol(ticker: str) -> str:
    token = str(ticker or "").strip().upper()
    return f"US:{token}" if token else ""


def unique_tickers(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    rows: list[str] = []
    for raw in values:
        token = str(raw or "").strip().upper()
        if not token or token in seen:
            continue
        seen.add(token)
        rows.append(token)
    return rows


US_SWING_TICKERS: list[str] = unique_tickers(
    ticker
    for rows in US_SWING_SECTOR_TICKERS.values()
    for ticker in rows
)

US_SWING_SYMBOLS: list[str] = [build_us_symbol(ticker) for ticker in US_SWING_TICKERS]
US_SWING_SECTOR_BY_TICKER: dict[str, str] = {
    ticker: sector
    for sector, tickers in US_SWING_SECTOR_TICKERS.items()
    for ticker in tickers
}
US_SWING_SECTOR_BY_SYMBOL: dict[str, str] = {
    build_us_symbol(ticker): sector
    for ticker, sector in US_SWING_SECTOR_BY_TICKER.items()
}
