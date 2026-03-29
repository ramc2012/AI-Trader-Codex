"""API route for ATM Options Watchlist — monitors nearest-expiry ATM CE/PE for all FNO stocks."""

from datetime import datetime
from typing import Any, List

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from src.api.dependencies import get_fyers_client, get_instrument_registry
from src.config.fno_constants import EQUITY_FNO
from src.watchlist.options_data_service import OptionsDataService
from src.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/options-watchlist", tags=["Options-Watchlist"])

class ATMOptionMetric(BaseModel):
    symbol: str
    underlying: str
    option_type: str  # CE | PE
    strike: float
    expiry: str
    ltp: float = 0.0
    vtt: int = 0  # volume
    oi: int = 0
    oi_change: int = 0
    macd: float = 0.0
    rsi: float = 0.0

class ATMWatchlistResponse(BaseModel):
    timestamp: str
    results: List[ATMOptionMetric]

@router.get("/atm", response_model=ATMWatchlistResponse)
async def get_atm_watchlist(
    limit: int = Query(50, ge=1, le=209),
    offset: int = Query(0, ge=0),
    fyers: Any = Depends(get_fyers_client)
) -> Any:
    """Fetch ATM CE/PE for FNO stocks."""
    options_service = OptionsDataService(fyers)
    results = []
    
    # Get all FNO symbols
    fno_symbols = list(EQUITY_FNO.keys())
    subset = fno_symbols[offset : offset + limit]
    
    for sym in subset:
        try:
            # Resolve ATM for this underlying
            underlying = f"NSE:{sym}-EQ"
            chain_data = options_service.get_canonical_chain(underlying, strike_count=2, include_expiries=1)
            
            expiries = chain_data.get("data", {}).get("expiryData", [])
            if not expiries:
                continue
            
            near_expiry = expiries[0]
            spot = near_expiry.get("spot", 0.0)
            strikes = near_expiry.get("strikes", [])
            
            if not strikes or spot <= 0:
                continue
                
            # Find the strike closest to spot
            atm_row = min(strikes, key=lambda x: abs(x["strike"] - spot))
            atm_strike = atm_row["strike"]
            expiry = near_expiry.get("expiry", "N/A")
            
            ce = atm_row.get("ce", {})
            pe = atm_row.get("pe", {})
            
            # CE
            results.append(ATMOptionMetric(
                symbol=ce.get("symbol", f"{sym}{expiry}{atm_strike}CE"),
                underlying=sym,
                option_type="CE",
                strike=atm_strike,
                expiry=expiry,
                ltp=ce.get("ltp", 0.0),
                oi=ce.get("oi", 0),
                oi_change=ce.get("oich", 0),
                vtt=ce.get("volume", 0),
                macd=0.0, 
                rsi=0.0
            ))
            
            # PE
            results.append(ATMOptionMetric(
                symbol=pe.get("symbol", f"{sym}{expiry}{atm_strike}PE"),
                underlying=sym,
                option_type="PE",
                strike=atm_strike,
                expiry=expiry,
                ltp=pe.get("ltp", 0.0),
                oi=pe.get("oi", 0),
                oi_change=pe.get("oich", 0),
                vtt=pe.get("volume", 0),
                macd=0.0,
                rsi=0.0
            ))
        except Exception as e:
            logger.debug(f"Error resolving ATM for {sym}: {e}")
            continue

    return {
        "timestamp": datetime.now().isoformat(),
        "results": results
    }
