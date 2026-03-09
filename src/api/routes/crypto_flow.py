"""Crypto correlation stub API routes.

Placeholder that returns mock correlation data between
BTC/ETH and NIFTY.  This will be replaced with live data
once crypto data feeds are integrated.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db
from src.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/crypto", tags=["crypto"])


# =========================================================================
# Mock Data
# =========================================================================

_MOCK_CORRELATIONS: list[dict[str, Any]] = [
    {"pair": "BTC-NIFTY", "correlation": 0.35, "period": "30D"},
    {"pair": "BTC-NIFTY", "correlation": 0.28, "period": "90D"},
    {"pair": "BTC-NIFTY", "correlation": 0.22, "period": "1Y"},
    {"pair": "ETH-NIFTY", "correlation": 0.31, "period": "30D"},
    {"pair": "ETH-NIFTY", "correlation": 0.25, "period": "90D"},
    {"pair": "ETH-NIFTY", "correlation": 0.19, "period": "1Y"},
    {"pair": "BTC-BANKNIFTY", "correlation": 0.30, "period": "30D"},
    {"pair": "BTC-BANKNIFTY", "correlation": 0.24, "period": "90D"},
    {"pair": "ETH-BANKNIFTY", "correlation": 0.27, "period": "30D"},
    {"pair": "ETH-BANKNIFTY", "correlation": 0.21, "period": "90D"},
]


# =========================================================================
# Endpoints
# =========================================================================


@router.get("/snapshot")
async def get_crypto_snapshot(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return mock correlation data between BTC/ETH and NIFTY.

    This is a placeholder endpoint.  The correlation values are
    hard-coded and will be replaced with real calculations once
    crypto market data feeds (e.g. Binance, CoinGecko) are
    integrated into the data pipeline.
    """
    logger.info("crypto_snapshot_request")

    return {
        "correlations": _MOCK_CORRELATIONS,
        "note": "Stub data -- live crypto feed integration pending",
        "timestamp": datetime.utcnow().isoformat(),
    }
