"""Relative Rotation Graph (RRG) engine.

Computes RS-Ratio and RS-Momentum for a universe of symbols
relative to a benchmark, used for 2D and 3D RRG visualisation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from src.database.models import IndexOHLC
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ── Universe group definitions ────────────────────────────────────────────

UNIVERSE_GROUPS: dict[str, dict[str, Any]] = {
    "NIFTY50": {
        "label": "Nifty 50 vs Nifty",
        "benchmark": "NSE:NIFTY50-INDEX",
        "symbols": [
            "NSE:RELIANCE-EQ", "NSE:TCS-EQ", "NSE:HDFCBANK-EQ", "NSE:INFY-EQ",
            "NSE:ICICIBANK-EQ", "NSE:HINDUNILVR-EQ", "NSE:ITC-EQ", "NSE:SBIN-EQ",
            "NSE:BHARTIARTL-EQ", "NSE:KOTAKBANK-EQ", "NSE:LT-EQ", "NSE:AXISBANK-EQ",
            "NSE:BAJFINANCE-EQ", "NSE:ASIANPAINT-EQ", "NSE:MARUTI-EQ",
            "NSE:SUNPHARMA-EQ", "NSE:TATAMOTORS-EQ", "NSE:TITAN-EQ",
            "NSE:WIPRO-EQ", "NSE:HCLTECH-EQ",
        ],
    },
    "BANKING": {
        "label": "Banking Sector",
        "benchmark": "NSE:NIFTY50-INDEX",
        "symbols": [
            "NSE:HDFCBANK-EQ", "NSE:ICICIBANK-EQ", "NSE:SBIN-EQ", "NSE:KOTAKBANK-EQ",
            "NSE:AXISBANK-EQ", "NSE:INDUSINDBK-EQ", "NSE:BANKBARODA-EQ",
            "NSE:PNB-EQ", "NSE:FEDERALBNK-EQ", "NSE:IDFCFIRSTB-EQ",
        ],
    },
    "IT": {
        "label": "IT Sector",
        "benchmark": "NSE:NIFTY50-INDEX",
        "symbols": [
            "NSE:TCS-EQ", "NSE:INFY-EQ", "NSE:HCLTECH-EQ", "NSE:WIPRO-EQ",
            "NSE:TECHM-EQ", "NSE:LTIM-EQ", "NSE:MPHASIS-EQ", "NSE:COFORGE-EQ",
            "NSE:PERSISTENT-EQ", "NSE:LTTS-EQ",
        ],
    },
    "AUTO": {
        "label": "Auto Sector",
        "benchmark": "NSE:NIFTY50-INDEX",
        "symbols": [
            "NSE:TATAMOTORS-EQ", "NSE:M&M-EQ", "NSE:MARUTI-EQ", "NSE:BAJAJ-AUTO-EQ",
            "NSE:HEROMOTOCO-EQ", "NSE:EICHERMOT-EQ", "NSE:TVSMOTOR-EQ",
            "NSE:ASHOKLEY-EQ", "NSE:APOLLOTYRE-EQ", "NSE:BALKRISIND-EQ",
        ],
    },
    "PHARMA": {
        "label": "Pharma Sector",
        "benchmark": "NSE:NIFTY50-INDEX",
        "symbols": [
            "NSE:SUNPHARMA-EQ", "NSE:DRREDDY-EQ", "NSE:CIPLA-EQ", "NSE:DIVISLAB-EQ",
            "NSE:AUROPHARMA-EQ", "NSE:LUPIN-EQ", "NSE:BIOCON-EQ", "NSE:TORNTPHARM-EQ",
            "NSE:ALKEM-EQ", "NSE:IPCALAB-EQ",
        ],
    },
    "METALS": {
        "label": "Metals & Mining",
        "benchmark": "NSE:NIFTY50-INDEX",
        "symbols": [
            "NSE:TATASTEEL-EQ", "NSE:JSWSTEEL-EQ", "NSE:HINDALCO-EQ",
            "NSE:VEDL-EQ", "NSE:JINDALSTEL-EQ", "NSE:SAIL-EQ",
            "NSE:NMDC-EQ", "NSE:NATIONALUM-EQ", "NSE:HINDCOPPER-EQ", "NSE:COALINDIA-EQ",
        ],
    },
    "FMCG": {
        "label": "FMCG Sector",
        "benchmark": "NSE:NIFTY50-INDEX",
        "symbols": [
            "NSE:HINDUNILVR-EQ", "NSE:ITC-EQ", "NSE:NESTLEIND-EQ", "NSE:BRITANNIA-EQ",
            "NSE:DABUR-EQ", "NSE:MARICO-EQ", "NSE:GODREJCP-EQ",
            "NSE:COLPAL-EQ", "NSE:TATACONSUM-EQ",
        ],
    },
    "ENERGY": {
        "label": "Energy & Oil",
        "benchmark": "NSE:NIFTY50-INDEX",
        "symbols": [
            "NSE:RELIANCE-EQ", "NSE:ONGC-EQ", "NSE:BPCL-EQ", "NSE:IOC-EQ",
            "NSE:HINDPETRO-EQ", "NSE:GAIL-EQ", "NSE:PETRONET-EQ", "NSE:IGL-EQ",
            "NSE:NTPC-EQ", "NSE:POWERGRID-EQ",
        ],
    },
    "FINANCE": {
        "label": "Financial Services",
        "benchmark": "NSE:NIFTY50-INDEX",
        "symbols": [
            "NSE:BAJFINANCE-EQ", "NSE:BAJAJFINSV-EQ", "NSE:HDFCAMC-EQ",
            "NSE:SBILIFE-EQ", "NSE:HDFCLIFE-EQ", "NSE:ICICIPRULI-EQ",
            "NSE:CHOLAFIN-EQ", "NSE:SHRIRAMFIN-EQ", "NSE:MUTHOOTFIN-EQ", "NSE:PEL-EQ",
        ],
    },
    "INFRA": {
        "label": "Infrastructure & Capital Goods",
        "benchmark": "NSE:NIFTY50-INDEX",
        "symbols": [
            "NSE:LT-EQ", "NSE:ADANIPORTS-EQ", "NSE:SIEMENS-EQ", "NSE:ABB-EQ",
            "NSE:HAL-EQ", "NSE:BEL-EQ", "NSE:CUMMINSIND-EQ", "NSE:POLYCAB-EQ",
            "NSE:BHEL-EQ", "NSE:CONCOR-EQ",
        ],
    },
    "REALTY": {
        "label": "Realty Sector",
        "benchmark": "NSE:NIFTY50-INDEX",
        "symbols": [
            "NSE:DLF-EQ", "NSE:GODREJPROP-EQ", "NSE:OBEROIRLTY-EQ",
        ],
    },
    "INDICES": {
        "label": "Sector Indices vs Nifty",
        "benchmark": "NSE:NIFTY50-INDEX",
        "symbols": [
            "NSE:NIFTYBANK-INDEX", "NSE:NIFTYIT-INDEX",
        ],
    },
}


@dataclass
class RRGPoint:
    """Single RRG data point for a symbol at a timestamp."""

    symbol: str
    timestamp: str
    rs_ratio: float
    rs_momentum: float
    quadrant: str  # Leading, Weakening, Lagging, Improving


def _classify_quadrant(rs_ratio: float, rs_momentum: float) -> str:
    """Classify into RRG quadrant based on 100 baseline."""
    if rs_ratio >= 100 and rs_momentum >= 100:
        return "Leading"
    elif rs_ratio >= 100 and rs_momentum < 100:
        return "Weakening"
    elif rs_ratio < 100 and rs_momentum < 100:
        return "Lagging"
    else:
        return "Improving"


def compute_rrg(
    symbol_candles: dict[str, Sequence[IndexOHLC]],
    benchmark_candles: Sequence[IndexOHLC],
    lookback: int = 14,
    smoothing: int = 5,
    tail_length: int = 8,
) -> dict[str, list[dict[str, Any]]]:
    """Compute RRG data for multiple symbols vs a benchmark.

    Algorithm:
    1. RS-Line = (symbol close / benchmark close) * 100
    2. RS-Ratio = EMA(RS-Line, smoothing) normalised to 100
    3. RS-Momentum = rate of change of RS-Ratio, normalised to 100

    Args:
        symbol_candles: Map of symbol -> OHLC candles (sorted by timestamp ASC).
        benchmark_candles: Benchmark OHLC candles.
        lookback: Lookback period for RS calculation.
        smoothing: EMA smoothing period.
        tail_length: Number of trailing points to return.

    Returns:
        Dict mapping symbol to list of RRG point dicts.
    """
    if len(benchmark_candles) < lookback + smoothing:
        return {}

    # Build benchmark close series indexed by date
    bench_closes: dict[str, float] = {}
    for c in benchmark_candles:
        key = c.timestamp.strftime("%Y-%m-%d %H:%M")
        bench_closes[key] = float(c.close)

    results: dict[str, list[dict[str, Any]]] = {}

    for symbol, candles in symbol_candles.items():
        if len(candles) < lookback + smoothing:
            continue

        # 1. Compute RS-Line
        rs_line: list[tuple[str, float]] = []
        for c in candles:
            key = c.timestamp.strftime("%Y-%m-%d %H:%M")
            bench = bench_closes.get(key)
            if bench and bench > 0:
                rs_line.append((key, (float(c.close) / bench) * 100))

        if len(rs_line) < lookback + smoothing:
            continue

        # 2. EMA smoothing of RS-Line → RS-Ratio
        values = [r[1] for r in rs_line]
        rs_ratio = _ema_smooth(values, smoothing)

        # Normalise RS-Ratio around 100
        mean_ratio = sum(rs_ratio[-lookback:]) / lookback if len(rs_ratio) >= lookback else 100
        std_ratio = _std(rs_ratio[-lookback:]) if len(rs_ratio) >= lookback else 1.0
        if std_ratio < 0.001:
            std_ratio = 1.0
        rs_ratio_norm = [100 + (v - mean_ratio) / std_ratio * 10 for v in rs_ratio]

        # 3. RS-Momentum = rate of change of RS-Ratio
        rs_momentum: list[float] = [100.0]
        for i in range(1, len(rs_ratio_norm)):
            if rs_ratio_norm[i - 1] != 0:
                roc = ((rs_ratio_norm[i] - rs_ratio_norm[i - 1]) / abs(rs_ratio_norm[i - 1])) * 1000
            else:
                roc = 0
            rs_momentum.append(100 + roc)

        # Build result tail
        points: list[dict[str, Any]] = []
        start_idx = max(0, len(rs_line) - tail_length)
        for i in range(start_idx, len(rs_line)):
            ratio_val = rs_ratio_norm[i] if i < len(rs_ratio_norm) else 100
            mom_val = rs_momentum[i] if i < len(rs_momentum) else 100
            points.append({
                "symbol": symbol,
                "timestamp": rs_line[i][0],
                "rs_ratio": round(ratio_val, 2),
                "rs_momentum": round(mom_val, 2),
                "quadrant": _classify_quadrant(ratio_val, mom_val),
            })

        results[symbol] = points

    return results


def _ema_smooth(values: list[float], period: int) -> list[float]:
    """EMA smoothing."""
    if not values or period < 1:
        return values
    k = 2.0 / (period + 1)
    result = [values[0]]
    for i in range(1, len(values)):
        result.append(values[i] * k + result[-1] * (1 - k))
    return result


def _std(values: list[float]) -> float:
    """Standard deviation."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return variance ** 0.5
