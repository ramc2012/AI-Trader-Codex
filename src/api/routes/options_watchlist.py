"""API route for ATM Options Watchlist — monitors nearest-expiry ATM CE/PE for all FNO stocks."""

from datetime import datetime
from typing import Any, List

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from src.api.dependencies import get_fyers_client, get_instrument_registry, get_atm_registry
from src.config.fno_constants import EQUITY_FNO
from src.config.market_hours import is_market_open as check_nse_open, is_market_holiday
from src.watchlist.atm_registry import ATMRegistryService
from src.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/options-watchlist", tags=["Options-Watchlist"])

class ATMOptionMetric(BaseModel):
    symbol: str
    underlying: str
    option_type: str  # CE | PE
    strike: float
    spot: float = 0.0
    expiry: str
    market: str
    ltp: float = 0.0
    vtt: int = 0  # volume
    oi: int = 0
    oi_change: int = 0
    macd: Optional[float] = None
    macd_prev: Optional[float] = None
    rsi: Optional[float] = None

class ATMWatchlistResponse(BaseModel):
    timestamp: str
    results: List[ATMOptionMetric]
    is_warmed: bool
    is_market_open: bool
    is_holiday: bool

@router.get("/atm", response_model=ATMWatchlistResponse)
async def get_atm_watchlist(
    market: str = Query("NSE"),
    limit: int = Query(209, ge=1, le=209),
    offset: int = Query(0, ge=0),
    atm_registry: ATMRegistryService = Depends(get_atm_registry)
) -> Any:
    """Fetch ATM CE/PE for a specific market (NSE, US, CRYPTO)."""
    all_atm = atm_registry.get_all_atm(market=market)
    
    # Sort by underlying name for consistent UI display
    all_atm.sort(key=lambda x: x.underlying)
    
    subset = all_atm[offset : offset + limit]
    
    results = []
    for meta in subset:
        # CE
        results.append(ATMOptionMetric(
            symbol=meta.ce_symbol,
            underlying=meta.underlying,
            option_type="CE",
            strike=meta.strike,
            spot=meta.spot,
            expiry=meta.expiry,
            market=meta.market,
            ltp=meta.ce_ltp,
            vtt=meta.ce_volume,
            oi=meta.ce_oi,
            macd=meta.ce_macd,
            macd_prev=meta.ce_macd_prev,
            rsi=meta.ce_rsi
        ))
        # PE
        results.append(ATMOptionMetric(
            symbol=meta.pe_symbol,
            underlying=meta.underlying,
            option_type="PE",
            strike=meta.strike,
            spot=meta.spot,
            expiry=meta.expiry,
            market=meta.market,
            ltp=meta.pe_ltp,
            vtt=meta.pe_volume,
            oi=meta.pe_oi,
            macd=meta.pe_macd,
            macd_prev=meta.pe_macd_prev,
            rsi=meta.pe_rsi
        ))

    is_open = check_nse_open()
    is_holiday = is_market_holiday()
    
    if not is_open:
        logger.info("atm_watchlist_fetch_market_closed", is_holiday=is_holiday)

    return {
        "timestamp": datetime.now().isoformat(),
        "results": results,
        "is_warmed": atm_registry.is_warmed,
        "is_market_open": is_open,
        "is_holiday": is_holiday
    }
