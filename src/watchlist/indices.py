"""
Advanced Watchlist for Indian Indices - Bloomberg Terminal Grade
Supports: NIFTY 50, SENSEX, BANK NIFTY, FIN NIFTY, MIDCAP NIFTY
Includes spot and futures tracking with real-time data
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from src.config.constants import build_monthly_futures_symbol
from src.config.market_hours import IST
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class IndexSymbol:
    """Index symbol configuration."""

    name: str
    display_name: str
    spot_symbol: str  # NSE spot symbol
    futures_root: str  # Root name for building futures symbol dynamically
    exchange: str = "NSE"
    lot_size: int = 1
    tick_size: float = 0.05
    sector: str = "Index"

    @property
    def futures_symbol(self) -> str:
        """Current front-month futures symbol, computed dynamically."""
        now = datetime.now(tz=IST)
        return build_monthly_futures_symbol(
            root=self.futures_root,
            exchange=self.exchange,
            dt=now,
        )


# Major Indian Indices Configuration — futures symbols are computed dynamically
INDIAN_INDICES = {
    "NIFTY": IndexSymbol(
        name="NIFTY",
        display_name="Nifty 50",
        spot_symbol="NSE:NIFTY50-INDEX",
        futures_root="NIFTY",
        lot_size=25,
        tick_size=0.05,
        sector="Broad Market",
    ),
    "BANKNIFTY": IndexSymbol(
        name="BANKNIFTY",
        display_name="Bank Nifty",
        spot_symbol="NSE:NIFTYBANK-INDEX",
        futures_root="BANKNIFTY",
        lot_size=15,
        tick_size=0.05,
        sector="Banking",
    ),
    "FINNIFTY": IndexSymbol(
        name="FINNIFTY",
        display_name="Fin Nifty",
        spot_symbol="NSE:FINNIFTY-INDEX",
        futures_root="FINNIFTY",
        lot_size=25,
        tick_size=0.05,
        sector="Financial Services",
    ),
    "MIDCPNIFTY": IndexSymbol(
        name="MIDCPNIFTY",
        display_name="Midcap Nifty",
        spot_symbol="NSE:NIFTYMIDCAP50-INDEX",
        futures_root="MIDCPNIFTY",
        lot_size=50,
        tick_size=0.05,
        sector="Midcap",
    ),
    "SENSEX": IndexSymbol(
        name="SENSEX",
        display_name="BSE Sensex",
        spot_symbol="BSE:SENSEX-INDEX",
        futures_root="SENSEX",
        exchange="BSE",
        lot_size=10,
        tick_size=0.05,
        sector="Broad Market",
    ),
}


@dataclass
class MarketData:
    """Real-time market data for an index."""

    symbol: str
    timestamp: datetime
    ltp: float  # Last traded price
    open: float
    high: float
    low: float
    close: float
    volume: int
    oi: Optional[int] = None  # Open interest (futures only)
    bid: Optional[float] = None
    ask: Optional[float] = None
    bid_qty: Optional[int] = None
    ask_qty: Optional[int] = None
    change: Optional[float] = None
    change_pct: Optional[float] = None
    vwap: Optional[float] = None
    upper_circuit: Optional[float] = None
    lower_circuit: Optional[float] = None
    total_buy_qty: Optional[int] = None
    total_sell_qty: Optional[int] = None


@dataclass
class TechnicalIndicators:
    """Technical analysis indicators for an index."""

    symbol: str
    timestamp: datetime

    # Moving Averages
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    sma_100: Optional[float] = None
    sma_200: Optional[float] = None
    ema_9: Optional[float] = None
    ema_21: Optional[float] = None
    ema_50: Optional[float] = None

    # Momentum Indicators
    rsi_14: Optional[float] = None
    rsi_signal: Optional[str] = None  # Overbought/Oversold/Neutral
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_histogram: Optional[float] = None

    # Volatility Indicators
    atr_14: Optional[float] = None
    bb_upper: Optional[float] = None
    bb_middle: Optional[float] = None
    bb_lower: Optional[float] = None
    bb_width: Optional[float] = None

    # Trend Indicators
    adx_14: Optional[float] = None
    adx_signal: Optional[str] = None  # Strong/Weak/No Trend
    supertrend: Optional[float] = None
    supertrend_direction: Optional[str] = None  # Bullish/Bearish

    # Volume Indicators
    obv: Optional[float] = None
    vwap: Optional[float] = None

    # Support/Resistance Levels
    pivot_point: Optional[float] = None
    r1: Optional[float] = None
    r2: Optional[float] = None
    r3: Optional[float] = None
    s1: Optional[float] = None
    s2: Optional[float] = None
    s3: Optional[float] = None


@dataclass
class MarketProfile:
    """Market Profile (TPO) data for an index."""

    symbol: str
    date: datetime
    poc: float  # Point of Control - highest volume price
    vah: float  # Value Area High
    val: float  # Value Area Low
    value_area_volume_pct: float  # Typically 70%

    # TPO data structure
    tpo_data: Dict[float, List[str]]  # price -> list of time periods
    volume_profile: Dict[float, int]  # price -> volume

    # Market structure
    initial_balance_high: Optional[float] = None
    initial_balance_low: Optional[float] = None
    day_type: Optional[str] = None  # Trend/Normal/Non-trend

    # Previous day levels
    prev_poc: Optional[float] = None
    prev_vah: Optional[float] = None
    prev_val: Optional[float] = None


@dataclass
class OrderFlowData:
    """Order flow and microstructure data."""

    symbol: str
    timestamp: datetime

    # Bid-Ask Data
    bid_ask_spread: float
    bid_ask_spread_pct: float
    mid_price: float

    # Depth of Market (DOM)
    bid_depth: List[tuple[float, int]]  # [(price, qty), ...]
    ask_depth: List[tuple[float, int]]
    total_bid_volume: int
    total_ask_volume: int
    buy_sell_ratio: float

    # Tape Reading
    aggressive_buys: int  # Trades at ask
    aggressive_sells: int  # Trades at bid
    trade_imbalance: float  # (buys - sells) / (buys + sells)

    # Volume Metrics
    volume_delta: int  # Buy volume - Sell volume
    cumulative_delta: int
    max_volume_price: float  # Price with highest volume

    # Time & Sales
    last_trades: List[Dict]  # Recent trade data


class IndexWatchlist:
    """
    Bloomberg-grade watchlist manager for Indian indices.
    Manages real-time data, technical analysis, and order flow for indices.
    """

    def __init__(self):
        self.indices = INDIAN_INDICES
        self.market_data: Dict[str, MarketData] = {}
        self.technical_data: Dict[str, TechnicalIndicators] = {}
        self.market_profiles: Dict[str, MarketProfile] = {}
        self.order_flow: Dict[str, OrderFlowData] = {}

        logger.info(
            "watchlist_initialized",
            indices=list(self.indices.keys()),
            count=len(self.indices),
        )

    def get_all_symbols(self) -> List[str]:
        """Get all index symbols (spot)."""
        return [idx.spot_symbol for idx in self.indices.values()]

    def get_all_futures_symbols(self) -> List[str]:
        """Get all futures symbols."""
        return [idx.futures_symbol for idx in self.indices.values()]

    def get_symbol_info(self, index_name: str) -> Optional[IndexSymbol]:
        """Get symbol configuration for an index."""
        return self.indices.get(index_name.upper())

    def update_market_data(self, symbol: str, data: MarketData) -> None:
        """Update real-time market data for a symbol."""
        self.market_data[symbol] = data
        logger.debug("market_data_updated", symbol=symbol, ltp=data.ltp)

    def get_market_data(self, symbol: str) -> Optional[MarketData]:
        """Get current market data for a symbol."""
        return self.market_data.get(symbol)

    def update_technical_indicators(
        self, symbol: str, indicators: TechnicalIndicators
    ) -> None:
        """Update technical indicators for a symbol."""
        self.technical_data[symbol] = indicators
        logger.debug("technical_indicators_updated", symbol=symbol)

    def get_technical_indicators(self, symbol: str) -> Optional[TechnicalIndicators]:
        """Get technical indicators for a symbol."""
        return self.technical_data.get(symbol)

    def update_market_profile(self, symbol: str, profile: MarketProfile) -> None:
        """Update market profile data for a symbol."""
        self.market_profiles[symbol] = profile
        logger.debug("market_profile_updated", symbol=symbol, poc=profile.poc)

    def get_market_profile(self, symbol: str) -> Optional[MarketProfile]:
        """Get market profile for a symbol."""
        return self.market_profiles.get(symbol)

    def update_order_flow(self, symbol: str, flow: OrderFlowData) -> None:
        """Update order flow data for a symbol."""
        self.order_flow[symbol] = flow
        logger.debug("order_flow_updated", symbol=symbol)

    def get_order_flow(self, symbol: str) -> Optional[OrderFlowData]:
        """Get order flow data for a symbol."""
        return self.order_flow.get(symbol)

    def get_watchlist_summary(self) -> Dict:
        """
        Get summary of all indices in the watchlist.
        Bloomberg-style overview with key metrics.
        """
        summary = []

        for name, idx in self.indices.items():
            spot_data = self.market_data.get(idx.spot_symbol)
            # Try current-month futures first; if not in cache (e.g. expired today),
            # roll to next month — Fyers expires front-month on last Thursday.
            futures_data = self.market_data.get(idx.futures_symbol)
            if futures_data is None:
                next_month_dt = (datetime.now(tz=IST).replace(day=1) + timedelta(days=32))
                next_sym = build_monthly_futures_symbol(
                    root=idx.futures_root,
                    exchange=idx.exchange,
                    dt=next_month_dt,
                )
                futures_data = self.market_data.get(next_sym)
            tech = self.technical_data.get(idx.spot_symbol)
            profile = self.market_profiles.get(idx.spot_symbol)
            flow = self.order_flow.get(idx.spot_symbol)

            item = {
                "name": name,
                "display_name": idx.display_name,
                "sector": idx.sector,
                "spot": {
                    "symbol": idx.spot_symbol,
                    "ltp": spot_data.ltp if spot_data else None,
                    "change": spot_data.change if spot_data else None,
                    "change_pct": spot_data.change_pct if spot_data else None,
                    "volume": spot_data.volume if spot_data else None,
                } if spot_data else None,
                "futures": {
                    "symbol": idx.futures_symbol,
                    "ltp": futures_data.ltp if futures_data else None,
                    "oi": futures_data.oi if futures_data else None,
                    "change": futures_data.change if futures_data else None,
                } if futures_data else None,
                "technicals": {
                    "rsi": tech.rsi_14 if tech else None,
                    "rsi_signal": tech.rsi_signal if tech else None,
                    "macd_signal": "Bullish" if tech and tech.macd and tech.macd_signal and tech.macd > tech.macd_signal else "Bearish" if tech and tech.macd and tech.macd_signal else None,
                    "trend": tech.adx_signal if tech else None,
                } if tech else None,
                "market_profile": {
                    "poc": profile.poc if profile else None,
                    "vah": profile.vah if profile else None,
                    "val": profile.val if profile else None,
                } if profile else None,
                "order_flow": {
                    "spread": flow.bid_ask_spread if flow else None,
                    "imbalance": flow.trade_imbalance if flow else None,
                    "buy_sell_ratio": flow.buy_sell_ratio if flow else None,
                } if flow else None,
            }

            summary.append(item)

        return {
            "timestamp": datetime.now().isoformat(),
            "indices": summary,
            "total_count": len(summary),
        }
